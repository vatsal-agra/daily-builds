"""The DOM tree Folio's HTML parser builds and every later stage walks."""

VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

# Elements whose end tag implicitly closes an already-open element of the
# same or a related kind, the way a real browser's HTML parser does, so
# "<p>a<p>b" and "<ul><li>a<li>b</ul>" don't nest forever.
IMPLIED_END_TAGS = {
    "p": {"p"},
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "option": {"option"},
    "tr": {"tr"},
    "td": {"td", "th"},
    "th": {"td", "th"},
}

# Elements whose content is raw text: the tokenizer must not look for tags
# inside them, only for their own matching end tag.
RAW_TEXT_ELEMENTS = frozenset({"script", "style"})

# Starting any of these tags implicitly closes an open <p>, the same way a
# real browser's parser does (HTML5 §13.2.6.4.4, "a start tag whose tag name
# is one of..."), so "<p>a<ul><li>b</ul>" doesn't nest the list inside the
# paragraph.
P_CLOSING_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol", "p",
    "pre", "section", "table", "ul",
})


class Node:
    """Base class for every DOM node kind."""

    __slots__ = ("parent",)

    def __init__(self):
        self.parent = None


class Document(Node):
    __slots__ = ("children",)

    def __init__(self):
        super().__init__()
        self.children = []

    def __repr__(self):
        return "#document"


class Element(Node):
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs=None):
        super().__init__()
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    @property
    def id(self):
        return self.attrs.get("id")

    @property
    def classes(self):
        cls = self.attrs.get("class")
        if not cls:
            return []
        return cls.split()

    def text_content(self):
        parts = []
        for child in self.children:
            if isinstance(child, Text):
                parts.append(child.data)
            elif isinstance(child, Element):
                parts.append(child.text_content())
        return "".join(parts)

    def __repr__(self):
        bits = [self.tag]
        if self.id:
            bits.append(f"#{self.id}")
        for c in self.classes:
            bits.append(f".{c}")
        return "<" + "".join(bits) + ">"


class Text(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        snippet = self.data.strip().replace("\n", " ")
        if len(snippet) > 20:
            snippet = snippet[:20] + "…"
        return f"#text{snippet!r}"


class Comment(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        return f"<!--{self.data.strip()!r}-->"


def iter_descendants(node):
    """Depth-first, document-order walk of Element descendants (self included)."""
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, Document):
            children = cur.children
        elif isinstance(cur, Element):
            yield cur
            children = cur.children
        else:
            continue
        stack.extend(reversed(children))


def find_first(node, tag):
    for el in iter_descendants(node):
        if el.tag == tag:
            return el
    return None


def find_all(node, tag):
    return [el for el in iter_descendants(node) if el.tag == tag]
