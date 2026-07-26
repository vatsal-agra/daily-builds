"""Best-window snippet extraction + HTML highlighting for search results."""

import html

from sift.analyzer import tokenize_raw, analyze

WINDOW_TOKENS = 28
CONTEXT_CHARS = 160


def _matched_positions(doc_text, query_terms):
    """Analyze the raw document text and return the set of token positions
    whose stemmed term is in query_terms, plus the full raw token list."""
    tokens = analyze(doc_text)
    matched = {t.position for t in tokens if t.term in query_terms}
    return tokens, matched


def best_window(tokens, matched_positions):
    """Slide a WINDOW_TOKENS-wide window over the token stream and return the
    (start_idx, end_idx) with the most matches. Falls back to the document's
    start if there are no matches at all."""
    n = len(tokens)
    if n == 0:
        return 0, 0
    if not matched_positions:
        return 0, min(WINDOW_TOKENS, n)

    best_start, best_count = 0, -1
    count = 0
    left = 0
    for right in range(n):
        if tokens[right].position in matched_positions:
            count += 1
        while right - left + 1 > WINDOW_TOKENS:
            if tokens[left].position in matched_positions:
                count -= 1
            left += 1
        if count > best_count:
            best_count = count
            best_start = left
    return best_start, min(best_start + WINDOW_TOKENS, n)


def make_snippet(doc_text, query_terms):
    """Return an HTML fragment: the densest window of the document
    containing query-term matches, with matches wrapped in <mark>, all
    non-match text safely HTML-escaped."""
    tokens, matched = _matched_positions(doc_text, query_terms)
    if not tokens:
        return ""
    start_idx, end_idx = best_window(tokens, matched)
    window = tokens[start_idx:end_idx]

    span_start = window[0].start
    span_end = window[-1].end
    prefix = "…" if start_idx > 0 else ""
    suffix = "…" if end_idx < len(tokens) else ""

    pieces = [prefix]
    cursor = span_start
    for tok in window:
        pieces.append(html.escape(doc_text[cursor:tok.start]))
        escaped = html.escape(doc_text[tok.start:tok.end])
        if tok.position in matched:
            pieces.append(f"<mark>{escaped}</mark>")
        else:
            pieces.append(escaped)
        cursor = tok.end
    pieces.append(html.escape(doc_text[cursor:span_end]))
    pieces.append(suffix)
    return "".join(pieces)
