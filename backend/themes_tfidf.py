"""
Option 2 — TF-IDF + K-Means clustering.
Uses scikit-learn. Discovers themes from the data rather than from
a predefined keyword list.
"""

import re
from collections import Counter

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# Words to remove that are specific to this product page rather than meaningful themes
EXTRA_STOP_WORDS = [
    "bike", "yamaha", "xsr", "155", "xsr155", "really", "also", "like",
    "just", "very", "quite", "much", "even", "get", "got", "make",
    "one", "two", "bit", "ago", "weeks", "months", "ago", "purchase",
    "bought", "india", "indian", "rupee", "rs", "bikewale", "user",
    "review", "retro", "rebel",
]


def _clean(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _top_terms(vectorizer: "TfidfVectorizer", km: "KMeans", cluster_id: int, n: int = 6) -> list[str]:
    feature_names = vectorizer.get_feature_names_out()
    centroid = km.cluster_centers_[cluster_id]
    top_indices = centroid.argsort()[-n:][::-1]
    return [feature_names[i] for i in top_indices]


def _theme_name(terms: list[str]) -> str:
    """Turn top TF-IDF terms into a human-readable theme label."""
    return " / ".join(t.capitalize() for t in terms[:3])


def _sentiment(texts: list[str]) -> str:
    pos = ["good", "great", "excellent", "smooth", "love", "amazing",
           "best", "fantastic", "solid", "happy", "perfect"]
    neg = ["bad", "poor", "issue", "problem", "disappoint", "worst",
           "terrible", "hate", "fail", "lacking", "stiff", "overpriced"]
    all_text = " ".join(texts).lower()
    p = sum(all_text.count(w) for w in pos)
    n = sum(all_text.count(w) for w in neg)
    if p > n * 2:
        return "positive"
    if n > p * 2:
        return "negative"
    return "mixed"


def analyze(reviews: list[dict], n_clusters: int = 6) -> list[dict] | dict:
    if not SKLEARN_AVAILABLE:
        return {"error": "scikit-learn not installed. Run: pip install scikit-learn"}

    texts = [r["review_text"] for r in reviews if r.get("review_text")]
    if len(texts) < n_clusters:
        return {"error": f"Not enough reviews ({len(texts)}) for {n_clusters} clusters."}

    cleaned = [_clean(t) for t in texts]

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=300,
        ngram_range=(1, 2),
        min_df=3,
    )
    # Append extra stop words by refitting after removal
    X = vectorizer.fit_transform(cleaned)

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    results = []
    for cluster_id in range(n_clusters):
        indices = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
        cluster_texts = [texts[i] for i in indices]
        top_terms = _top_terms(vectorizer, km, cluster_id, n=6)

        # Filter out stop words from terms
        top_terms = [t for t in top_terms if t not in EXTRA_STOP_WORDS]

        # Representative sentences — pick shortest meaningful snippet per review
        snippets = []
        for t in cluster_texts[:5]:
            sents = [s.strip() for s in re.split(r"[.!?\n]", t) if len(s.strip()) > 30]
            if sents:
                snippets.append(min(sents, key=len))

        results.append({
            "name": _theme_name(top_terms),
            "sentiment": _sentiment(cluster_texts),
            "mention_count": len(indices),
            "example_quotes": snippets[:3],
            "keywords": top_terms,
        })

    # Sort by size descending
    results.sort(key=lambda r: -r["mention_count"])
    return results
