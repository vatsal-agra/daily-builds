"""A small HTML tokenizer: raw markup text -> a stream of tokens.

Handles tags with attributes (quoted/unquoted/boolean), text runs, HTML
comments, a doctype declaration, and entity decoding (the common named
entities plus numeric decimal/hex references) in both text and attribute
values. Not a full WHATWG tokenizer state machine, but covers the real
surface area real-world simple pages use.
"""

import re

NAMED_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
    "nbsp": " ", "copy": "©", "reg": "®", "trade": "™",
    "hellip": "…", "mdash": "—", "ndash": "–",
    "lsquo": "‘", "rsquo": "’", "ldquo": "“", "rdquo": "”",
    "times": "×", "divide": "÷", "deg": "°",
    "eacute": "é", "egrave": "è", "middot": "·",
    "bull": "•", "larr": "←", "rarr": "→", "uarr": "↑",
    "darr": "↓", "sect": "§", "para": "¶",
}

_ENTITY_RE = re.compile(r"&(#[xX][0-9a-fA-F]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]*);?")


def decode_entities(s):
    def repl(m):
        body = m.group(1)
        if body.startswith("#x") or body.startswith("#X"):
            try:
                return chr(int(body[2:], 16))
            except ValueError:
                return m.group(0)
        if body.startswith("#"):
            try:
                return chr(int(body[1:]))
            except ValueError:
                return m.group(0)
        if body in NAMED_ENTITIES:
            return NAMED_ENTITIES[body]
        return m.group(0)

    return _ENTITY_RE.sub(repl, s)


class Token:
    __slots__ = ("kind", "name", "attrs", "data", "self_closing")

    def __init__(self, kind, name=None, attrs=None, data=None, self_closing=False):
        self.kind = kind  # 'starttag' | 'endtag' | 'text' | 'comment' | 'doctype'
        self.name = name
        self.attrs = attrs
        self.data = data
        self.self_closing = self_closing

    def __repr__(self):
        if self.kind == "starttag":
            return f"<{self.name} {self.attrs}{'/' if self.self_closing else ''}>"
        if self.kind == "endtag":
            return f"</{self.name}>"
        if self.kind == "text":
            return f"TEXT({self.data!r})"
        if self.kind == "comment":
            return f"<!--{self.data}-->"
        return f"DOCTYPE({self.data})"


# Elements whose content is opaque text (not markup) until the matching end tag.
RAW_TEXT_ELEMENTS = {"script", "style", "textarea", "title"}

_TAG_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9:_-]*")
_ATTR_NAME_RE = re.compile(r"[^\s=/>][^\s=/>]*")


def tokenize(html):
    tokens = []
    i = 0
    n = len(html)

    while i < n:
        if html[i] == "<":
            # Comment
            if html.startswith("<!--", i):
                end = html.find("-->", i + 4)
                if end == -1:
                    tokens.append(Token("comment", data=html[i + 4:]))
                    break
                tokens.append(Token("comment", data=html[i + 4:end]))
                i = end + 3
                continue
            # Doctype / other bang declarations
            if html.startswith("<!", i):
                end = html.find(">", i)
                if end == -1:
                    break
                tokens.append(Token("doctype", data=html[i + 2:end]))
                i = end + 1
                continue
            # End tag
            if html.startswith("</", i):
                end = html.find(">", i)
                if end == -1:
                    break
                name = html[i + 2:end].strip()
                m = _TAG_NAME_RE.match(name)
                if m:
                    tokens.append(Token("endtag", name=m.group(0).lower()))
                i = end + 1
                continue
            # Start tag
            m = _TAG_NAME_RE.match(html, i + 1)
            if m:
                name = m.group(0).lower()
                j = m.end()
                attrs, j, self_closing = _parse_attrs(html, j)
                tokens.append(Token("starttag", name=name, attrs=attrs,
                                     self_closing=self_closing))
                i = j
                if name in RAW_TEXT_ELEMENTS and not self_closing:
                    close = f"</{name}"
                    end = _find_ci(html, close, i)
                    raw = html[i:end] if end != -1 else html[i:]
                    if raw:
                        tokens.append(Token("text", data=raw))
                    i = end if end != -1 else n
                continue
            # Not a real tag ('<' followed by something else) -> literal text
            tokens.append(Token("text", data="<"))
            i += 1
            continue
        # Text run
        end = html.find("<", i)
        if end == -1:
            end = n
        raw = html[i:end]
        if raw:
            tokens.append(Token("text", data=decode_entities(raw)))
        i = end

    return tokens


def _find_ci(haystack, needle, start):
    """Case-insensitive find."""
    hl = haystack.lower()
    return hl.find(needle.lower(), start)


def _parse_attrs(html, i):
    n = len(html)
    attrs = {}
    self_closing = False
    while i < n:
        while i < n and html[i].isspace():
            i += 1
        if i >= n:
            break
        if html[i] == ">":
            i += 1
            break
        if html[i] == "/" and i + 1 < n and html[i + 1] == ">":
            self_closing = True
            i += 2
            break
        if html[i] == "/":
            i += 1
            continue
        m = _ATTR_NAME_RE.match(html, i)
        if not m:
            i += 1
            continue
        name = m.group(0).lower()
        i = m.end()
        while i < n and html[i].isspace():
            i += 1
        value = ""
        if i < n and html[i] == "=":
            i += 1
            while i < n and html[i].isspace():
                i += 1
            if i < n and html[i] in ("'", '"'):
                quote = html[i]
                i += 1
                start = i
                end = html.find(quote, i)
                if end == -1:
                    end = n
                value = html[start:end]
                i = end + 1
            else:
                start = i
                while i < n and not html[i].isspace() and html[i] != ">":
                    i += 1
                value = html[start:i]
        attrs[name] = decode_entities(value)
    return attrs, i, self_closing
