"""
Semantic Clustering — the "Solid upgrade" theme method.

Pipeline:
  1. Embed each review with Ollama nomic-embed-text (768-dim).
  2. Cluster the dense vectors with HDBSCAN.
     - No K to pick — HDBSCAN finds clusters of varying density.
     - Outlier reviews get cluster_id = -1 and are reported separately.
  3. Name each cluster via c-TF-IDF (the BERTopic technique).
  4. Sentiment per cluster via the existing pos/neg word recipe.

Compared to themes_tfidf:
  - Uses semantic similarity rather than bag-of-words. "smooth pickup" and
    "punchy acceleration" cluster together; TF-IDF treats them as unrelated.
  - HDBSCAN doesn't force every review into a cluster (good).
  - c-TF-IDF naming yields more distinctive labels.
"""

from __future__ import annotations

import hdbscan
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from themes_embeddings import (
    check_ollama_ready,
    cluster_label_from_terms,
    embed_texts,
    name_clusters_ctfidf,
    sentiment_for,
    shortest_snippet,
)


def _kmeans_with_silhouette(embeds: np.ndarray, k_min: int = 2, k_max: int = 8) -> np.ndarray:
    """KMeans fallback for small / low-density datasets where HDBSCAN
    returns all noise. Picks K via silhouette score."""
    n = len(embeds)
    k_max = min(k_max, max(2, n // 2))
    if k_min >= k_max:
        return KMeans(n_clusters=k_min, random_state=42, n_init=10).fit_predict(embeds)
    best_k, best_score, best_labels = k_min, -1.0, None
    for k in range(k_min, k_max + 1):
        try:
            km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(embeds)
            score = silhouette_score(embeds, km.labels_) if k < n else -1.0
            if score > best_score:
                best_k, best_score, best_labels = k, score, km.labels_
        except Exception:
            continue
    print(f"[semantic] KMeans fallback: k={best_k}, silhouette={best_score:.3f}")
    return best_labels if best_labels is not None else KMeans(
        n_clusters=k_min, random_state=42, n_init=10
    ).fit_predict(embeds)


def analyze(reviews: list[dict], min_cluster_size: int | None = None) -> list[dict] | dict:
    ok, err = check_ollama_ready()
    if not ok:
        return {"error": err}

    texts = [r.get("review_text") or "" for r in reviews if r.get("review_text")]
    if len(texts) < 5:
        return {"error": f"Need at least 5 reviews for clustering (have {len(texts)})."}

    # Adaptive: small datasets get min=2 so even 8 reviews can produce clusters.
    if min_cluster_size is None:
        min_cluster_size = 2 if len(texts) < 30 else max(3, len(texts) // 15)

    print(f"[semantic] embedding {len(texts)} reviews via Ollama…")
    embeds = embed_texts(texts)
    if not embeds.any():
        return {"error": "All embeddings came back empty — check Ollama logs."}

    print(f"[semantic] clustering with HDBSCAN (min_cluster_size={min_cluster_size})…")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(embeds)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_outliers = int((labels == -1).sum())
    print(f"[semantic] HDBSCAN found {n_clusters} clusters, {n_outliers} outliers")

    # Fallback: when reviews are sparse / too varied, HDBSCAN marks everything
    # as noise. Use KMeans with auto-K so the user still gets buckets.
    if n_clusters == 0:
        print("[semantic] HDBSCAN gave no clusters → falling back to KMeans + silhouette")
        labels = _kmeans_with_silhouette(embeds)
        n_clusters = len(set(labels))
        n_outliers = 0

    # c-TF-IDF naming
    terms_per_cluster = name_clusters_ctfidf(texts, labels, top_n=6)

    results: list[dict] = []
    for cid in sorted(set(labels)):
        if cid == -1:
            continue
        idxs = [i for i, lbl in enumerate(labels) if lbl == cid]
        cluster_texts = [texts[i] for i in idxs]
        terms = terms_per_cluster.get(int(cid), [])
        snippets = [s for s in (shortest_snippet(t) for t in cluster_texts) if s][:3]
        results.append({
            "name": cluster_label_from_terms(terms) or f"Theme {cid + 1}",
            "sentiment": sentiment_for(cluster_texts),
            "mention_count": len(idxs),
            "example_quotes": snippets,
            "keywords": terms,
        })

    # Add an Outliers theme so unbucketed reviews aren't hidden
    if n_outliers > 0:
        outlier_idxs = [i for i, lbl in enumerate(labels) if lbl == -1]
        outlier_texts = [texts[i] for i in outlier_idxs]
        snippets = [s for s in (shortest_snippet(t) for t in outlier_texts) if s][:3]
        results.append({
            "name": "Outliers (unique reviews)",
            "sentiment": sentiment_for(outlier_texts),
            "mention_count": n_outliers,
            "example_quotes": snippets,
            "keywords": [],
        })

    results.sort(key=lambda r: -r["mention_count"])
    return results
