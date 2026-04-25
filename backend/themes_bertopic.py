"""
BERTopic-style pipeline — the "Power user" theme method.

Same stack BERTopic uses, but rolled by hand against our local Ollama
embedding service so we don't drag in `sentence-transformers` + torch:

  1. Embed each review (Ollama nomic-embed-text, 768-dim).
  2. UMAP dimensionality reduction → 5 dims. Dramatically improves
     clustering quality on dense embeddings.
  3. HDBSCAN on the reduced vectors.
  4. c-TF-IDF cluster naming.
  5. Optional: pass each cluster's top representative quotes to the local
     Mistral 7B for a 2-3 word "polished" theme name.

Compared to themes_semantic:
  - UMAP step gives tighter clusters, especially when N gets big (>200 reviews).
  - LLM-refined names produce labels like "Riding Comfort" instead of
    "comfort / cushion / seat".

Slower (~30s vs ~10s on 100 reviews) but the labels are noticeably better.
"""

from __future__ import annotations

import json
import re

import hdbscan
import numpy as np
import umap
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
from themes_llm import _analyze_ollama  # reused for direct Ollama chat calls
import requests as http_requests

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"


def _refine_names_via_llm(
    cluster_summaries: list[dict],
    model: str = "mistral:7b",
) -> dict[int, str]:
    """For each cluster, ask the local LLM to coin a short 2-3 word theme
    name from its top quotes + top terms. Returns {cluster_id: name}.

    Failures degrade gracefully — caller falls back to the c-TF-IDF label.
    """
    out: dict[int, str] = {}

    system_prompt = (
        "You are an expert product analyst. Given a few review excerpts and "
        "their top distinctive keywords, return a SHORT theme label (2-3 words "
        "max) in title case that captures what these reviews are about. "
        "Reply with ONLY the label, no quotes, no explanation."
    )

    for s in cluster_summaries:
        cid = s["cluster_id"]
        terms = ", ".join(s["terms"][:6]) if s["terms"] else "(none)"
        quotes = "\n".join(f"- {q}" for q in s["quotes"][:3])
        user_prompt = (
            f"Top distinctive keywords: {terms}\n\n"
            f"Excerpts from reviews in this cluster:\n{quotes}\n\n"
            f"Theme label (2-3 words):"
        )
        try:
            resp = http_requests.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                },
                timeout=60,
            )
            resp.raise_for_status()
            label = resp.json().get("message", {}).get("content", "").strip()
            # Strip any surrounding quotes / asterisks; keep only the first line
            label = re.sub(r'^["\'\*]+|["\'\*]+$', "", label.split("\n")[0]).strip()
            if 2 <= len(label) <= 60:
                out[cid] = label
        except Exception as e:
            print(f"[bertopic] LLM rename failed for cluster {cid}: {e}")
            continue
    return out


def analyze(
    reviews: list[dict],
    llm_naming: bool = True,
    n_neighbors: int = 15,
    n_components: int = 5,
    min_cluster_size: int | None = None,
) -> list[dict] | dict:
    ok, err = check_ollama_ready()
    if not ok:
        return {"error": err}

    kept = [r for r in reviews if r.get("review_text")]
    texts = [r.get("review_text") or "" for r in kept]
    post_ids = [r.get("post_id") for r in kept]
    if len(texts) < 10:
        return {"error": "Need at least 10 reviews for the BERTopic pipeline."}

    if min_cluster_size is None:
        min_cluster_size = max(3, len(texts) // 12)

    # n_neighbors must be < n_samples for UMAP
    n_neighbors = min(n_neighbors, max(2, len(texts) - 1))

    print(f"[bertopic] embedding {len(texts)} reviews…")
    embeds = embed_texts(texts, post_ids=post_ids)

    print(f"[bertopic] UMAP reducing 768→{n_components} dims…")
    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    reduced = reducer.fit_transform(embeds)

    print(f"[bertopic] HDBSCAN (min_cluster_size={min_cluster_size})…")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_outliers = int((labels == -1).sum())
    print(f"[bertopic] HDBSCAN: {n_clusters} clusters, {n_outliers} outliers")

    # KMeans fallback if HDBSCAN couldn't find structure
    if n_clusters == 0:
        print("[bertopic] HDBSCAN gave no clusters → KMeans + silhouette fallback")
        n = len(reduced)
        k_max = min(8, max(2, n // 2))
        best_k, best_score, best_labels = 2, -1.0, None
        for k in range(2, k_max + 1):
            try:
                km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(reduced)
                score = silhouette_score(reduced, km.labels_) if k < n else -1.0
                if score > best_score:
                    best_k, best_score, best_labels = k, score, km.labels_
            except Exception:
                continue
        labels = best_labels if best_labels is not None else KMeans(
            n_clusters=2, random_state=42, n_init=10
        ).fit_predict(reduced)
        n_clusters = len(set(labels))
        n_outliers = 0

    terms_per_cluster = name_clusters_ctfidf(texts, labels, top_n=6)

    # Build per-cluster summaries (used both for output and for LLM naming)
    cluster_blobs = []
    for cid in sorted(set(labels)):
        if cid == -1:
            continue
        idxs = [i for i, lbl in enumerate(labels) if lbl == cid]
        ctexts = [texts[i] for i in idxs]
        snippets = [s for s in (shortest_snippet(t) for t in ctexts) if s][:3]
        cluster_blobs.append({
            "cluster_id": int(cid),
            "indices": idxs,
            "texts": ctexts,
            "terms": terms_per_cluster.get(int(cid), []),
            "quotes": snippets,
        })

    # Optional LLM-refined names
    llm_names: dict[int, str] = {}
    if llm_naming:
        print(f"[bertopic] refining {len(cluster_blobs)} cluster names via Mistral…")
        llm_names = _refine_names_via_llm(cluster_blobs)

    results: list[dict] = []
    for blob in cluster_blobs:
        cid = blob["cluster_id"]
        ctfidf_label = cluster_label_from_terms(blob["terms"]) or f"Theme {cid + 1}"
        name = llm_names.get(cid) or ctfidf_label
        results.append({
            "name": name,
            "sentiment": sentiment_for(blob["texts"]),
            "mention_count": len(blob["indices"]),
            "example_quotes": blob["quotes"],
            "keywords": blob["terms"],
        })

    if n_outliers > 0:
        outlier_idxs = [i for i, lbl in enumerate(labels) if lbl == -1]
        otexts = [texts[i] for i in outlier_idxs]
        results.append({
            "name": "Outliers (unique reviews)",
            "sentiment": sentiment_for(otexts),
            "mention_count": n_outliers,
            "example_quotes": [s for s in (shortest_snippet(t) for t in otexts) if s][:3],
            "keywords": [],
        })

    results.sort(key=lambda r: -r["mention_count"])
    # Suppress unused-import warning for a helper kept for future use
    _ = _analyze_ollama
    return results
