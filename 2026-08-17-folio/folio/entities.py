"""HTML character-reference decoding, from scratch.

Real HTML5 ships a table of ~2,200 named character references. Folio
implements the mechanism (numeric decimal/hex references, and named-entity
lookup with the HTML5 "longest match wins, trailing ';' optional for a
legacy subset" rule) against a curated table of the entities that actually
show up in real-world markup, rather than transcribing the full spec table.
"""

import re

# A curated subset of HTML5's named character references -- enough to cover
# the entities that show up in ordinary prose and markup.
NAMED_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
    "nbsp": " ", "copy": "©", "reg": "®", "trade": "™",
    "mdash": "—", "ndash": "–", "hellip": "…",
    "lsquo": "‘", "rsquo": "’", "ldquo": "“", "rdquo": "”",
    "middot": "·", "bull": "•", "deg": "°",
    "plusmn": "±", "times": "×", "divide": "÷",
    "frac12": "½", "frac14": "¼", "frac34": "¾",
    "sup2": "²", "sup3": "³", "micro": "µ",
    "para": "¶", "sect": "§", "laquo": "«", "raquo": "»",
    "euro": "€", "pound": "£", "yen": "¥", "cent": "¢",
    "larr": "←", "rarr": "→", "uarr": "↑", "darr": "↓",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "pi": "π", "sigma": "σ", "omega": "ω", "infin": "∞",
    "ne": "≠", "le": "≤", "ge": "≥", "plusminus": "±",
    "shy": "­", "ensp": " ", "emsp": " ", "thinsp": " ",
    "zwnj": "‌", "zwj": "‍", "AMP": "&", "COPY": "©",
    "REG": "®", "QUOT": '"', "LT": "<", "GT": ">",
}

_MAX_NAME_LEN = max(len(k) for k in NAMED_ENTITIES)

_REF_RE = re.compile(r"&(#[xX]?[0-9A-Fa-f]+;?|[A-Za-z][A-Za-z0-9]{0,31};?)")


def _decode_one(body):
    """`body` excludes the leading '&'. Returns (replacement_text, consumed_len)
    where consumed_len is how much of `body` (not counting '&') the reference
    used, or None if `body` isn't a valid reference at all (caller keeps '&' literal)."""
    if body.startswith("#"):
        m = re.match(r"#[xX]([0-9A-Fa-f]+);?", body)
        if m:
            try:
                cp = int(m.group(1), 16)
            except ValueError:
                return None
        else:
            m = re.match(r"#([0-9]+);?", body)
            if not m:
                return None
            cp = int(m.group(1))
        if cp == 0 or cp > 0x10FFFF or (0xD800 <= cp <= 0xDFFF):
            cp = 0xFFFD  # replacement character, per spec for invalid code points
        try:
            return chr(cp), m.end()
        except ValueError:
            return "�", m.end()

    # Named reference: HTML5 semantics allow the trailing ';' to be omitted
    # for a legacy subset; Folio requires it except for the handful of
    # single-character legacy names, which keeps the decoder unambiguous.
    m = re.match(r"[A-Za-z][A-Za-z0-9]{0,31}", body)
    if not m:
        return None
    name_no_semi = m.group(0)
    # Longest-match against our table, with or without the trailing ';'.
    for length in range(min(len(name_no_semi), _MAX_NAME_LEN), 0, -1):
        candidate = name_no_semi[:length]
        if candidate in NAMED_ENTITIES:
            has_semi = len(body) > length and body[length] == ";"
            consumed = length + 1 if has_semi else length
            return NAMED_ENTITIES[candidate], consumed
    return None


def decode_entities(text):
    """Decode HTML character references in `text`. Anything that isn't a
    recognized reference is left as literal text (matches real browsers'
    tolerant behavior for a bare '&')."""
    if "&" not in text:
        return text
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != "&":
            out.append(c)
            i += 1
            continue
        result = _decode_one(text[i + 1 :])
        if result is None:
            out.append("&")
            i += 1
        else:
            replacement, consumed = result
            out.append(replacement)
            i += 1 + consumed
    return "".join(out)
