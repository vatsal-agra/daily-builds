"""A from-scratch HTML tokenizer + tree-construction parser.

This is a deliberate *subset* of the WHATWG HTML5 parsing algorithm: it
handles the tokenizer states that matter for real documents (tags,
attributes, comments, raw-text elements like <script>/<style>), and a
simplified stack-based tree builder with the auto-closing rules that
account for the overwhelming majority of "malformed" real-world markup
(unclosed <p>, <li>, <td>/<tr>, ...). It does not implement the full
"adoption agency" algorithm for wildly misnested tags — mismatched end
tags are recovered by unwinding the open-element stack to the nearest
matching start tag, or dropped if no match exists. It never raises on
malformed input.
"""

from .dom import Document, Element, Text, Comment, VOID_ELEMENTS, RAWTEXT_ELEMENTS

# tag -> set of tags, at the top of the open-elements stack, that this tag
# implicitly closes when it appears as a new start tag.
AUTO_CLOSE = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "option": {"option"},
    "tr": {"tr", "td", "th"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "thead": {"thead", "tbody", "tfoot"},
    "tbody": {"thead", "tbody", "tfoot"},
    "tfoot": {"thead", "tbody", "tfoot"},
}

# Tags that, when opened, implicitly close an open <p> ancestor (real HTML5
# scopes this to "has a <p> in button scope"; we simplify to "top of stack
# is <p>", which covers the actual malformed markup this matters for).
_P_CLOSERS = {
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol", "p",
    "pre", "section", "table", "ul",
}
for _tag in _P_CLOSERS:
    AUTO_CLOSE.setdefault(_tag, set()).add("p")


class Token:
    __slots__ = ("kind", "name", "attrs", "data", "self_closing")

    def __init__(self, kind, name=None, attrs=None, data=None, self_closing=False):
        self.kind = kind  # 'start', 'end', 'text', 'comment', 'doctype'
        self.name = name
        self.attrs = attrs
        self.data = data
        self.self_closing = self_closing


def tokenize(html):
    """Yield Token objects. Handles tags/attributes/comments/doctype and
    raw-text elements (script/style/textarea/title)."""
    i = 0
    n = len(html)
    while i < n:
        ch = html[i]
        if ch == "<":
            if html.startswith("<!--", i):
                end = html.find("-->", i + 4)
                if end == -1:
                    yield Token("comment", data=html[i + 4:])
                    return
                yield Token("comment", data=html[i + 4:end])
                i = end + 3
                continue
            if html.startswith("<!", i):
                end = html.find(">", i)
                if end == -1:
                    return
                yield Token("doctype", data=html[i + 2:end])
                i = end + 1
                continue
            if html.startswith("</", i):
                end = html.find(">", i)
                if end == -1:
                    return
                name = html[i + 2:end].strip().split()[0:1]
                i = end + 1
                if name:
                    yield Token("end", name=name[0].lower())
                continue
            if i + 1 < n and (html[i + 1].isalpha()):
                name, attrs, self_closing, i = _parse_tag(html, i)
                yield Token("start", name=name, attrs=attrs, self_closing=self_closing)
                if name in RAWTEXT_ELEMENTS and not self_closing:
                    close = f"</{name}"
                    idx = html.lower().find(close, i)
                    if idx == -1:
                        text, i = html[i:], n
                    else:
                        text, i = html[i:idx], idx
                        gt = html.find(">", i)
                        i = gt + 1 if gt != -1 else i
                    if text:
                        yield Token("text", data=text)
                    yield Token("end", name=name)
                continue
            # stray '<' not starting a real tag -> literal text
            yield Token("text", data="<")
            i += 1
            continue
        # text run up to next '<'
        end = html.find("<", i)
        if end == -1:
            end = n
        yield Token("text", data=html[i:end])
        i = end


