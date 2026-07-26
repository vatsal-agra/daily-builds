"""Relevance snippets: for a matched document, find the densest window of
query-term hits and render it with the hits marked, the way a real search
engine's result preview works (not just the first N characters)."""

from .tokenizer import raw_tokens, normalize_term

WINDOW_SIZE = 24     # words either side of context is trimmed to this
MAX_SNIPPET_CHARS = 320


def _best_window(word_terms, query_terms):
    """Given the stemmed term for every raw word in the document (in
    order) and the set of stemmed query terms, return the (start, end)
    word-index range containing the most query-term hits, preferring the
    earliest and narrowest such window on ties."""
    hit_positions = [i for i, t in enumerate(word_terms) if t in query_terms]
    if not hit_positions:
        return None

    best = None
    best_count = -1
    n = len(word_terms)
    for start_hit in hit_positions:
        start = max(0, start_hit - WINDOW_SIZE // 4)
        end = min(n, start + WINDOW_SIZE)
        count = sum(1 for p in hit_positions if start <= p < end)
        if count > best_count:
            best_count = count
            best = (start, end)
    return best


def make_snippet(text, query_terms, window=WINDOW_SIZE, max_chars=MAX_SNIPPET_CHARS):
    """Return a plain-text snippet of `text` centered on the densest
    cluster of `query_terms` (already stemmed), with each matched word
    wrapped in `**...**`. Falls back to the start of the document if no
    query term appears in it at all (e.g. a NOT-only match)."""
    words = raw_tokens(text)
    if not words:
        return ""
    word_terms = [normalize_term(w) for w, _s, _e in words]

    window_range = _best_window(word_terms, set(query_terms)) if query_terms else None
    if window_range is None:
        start, end = 0, min(len(words), window)
    else:
        start, end = window_range

    pieces = []
    for i in range(start, end):
        raw = words[i][0]
        if word_terms[i] in query_terms:
            pieces.append(f"**{raw}**")
        else:
            pieces.append(raw)

    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(words) else ""
    snippet = prefix + " ".join(pieces) + suffix
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars].rsplit(" ", 1)[0] + " …"
    return snippet
