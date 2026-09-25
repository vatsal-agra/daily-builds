"""A from-scratch HTML tokenizer and tree builder.

This is not a full HTML5-spec parser (the real spec's tree-construction
insertion-mode state machine is enormous). It implements, from scratch, the
part of the algorithm that actually matters for real-world malformed HTML:

  * a character-by-character tokenizer for tags/attributes/text/comments
  * raw-text elements (<script>/<style>) whose content is never tokenized
    as markup
  * void elements that never open a new scope
  * a stack-based tree builder with the two most common "optional end tag"
    recovery rules HTML5 defines: an open <p> is implicitly closed by the
    next block-level start tag, and an open <li> is implicitly closed by
    the next <li>
  * stray/mismatched end tags are recovered from by searching the open-
    element stack, exactly like a real browser, instead of raising

Scope note: it does not implement the full insertion-mode table (foreign
content, <table>/<select> re-parenting quirks, etc). Undocumented tags are
still parsed generically (pushed/popped like any other element), so
unsupported tags do not crash the parser -- they just fall back to generic
block behaviour in layout.
"""

from .dom import Comment, Document, Element, Text

VOID_ELEMENTS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "source", "track", "wbr",
    }
)

RAW_TEXT_ELEMENTS = frozenset({"script", "style"})

# Start tags that implicitly close an open <p>, per the HTML5 spec's list
# of "p element in button scope" closers (the subset relevant to the tags
# Casement understands).
P_CLOSERS = frozenset(
    {
        "address", "article", "aside", "blockquote", "div", "dl",
        "fieldset", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "main", "nav", "ol", "p", "pre", "section",
        "table", "ul",
    }
)


class Token:
    __slots__ = ("kind", "name", "attrs", "data", "self_closing")

    def __init__(self, kind, name=None, attrs=None, data=None, self_closing=False):
        self.kind = kind  # 'start', 'end', 'text', 'comment', 'doctype'
        self.name = name
        self.attrs = attrs
        self.data = data
        self.self_closing = self_closing


class HTMLSyntaxError(Exception):
    pass


def tokenize(source):
    """Yield Token objects from raw HTML source."""
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "<":
            if source.startswith("<!--", i):
                end = source.find("-->", i + 4)
                if end == -1:
                    yield Token("comment", data=source[i + 4:])
                    return
                yield Token("comment", data=source[i + 4:end])
                i = end + 3
                continue
            if source.startswith("<!", i):
                end = source.find(">", i)
                end = n if end == -1 else end
                yield Token("doctype", data=source[i + 2:end])
                i = end + 1
                continue
            if i + 1 < n and source[i + 1] == "/":
                end = source.find(">", i)
                end = n if end == -1 else end
                name = source[i + 2:end].strip().lower()
                yield Token("end", name=name)
                i = end + 1
                continue
            if i + 1 < n and (source[i + 1].isalpha()):
                tag_end = _find_tag_end(source, i)
                inner = source[i + 1:tag_end]
                self_closing = inner.rstrip().endswith("/")
                if self_closing:
                    inner = inner.rstrip()[:-1]
                name, attrs = _parse_tag_inner(inner)
                yield Token("start", name=name.lower(), attrs=attrs, self_closing=self_closing)
                i = tag_end + 1
                if name.lower() in RAW_TEXT_ELEMENTS and not self_closing:
                    close = f"</{name.lower()}"
                    idx = source.lower().find(close, i)
                    if idx == -1:
                        yield Token("text", data=source[i:])
                        return
                    yield Token("text", data=source[i:idx])
                    end = source.find(">", idx)
                    end = n if end == -1 else end
                    yield Token("end", name=name.lower())
                    i = end + 1
                continue
            # stray '<' not starting a recognizable construct: literal text
            yield Token("text", data="<")
            i += 1
            continue
        else:
            end = source.find("<", i)
            end = n if end == -1 else end
            yield Token("text", data=source[i:end])
            i = end
            continue


def _find_tag_end(source, start):
    """Find the '>' that closes the tag starting at `start`, respecting quotes."""
    i = start + 1
    n = len(source)
    quote = None
    while i < n:
        c = source[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ">":
            return i
        i += 1
    return n


def _parse_tag_inner(inner):
    """Parse `tagname attr="val" attr2 attr3='v'` into (name, attrs dict)."""
    i = 0
    n = len(inner)
    while i < n and not inner[i].isspace():
        i += 1
    name = inner[:i]
    attrs = {}
    while i < n:
        while i < n and inner[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        while i < n and inner[i] not in "= \t\n\r" and inner[i] != "/":
            i += 1
        attr_name = inner[start:i]
        if not attr_name:
            i += 1
            continue
        while i < n and inner[i].isspace():
            i += 1
        if i < n and inner[i] == "=":
            i += 1
            while i < n and inner[i].isspace():
                i += 1
            if i < n and inner[i] in "\"'":
                quote = inner[i]
                i += 1
                start = i
                while i < n and inner[i] != quote:
                    i += 1
                value = inner[start:i]
                i += 1
            else:
                start = i
                while i < n and not inner[i].isspace():
                    i += 1
                value = inner[start:i]
            attrs[attr_name.lower()] = _unescape_entities(value)
        else:
            attrs[attr_name.lower()] = ""
    return name, attrs


_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
    "nbsp": " ", "copy": "©", "mdash": "—", "ndash": "–",
    "hellip": "…", "rsquo": "’", "lsquo": "‘",
    "rdquo": "”", "ldquo": "“",
}


def _unescape_entities(text):
    if "&" not in text:
        return text
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "&":
            end = text.find(";", i, i + 12)
            if end != -1:
                ent = text[i + 1:end]
                if ent.startswith("#x") or ent.startswith("#X"):
                    try:
                        out.append(chr(int(ent[2:], 16)))
                        i = end + 1
                        continue
                    except ValueError:
                        pass
                elif ent.startswith("#"):
                    try:
                        out.append(chr(int(ent[1:])))
                        i = end + 1
                        continue
                    except ValueError:
                        pass
                elif ent in _ENTITIES:
                    out.append(_ENTITIES[ent])
                    i = end + 1
                    continue
        out.append(c)
        i += 1
    return "".join(out)


def parse(source):
    """Parse an HTML document string into a DOM tree; returns the Document root."""
    doc = Document()
    stack = [doc]

    def top():
        return stack[-1]

    for tok in tokenize(source):
        if tok.kind == "text":
            if tok.data:
                text = _unescape_entities(tok.data)
                top().append(Text(text))
        elif tok.kind == "comment":
            top().append(Comment(tok.data))
        elif tok.kind == "doctype":
            continue
        elif tok.kind == "start":
            name = tok.name
            if isinstance(top(), Element):
                if top().tag == "p" and name in P_CLOSERS:
                    stack.pop()
                elif top().tag == "li" and name == "li":
                    stack.pop()
            el = Element(name, tok.attrs)
            top().append(el)
            if name not in VOID_ELEMENTS and not tok.self_closing:
                stack.append(el)
        elif tok.kind == "end":
            name = tok.name
            for idx in range(len(stack) - 1, 0, -1):
                node = stack[idx]
                if isinstance(node, Element) and node.tag == name:
                    del stack[idx:]
                    break
            # stray end tag with no match: ignore
    return doc