def _parse_tag(html, i):
    n = len(html)
    j = i + 1
    start = j
    while j < n and (html[j].isalnum() or html[j] in "-:"):
        j += 1
    name = html[start:j].lower()
    attrs = {}
    self_closing = False
    while j < n:
        while j < n and html[j] in " \t\r\n":
            j += 1
        if j < n and html[j] == "/":
            if html.startswith("/>", j):
                self_closing = True
                j += 2
                break
            j += 1
            continue
        if j < n and html[j] == ">":
            j += 1
            break
        if j >= n:
            break
        astart = j
        while j < n and html[j] not in " \t\r\n=/>":
            j += 1
        aname = html[astart:j].lower()
        if not aname:
            j += 1
            continue
        while j < n and html[j] in " \t\r\n":
            j += 1
        if j < n and html[j] == "=":
            j += 1
            while j < n and html[j] in " \t\r\n":
                j += 1
            if j < n and html[j] in "\"'":
                q = html[j]
                j += 1
                vstart = j
                j = html.find(q, j)
                if j == -1:
                    j = n
                    aval = html[vstart:]
                else:
                    aval = html[vstart:j]
                    j += 1
            else:
                vstart = j
                while j < n and html[j] not in " \t\r\n>":
                    j += 1
                aval = html[vstart:j]
            attrs[aname] = _unescape(aval)
        else:
            attrs[aname] = ""
    return name, attrs, self_closing, j


_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
    "nbsp": " ", "copy": "©", "mdash": "—", "ndash": "–",
    "hellip": "…", "rsquo": "’", "lsquo": "‘",
    "rdquo": "”", "ldquo": "“",
}


def _unescape(s):
    if "&" not in s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "&":
            semi = s.find(";", i, i + 12)
            if semi != -1:
                ent = s[i + 1:semi]
                if ent.startswith("#x") or ent.startswith("#X"):
                    try:
                        out.append(chr(int(ent[2:], 16)))
                        i = semi + 1
                        continue
                    except ValueError:
                        pass
                elif ent.startswith("#"):
                    try:
                        out.append(chr(int(ent[1:])))
                        i = semi + 1
                        continue
                    except ValueError:
                        pass
                elif ent in _ENTITIES:
                    out.append(_ENTITIES[ent])
                    i = semi + 1
                    continue
        out.append(s[i])
        i += 1
    return "".join(out)


def parse(html):
    """Parse an HTML string into a Document tree."""
    doc = Document()
    stack = [doc]

    def top():
        return stack[-1]

    for tok in tokenize(html):
        if tok.kind == "doctype":
            continue
        if tok.kind == "comment":
            top().append(Comment(_unescape(tok.data)))
            continue
        if tok.kind == "text":
            data = _unescape(tok.data)
            if data:
                top().append(Text(data))
            continue
        if tok.kind == "start":
            name = tok.name
            closers = AUTO_CLOSE.get(name)
            if closers:
                while (len(stack) > 1 and isinstance(top(), Element)
                       and top().tag in closers):
                    stack.pop()
            el = Element(name, tok.attrs)
            top().append(el)
            if name not in VOID_ELEMENTS and not tok.self_closing:
                stack.append(el)
            continue
        if tok.kind == "end":
            name = tok.name
            if name in VOID_ELEMENTS:
                continue
            for idx in range(len(stack) - 1, 0, -1):
                node = stack[idx]
                if isinstance(node, Element) and node.tag == name:
                    del stack[idx:]
                    break
            # else: stray end tag with no open match -> ignore
            continue
    _ensure_body(doc)
    return doc


def _ensure_body(doc):
    """Real HTML5 parsing always yields an implicit <html><head>...<body>
    structure regardless of what the author wrote — a bare text document,
    or top-level tags with no <body> wrapper at all, still render as if
    wrapped. Mirror that with a simple post-process: if there's no <body>
    anywhere in the tree, gather the document's actual content (skipping
    any <head>, which stays outside body like it does in a real browser)
    into a synthetic one."""
    if doc.find("body") is not None:
        return
    html_el = doc.find("html")
    container = html_el if html_el is not None else doc
    head = None
    rest = []
    for child in list(container.children):
        if isinstance(child, Element) and child.tag == "head":
            head = child
        else:
            rest.append(child)
    body = Element("body")
    for child in rest:
        body.append(child)
    if html_el is None:
        html_el = Element("html")
        doc.children = [html_el]
        html_el.parent = doc
    else:
        html_el.children = []
    if head is not None:
        html_el.append(head)
    html_el.append(body)
