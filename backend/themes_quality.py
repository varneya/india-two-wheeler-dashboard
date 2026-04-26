"""
Theme-quality metrics — computed *post-hoc* from the themes a method
returned + the corpus it ran against. Method-agnostic; works for all five
clustering engines without modifying any of them.

Two metrics are surfaced today:

- npmi  — average pairwise Normalised Pointwise Mutual Information of each
          theme's top keywords. Captures whether words inside a theme actually
          co-occur in reviews. Ranges roughly -1 (anti-coherent) to +1
          (perfectly coherent). 0.1–0.3 is decent, >0.4 is sharp.

- theme_diversity — fraction of *unique* tokens across all themes' keyword
          lists. Low values signal redundant themes ("two themes are basically
          the same"); high values mean the themes carve up distinct territory.

Both are scalar floats so the UI can render them as pills with no extra logic.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

_TOKEN_RE = re.compile(r"[a-z][a-z']+")


def _tokenise(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(_TOKEN_RE.findall(text.lower()))


def _doc_word_sets(texts: Iterable[str]) -> list[set[str]]:
    return [_tokenise(t) for t in texts]


def _flatten_keywords(theme_keywords: list[list[str]]) -> list[set[str]]:
    """For each theme, return the set of word-tokens that appear in its
    keyword list. Multi-word keywords contribute their constituent tokens —
    'fuel economy' becomes {'fuel', 'economy'}."""
    out: list[set[str]] = []
    for kws in theme_keywords:
        toks: set[str] = set()
        for kw in kws or []:
            toks.update(_tokenise(str(kw)))
        out.append(toks)
    return out


def compute_npmi(
    theme_keywords: list[list[str]],
    review_texts: list[str],
    epsilon: float = 1e-9,
) -> float | None:
    """Average pairwise NPMI across all themes. Returns None if the corpus
    or themes are too small for the metric to be meaningful."""
    if not theme_keywords or not review_texts:
        return None
    docs = _doc_word_sets(review_texts)
    n_docs = len(docs)
    if n_docs < 5:
        return None

    # Theme-token sets (deduped per theme)
    theme_tokens = _flatten_keywords(theme_keywords)

    # Single-token doc frequencies
    df: dict[str, int] = {}
    for ts in theme_tokens:
        for t in ts:
            if t not in df:
                df[t] = sum(1 for d in docs if t in d)

    per_theme_npmi: list[float] = []
    for ts in theme_tokens:
        terms = [t for t in ts if df.get(t, 0) > 0]
        if len(terms) < 2:
            continue
        pair_scores: list[float] = []
        for i in range(len(terms)):
            for j in range(i + 1, len(terms)):
                a, b = terms[i], terms[j]
                # Joint frequency
                joint = sum(1 for d in docs if a in d and b in d)
                if joint == 0:
                    pair_scores.append(-1.0)  # never co-occur — strongly anti-coherent
                    continue
                p_a = df[a] / n_docs
                p_b = df[b] / n_docs
                p_ab = joint / n_docs
                pmi = math.log((p_ab + epsilon) / (p_a * p_b + epsilon))
                # Normaliser; -log(p_ab) is always positive when p_ab>0
                norm = -math.log(p_ab + epsilon)
                if norm == 0:
                    continue
                pair_scores.append(pmi / norm)
        if pair_scores:
            per_theme_npmi.append(sum(pair_scores) / len(pair_scores))

    if not per_theme_npmi:
        return None
    return sum(per_theme_npmi) / len(per_theme_npmi)


def compute_theme_diversity(theme_keywords: list[list[str]]) -> float | None:
    """Returns the fraction of unique tokens vs. total tokens across all themes.
    1.0 = no overlap between themes; 0.5 = on average each token appears in
    two themes; etc. None if themes are empty."""
    if not theme_keywords:
        return None
    all_tokens: list[str] = []
    for kws in theme_keywords:
        for kw in kws or []:
            all_tokens.extend(_TOKEN_RE.findall(str(kw).lower()))
    if not all_tokens:
        return None
    return len(set(all_tokens)) / len(all_tokens)


def compute_metrics(
    theme_keywords: list[list[str]],
    review_texts: list[str],
) -> dict:
    """Bundle both metrics into a single dict for the API. Each value is
    either a float or None when the metric isn't computable."""
    return {
        "npmi": compute_npmi(theme_keywords, review_texts),
        "theme_diversity": compute_theme_diversity(theme_keywords),
    }
