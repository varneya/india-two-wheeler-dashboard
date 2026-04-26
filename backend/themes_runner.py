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


_TOKEN_RE = re.compile(r"[a-z][a-z']+")


def _tokenise(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def _attribute_reviews_to_themes(
    themes: list[dict], reviews: list[dict], target_bike_id: str
) -> list[dict]:
    """For each theme, compute the fraction of reviews most-likely-belonging
    to that theme that came from `target_bike_id`. Method-agnostic: scores
    each (review, theme) pair by Jaccard-style overlap between the review's
    word set and the theme's `keywords` list, then takes the argmax.

    Mutates the themes in place by adding `localized_share: float` and
    `bike_review_counts: dict[str, int]`. Themes with no clearly-assigned
    review get `localized_share=None` so the UI can hide the badge."""

    theme_keysets: list[tuple[set[str], dict]] = []
    for t in themes:
        kws = t.get("keywords") or []
        # Split each keyword on spaces so multi-word keywords contribute their
        # individual tokens to the match.
        tok = set()
        for kw in kws:
            tok.update(_tokenise(str(kw)))
        # Also fold in any words from the theme name as a fallback
        tok.update(_tokenise(t.get("name") or ""))
        theme_keysets.append((tok, t))

    # For each review, find the best-overlap theme
    counts_by_theme: list[dict[str, int]] = [dict() for _ in themes]
    for r in reviews:
        rid = r.get("bike_id")
        rtok = _tokenise(r.get("review_text"))
        if not rtok:
            continue
        best_idx, best_score = -1, 0
        for i, (kws, _t) in enumerate(theme_keysets):
            if not kws:
                continue
            overlap = len(rtok & kws)
            if overlap > best_score:
                best_idx, best_score = i, overlap
        if best_idx >= 0 and best_score > 0:
            d = counts_by_theme[best_idx]
            d[rid] = d.get(rid, 0) + 1

    for i, t in enumerate(themes):
        per_bike = counts_by_theme[i]
        total = sum(per_bike.values())
        if total == 0:
            t["localized_share"] = None
            t["bike_review_counts"] = {}
        else:
            t["localized_share"] = per_bike.get(target_bike_id, 0) / total
            t["bike_review_counts"] = per_bike

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

    if pool_scope == "brand":
        result = _attribute_reviews_to_themes(result, reviews, bike_id)

    # Persist with the resolved scope so the UI can disambiguate cached results.
    persisted_config = {**(config or {}), "pool_scope": pool_scope}
    database.save_themes_analysis(
        bike_id=bike_id, method=method, config=persisted_config, themes=result
    )
    print(f"[themes] {bike_id}: saved {len(result)} themes (scope={pool_scope})")

    return {"themes": result, "error": None}
