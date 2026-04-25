"""
Shared utilities for embedding-based theme methods.

We use Ollama's nomic-embed-text as the embedding backend — it runs locally
on the M4 Max, no API key, ~274 MB model, 768-dim output. No torch dependency.

This module is consumed by both:
  - themes_semantic.py (Solid upgrade — embeddings + HDBSCAN + c-TF-IDF)
  - themes_bertopic.py (Power user — adds UMAP + optional LLM naming)
"""

from __future__ import annotations

import re
import time
from collections import Counter

import numpy as np
import requests as http_requests
from sklearn.feature_extraction.text import CountVectorizer

EMBED_MODEL = "nomic-embed-text"
EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_DIM = 768
EMBED_TIMEOUT = 30


def check_ollama_ready() -> tuple[bool, str | None]:
    """Returns (ok, error_message). Used to fail fast when Ollama or the
    embedding model isn't available, so we can surface a clear error to the
    UI instead of a generic 500."""
    try:
        r = http_requests.get("http://localhost:11434/api/tags", timeout=3)
        r.raise_for_status()
    except Exception as e:
        return False, f"Ollama is not running. Start it with: ollama serve  ({e})"
    pulled = [m["name"] for m in r.json().get("models", [])]
    if not any(EMBED_MODEL in name for name in pulled):
        return False, f"Embedding model '{EMBED_MODEL}' not pulled. Run: ollama pull {EMBED_MODEL}"
    return True, None


def _embed_one(text: str) -> np.ndarray:
    """Embed a single text via Ollama. Returns a (EMBED_DIM,) float32 array.
    Empty / whitespace-only text returns zeros."""
    if not text or not text.strip():
        return np.zeros(EMBED_DIM, dtype=np.float32)
    snippet = text[:2000]
    try:
        r = http_requests.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": snippet},
            timeout=EMBED_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        emb = data.get("embedding")
        if not emb or len(emb) != EMBED_DIM:
            raise ValueError(f"unexpected embedding shape: {len(emb) if emb else 'none'}")
        return np.asarray(emb, dtype=np.float32)
    except Exception as e:
        print(f"[embed] failed: {e}")
        return np.zeros(EMBED_DIM, dtype=np.float32)


def embed_texts(
    texts: list[str],
    post_ids: list[str] | None = None,
    log_progress: bool = True,
) -> np.ndarray:
    """Embed a list of strings via Ollama. Returns (N, EMBED_DIM) float32 array.

    If `post_ids` is provided, the per-review embedding cache (DB table
    `review_embeddings`) is consulted first; only cache misses hit Ollama, and
    fresh embeddings are written back. Lengths of `texts` and `post_ids` must
    match when both are provided.

    Empty strings are kept in place as zero vectors so the output stays index-
    aligned with the input (callers depend on this for clustering)."""
    n = len(texts)
    out = np.zeros((n, EMBED_DIM), dtype=np.float32)
    if n == 0:
        return out

    # Cache hit phase
    cached_blobs: dict[str, bytes] = {}
    if post_ids is not None:
        if len(post_ids) != n:
            raise ValueError(
                f"texts ({n}) / post_ids ({len(post_ids)}) length mismatch"
            )
        # Local import to avoid module-load cycles during db init.
        from database import get_cached_embeddings  # noqa: WPS433
        cached_blobs = get_cached_embeddings(post_ids, EMBED_MODEL)

    miss_indices: list[int] = []
    for i in range(n):
        pid = post_ids[i] if post_ids is not None else None
        if pid is not None and pid in cached_blobs:
            out[i] = np.frombuffer(cached_blobs[pid], dtype=np.float32)
        else:
            miss_indices.append(i)

    if log_progress and post_ids is not None:
        print(
            f"[embed] cache: {n - len(miss_indices)}/{n} hits, "
            f"{len(miss_indices)} misses"
        )

    # Miss phase: embed the cache misses, then write them back.
    started = time.time()
    fresh_pids: list[str] = []
    fresh_blobs: list[bytes] = []
    for j, i in enumerate(miss_indices):
        emb = _embed_one(texts[i])
        out[i] = emb
        if post_ids is not None and texts[i] and texts[i].strip():
            fresh_pids.append(post_ids[i])
            fresh_blobs.append(emb.tobytes())
        if log_progress and (j + 1) % 25 == 0:
            print(
                f"[embed] {j+1}/{len(miss_indices)} fresh embeddings in "
                f"{time.time()-started:.1f}s"
            )

    if fresh_pids:
        from database import cache_embeddings  # noqa: WPS433
        cache_embeddings(fresh_pids, EMBED_MODEL, fresh_blobs, EMBED_DIM)

    return out


# ---------------------------------------------------------------------------
# c-TF-IDF naming (the BERTopic recipe)
# ---------------------------------------------------------------------------

