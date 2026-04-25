"""
Bike-scoped dispatcher — routes to the correct theme engine
and saves the result against a specific bike_id.
"""

import database
import themes_keyword
import themes_tfidf
import themes_llm
import themes_semantic
import themes_bertopic


def run_analysis(method: str, config: dict, bike_id: str) -> dict:
    """
    method: "keyword" | "tfidf" | "semantic" | "bertopic" | "llm"
    bike_id: which bike's reviews to analyse.
    Returns {"themes": [...], "error": None} or {"themes": None, "error": "..."}
    """
    reviews = database.get_all_reviews(bike_id=bike_id)
    if not reviews:
        return {"themes": None, "error": f"No reviews in database for {bike_id}. Run a reviews refresh first."}

    print(f"[themes] {bike_id} '{method}' on {len(reviews)} reviews with config={config}")

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

    database.save_themes_analysis(bike_id=bike_id, method=method, config=config, themes=result)
    print(f"[themes] {bike_id}: saved {len(result)} themes")

    return {"themes": result, "error": None}
