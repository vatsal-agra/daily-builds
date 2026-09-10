"""The DOM tree: Node, Element, Text, Comment, Document."""

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# Elements that auto-close when one of these tags is seen again while it is
# still open (a simplified version of HTML5's implicit end tag rules).
AUTO_CLOSE = {
    "p": {"p", "div", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
          "section", "article", "header", "footer", "form", "blockquote"},
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "tr": {"tr"},
    "td": {"td", "th", "tr"},
    "th": {"td", "th", "tr"},
    "option": {"option"},
    "thead": {"tbody", "tfoot"},
    "tbody": {"tbody", "tfoot"},
}


class Node:
    """Base DOM node."""

    def __init__(self):
        self.parent = None
        self.children = []

    def append_child(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def iter_descendants(self):
        for c in self.children:
            yield c
            yield from c.iter_descendants()

    def element_children(self):
        return [c for c in self.children if isinstance(c, Element)]

    @property
    def next_sibling_element(self):
        if self.parent is None:
            return None
        sibs = self.parent.element_children()
        idx = sibs.index(self) if self in sibs else -1
        if idx == -1 or idx + 1 >= len(sibs):
            return None
        return sibs[idx + 1]

    @property
    def prev_sibling_element(self):
        if self.parent is None:
            return None
        sibs = self.parent.element_children()
        idx = sibs.index(self) if self in sibs else -1
        if idx <= 0:
            return None
        return sibs[idx - 1]


class Document(Node):
    def __repr__(self):
        return "#document"


class Element(Node):
    def __init__(self, tag, attrs=None):
        super().__init__()
        self.tag = tag.lower()
        self.attrs = attrs or {}
        # filled in later by the cascade
        self.computed_style = {}
        # filled in later by layout
        self.box = None

    @property
    def id(self):
        return self.attrs.get("id", "")

    @property
    def classes(self):
        c = self.attrs.get("class", "")
        return [x for x in c.split() if x]

    def is_void(self):
        return self.tag in VOID_ELEMENTS

    def text_content(self):
        out = []
        for c in self.children:
            if isinstance(c, Text):
                out.append(c.data)
            elif isinstance(c, Element):
                out.append(c.text_content())
        return "".join(out)

    def __repr__(self):
        cls = f".{'.'.join(self.classes)}" if self.classes else ""
        idn = f"#{self.id}" if self.id else ""
        return f"<{self.tag}{idn}{cls}>"


class Text(Node):
    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        preview = self.data.strip().replace("\n", " ")[:24]
        return f"#text({preview!r})"


class Comment(Node):
    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        return f"#comment({self.data[:24]!r})"


def find_first(node, tag):
    for c in node.iter_descendants():
        if isinstance(c, Element) and c.tag == tag:
            return c
    return None


def find_all(node, tag=None, cls=None, id_=None):
    out = []
    for c in node.iter_descendants():
        if not isinstance(c, Element):
            continue
        if tag is not None and c.tag != tag:
            continue
        if cls is not None and cls not in c.classes:
            continue
        if id_ is not None and c.id != id_:
            continue
        out.append(c)
    return out