# Same domain-specific stop list as themes_tfidf — keeps cluster labels free of
# product / ad copy noise.
EXTRA_STOP_WORDS = {
    "bike", "yamaha", "honda", "hero", "bajaj", "tvs", "suzuki", "ktm",
    "royal", "enfield", "kawasaki", "aprilia", "really", "also", "like",
    "just", "very", "quite", "much", "even", "get", "got", "make",
    "one", "two", "bit", "ago", "weeks", "months", "purchase",
    "bought", "india", "indian", "rupee", "rs", "bikewale", "user",
    "review", "today", "new",
}


def _clean(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def name_clusters_ctfidf(
    texts: list[str],
    cluster_labels: np.ndarray,
    top_n: int = 6,
) -> dict[int, list[str]]:
    """Class-based TF-IDF: for each cluster, return the words that are
    over-represented in that cluster relative to the others. This is what
    BERTopic uses; produces much more discriminating labels than raw centroid
    terms.

    Implementation note: we treat each cluster as a single "document" of
    concatenated reviews, then run TF-IDF across those mega-docs. -1 (HDBSCAN
    noise) is excluded from naming.
    """
    cleaned = [_clean(t) for t in texts]
    docs_per_cluster: dict[int, list[str]] = {}
    for text, cid in zip(cleaned, cluster_labels):
        if cid == -1:
            continue
        docs_per_cluster.setdefault(int(cid), []).append(text)

    if not docs_per_cluster:
        return {}

    cluster_ids = sorted(docs_per_cluster.keys())
    mega_docs = [" ".join(docs_per_cluster[cid]) for cid in cluster_ids]

    # Count vectorizer with sklearn's English stop words plus our domain words
    stop = list(EXTRA_STOP_WORDS) + [
        # very common adjectives that survive sklearn's default stop list
        "good", "great", "nice", "best", "amazing", "awesome", "perfect",
    ]
    # min_df=1 because c-TF-IDF's whole point is surfacing terms that appear
    # in ONE cluster but not others — over-filtering with min_df>=2 would kill
    # exactly the words we want.
    vec = CountVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        min_df=1,
        token_pattern=r"\b[a-z]{3,}\b",  # ≥3 chars, alpha only
    )
    try:
        X = vec.fit_transform(mega_docs)  # (n_clusters, vocab)
    except ValueError:
        # vocabulary became empty after stop filtering
        return {cid: [] for cid in cluster_ids}

    vocab = np.array(vec.get_feature_names_out())
    # Filter out our extra stop words by zeroing those columns
    extra_mask = np.array([w in stop for w in vocab])
    X = X.toarray().astype(np.float32)
    X[:, extra_mask] = 0

    # c-TF-IDF: tf within cluster, idf across clusters
    tf = X / (X.sum(axis=1, keepdims=True) + 1e-9)
    df = (X > 0).sum(axis=0)  # number of clusters each term appears in
    idf = np.log((1 + len(cluster_ids)) / (1 + df))
    ctfidf = tf * idf

    out: dict[int, list[str]] = {}
    for i, cid in enumerate(cluster_ids):
        scores = ctfidf[i]
        top_idx = scores.argsort()[::-1][:top_n]
        out[cid] = [vocab[j] for j in top_idx if scores[j] > 0]
    return out


# ---------------------------------------------------------------------------
# Helper: compose a human-readable theme name from c-TF-IDF top terms
# ---------------------------------------------------------------------------

def cluster_label_from_terms(terms: list[str], max_words: int = 3) -> str:
    """Turn c-TF-IDF top terms into a short title. Capitalises and joins
    with ' / '. Prefers bigrams over unigrams when present."""
    if not terms:
        return "Theme"
    # Prefer bigrams (more meaningful) — promote them to the front
    bigrams = [t for t in terms if " " in t]
    unigrams = [t for t in terms if " " not in t]
    pool = (bigrams + unigrams)[:max_words]
    return " / ".join(t.title() for t in pool)


# ---------------------------------------------------------------------------
# Sentiment (reused — same recipe as the other methods)
# ---------------------------------------------------------------------------

POS = ["good", "great", "excellent", "smooth", "love", "amazing",
       "best", "fantastic", "solid", "happy", "perfect", "brilliant"]
NEG = ["bad", "poor", "issue", "problem", "disappoint", "worst",
       "terrible", "hate", "fail", "lacking", "stiff", "overpriced"]


def sentiment_for(texts: list[str]) -> str:
    blob = " ".join(texts).lower()
    p = sum(blob.count(w) for w in POS)
    n = sum(blob.count(w) for w in NEG)
    if p > n * 2: return "positive"
    if n > p * 2: return "negative"
    return "mixed"


def shortest_snippet(text: str, min_len: int = 30) -> str | None:
    sents = [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > min_len]
    if not sents:
        return None
    return min(sents, key=len)
