"""
Bike-scoped dispatcher — routes to the correct theme engine
and saves the result against a specific bike_id.

Supports two scopes:
  pool_scope='bike'  — analyse only this bike's reviews (default; original behaviour)
  pool_scope='brand' — analyse every review of every bike under this bike's brand,
                       then attach a `localized_share` field to each theme that
                       reports the fraction of that theme's reviews attributable
                       to the originally-selected bike. Helps niche / low-review
                       bikes inherit signal from their siblings.
"""

import re

import database
import bike_catalogue
import themes_keyword
import themes_tfidf
import themes_llm
import themes_semantic
import themes_bertopic
import themes_quality


_TOKEN_RE = re.compile(r"[a-z][a-z']+")


def _tokenise(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def _attribute_and_enrich(
    themes: list[dict],
    reviews: list[dict],
    target_bike_id: str | None,
) -> list[dict]:
    """For each theme:
      - Assign every review whose word-set has any overlap with the theme's
        keywords. Tie-break by highest overlap.
      - Aggregate per-bike review counts (used for `localized_share` when a
        target bike is given) and per-theme average rating.

    Mutates `themes` in place by adding:
      - `bike_review_counts: dict[str, int]`
      - `localized_share: float | None`  (only meaningful when target_bike_id
                                          was provided AND ≥1 review attributed)
      - `avg_rating: float | None`       (mean of `overall_rating` across
                                          attributed reviews that have one)
    """

    theme_keysets: list[set[str]] = []
    for t in themes:
        tok: set[str] = set()
        for kw in (t.get("keywords") or []):
            tok.update(_tokenise(str(kw)))
        tok.update(_tokenise(t.get("name") or ""))
        theme_keysets.append(tok)

    counts_by_theme: list[dict[str, int]] = [dict() for _ in themes]
    rating_sums: list[float] = [0.0 for _ in themes]
    rating_n: list[int] = [0 for _ in themes]

    for r in reviews:
        rtok = _tokenise(r.get("review_text"))
        if not rtok:
            continue
        best_idx, best_score = -1, 0
        for i, kws in enumerate(theme_keysets):
            if not kws:
                continue
            overlap = len(rtok & kws)
            if overlap > best_score:
                best_idx, best_score = i, overlap
        if best_idx < 0 or best_score == 0:
            continue
        rid = r.get("bike_id")
        if rid is not None:
            counts_by_theme[best_idx][rid] = counts_by_theme[best_idx].get(rid, 0) + 1
        rating = r.get("overall_rating")
        if rating is not None:
            try:
                rating_sums[best_idx] += float(rating)
                rating_n[best_idx] += 1
            except (TypeError, ValueError):
                pass

    for i, t in enumerate(themes):
        per_bike = counts_by_theme[i]
        total = sum(per_bike.values())
        t["bike_review_counts"] = per_bike
        if target_bike_id and total > 0:
            t["localized_share"] = per_bike.get(target_bike_id, 0) / total
        else:
            t["localized_share"] = None
        t["avg_rating"] = (rating_sums[i] / rating_n[i]) if rating_n[i] > 0 else None
        t["rating_count"] = rating_n[i]

    return themes


def run_analysis(
    method: str,
    config: dict,
    bike_id: str,
    pool_scope: str = "bike",
) -> dict:
    """
    method: "keyword" | "tfidf" | "semantic" | "bertopic" | "llm"
    bike_id: which bike's themes to save against (and to localise around).
    pool_scope: "bike" (default) or "brand".
    Returns {"themes": [...], "error": None} or {"themes": None, "error": "..."}
    """
    if pool_scope == "brand":
        brand = bike_catalogue.brand_id_from_bike_id(bike_id)
        if not brand:
            return {
                "themes": None,
                "error": f"Cannot infer brand from bike_id={bike_id!r}; refusing brand-wide pool.",
            }
        reviews = database.get_reviews_by_scope("brand", brand)
        scope_label = f"brand={brand}"
    elif pool_scope == "bike":
        reviews = database.get_reviews_by_scope("bike", bike_id)
        scope_label = f"bike={bike_id}"
    else:
        return {"themes": None, "error": f"Unknown pool_scope: {pool_scope!r}"}

    if not reviews:
        return {
            "themes": None,
            "error": f"No reviews in database for {scope_label}. Run a reviews refresh first.",
        }

    print(
        f"[themes] {bike_id} '{method}' scope={pool_scope} on "
        f"{len(reviews)} reviews with config={config}"
    )

    if method == "keyword":
        custom = config.get("keywords") if isinstance(config, dict) else None
        if custom and not isinstance(custom, dict):
            custom = None
        result = themes_keyword.analyze(reviews, custom_keywords=custom)

    elif method == "tfidf":
        n = int(config.get("n_clusters", 6))
        result = themes_tfidf.analyze(reviews, n_clusters=n)

    elif method == "semantic":
        # "Solid upgrade" — Ollama embeddings + HDBSCAN + c-TF-IDF
        min_cs = int(config.get("min_cluster_size", 3))
        result = themes_semantic.analyze(reviews, min_cluster_size=min_cs)

    elif method == "bertopic":
        # "Power user" — adds UMAP + optional Mistral name refinement
        llm_naming = bool(config.get("llm_naming", True))
        result = themes_bertopic.analyze(reviews, llm_naming=llm_naming)

    elif method == "llm":
        backend = config.get("backend", "claude")
        result = themes_llm.analyze(reviews, backend=backend)

    else:
        return {"themes": None, "error": f"Unknown method: {method}"}

    if isinstance(result, dict) and "error" in result:
        return {"themes": None, "error": result["error"]}

    # Per-theme attribution: bike counts, localized share (brand scope only),
    # and avg rating from any reviews carrying overall_rating.
    target_bike = bike_id if pool_scope == "brand" else None
    result = _attribute_and_enrich(result, reviews, target_bike)

    # Quality metrics — method-agnostic NPMI + theme diversity over the
    # corpus we actually clustered.
    review_texts = [r.get("review_text") or "" for r in reviews if r.get("review_text")]
    theme_keywords = [t.get("keywords") or [] for t in result]
    metrics = themes_quality.compute_metrics(theme_keywords, review_texts)
    metrics["n_reviews"] = len(review_texts)

    # Persist with the resolved scope so the UI can disambiguate cached results.
    persisted_config = {**(config or {}), "pool_scope": pool_scope}
    database.save_themes_analysis(
        bike_id=bike_id,
        method=method,
        config=persisted_config,
        themes=result,
        metrics=metrics,
    )
    print(f"[themes] {bike_id}: saved {len(result)} themes (scope={pool_scope})")

    return {"themes": result, "metrics": metrics, "error": None}
