"""Builds a highlighted excerpt of a document around its first query match."""
from .analyzer import TOKEN_RE, porter_stem


def make_snippet(text, matched_terms, window=220):
    matched_terms = set(matched_terms)
    if not text:
        return ""
    matches = [
        m for m in TOKEN_RE.finditer(text)
        if porter_stem(m.group(0).lower()) in matched_terms
    ]
    if not matches:
        collapsed = " ".join(text.split())
        return collapsed[:window] + ("…" if len(collapsed) > window else "")

    center = matches[0].start()
    start = max(0, center - window // 2)
    end = min(len(text), center + window // 2)
    while start > 0 and not text[start].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1

    pieces = []
    cursor = start
    for m in matches:
        if m.start() < start or m.end() > end:
            continue
        pieces.append(text[cursor:m.start()])
        pieces.append(f"[[{text[m.start():m.end()]}]]")
        cursor = m.end()
    pieces.append(text[cursor:end])

    body = " ".join("".join(pieces).split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{body}{suffix}"


def to_html(snippet):
    return snippet.replace("[[", "<mark>").replace("]]", "</mark>")


def to_ansi(snippet):
    return snippet.replace("[[", "\033[1m\033[93m").replace("]]", "\033[0m")


def to_plain(snippet):
    return snippet.replace("[[", "").replace("]]", "")
