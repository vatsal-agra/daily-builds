"""The DOM: the tree the HTML parser builds and the CSS/layout stages consume."""

DOCUMENT = "document"
ELEMENT = "element"
TEXT = "text"
COMMENT = "comment"

# Elements that never have content / a closing tag (HTML "void elements").
VOID_ELEMENTS = frozenset(
    [
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    ]
)

# Elements whose content is not parsed as markup at all -- read verbatim
# until the matching end tag.
RAW_TEXT_ELEMENTS = frozenset(["script", "style"])
# Elements whose content is text but character references are still decoded
# (unlike script/style, whose content genuinely isn't HTML at all).
ESCAPABLE_RAW_TEXT_ELEMENTS = frozenset(["textarea", "title"])


class Node:
    """Base DOM node. Every node type below subclasses this."""

    __slots__ = ("node_type", "parent", "children")

    def __init__(self, node_type):
        self.node_type = node_type
        self.parent = None
        self.children = []

    def append_child(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def iter_descendants(self):
        # Iterative (explicit stack), not recursive: a deeply-nested
        # document (thousands of levels -- not unheard of from WYSIWYG
        # editor output) must not blow Python's recursion limit just to be
        # walked for style extraction or searching.
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def iter_element_descendants(self):
        for node in self.iter_descendants():
            if node.node_type == ELEMENT:
                yield node

    @property
    def is_element(self):
        return self.node_type == ELEMENT

    @property
    def is_text(self):
        return self.node_type == TEXT


class Document(Node):
    __slots__ = ()

    def __init__(self):
        super().__init__(DOCUMENT)

    def __repr__(self):
        return "#document"


class Element(Node):
    __slots__ = ("tag", "attrs")

    def __init__(self, tag, attrs=None):
        super().__init__(ELEMENT)
        self.tag = tag
        self.attrs = attrs or {}

    def get_attr(self, name, default=None):
        return self.attrs.get(name, default)

    @property
    def id(self):
        return self.attrs.get("id")

    @property
    def class_list(self):
        cls = self.attrs.get("class", "")
        return [c for c in cls.split() if c]

    def __repr__(self):
        bits = [self.tag]
        if self.id:
            bits.append("#" + self.id)
        for c in self.class_list:
            bits.append("." + c)
        return "<" + " ".join(bits) + ">"


class Text(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__(TEXT)
        self.data = data

    def __repr__(self):
        preview = self.data if len(self.data) <= 24 else self.data[:21] + "..."
        return "#text %r" % preview


class Comment(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__(COMMENT)
        self.data = data

    def __repr__(self):
        return "#comment %r" % self.data


def find_first(root, predicate):
    for node in root.iter_descendants():
        if predicate(node):
            return node
    return None


def find_element(root, tag):
    return find_first(root, lambda n: n.is_element and n.tag == tag)


def pick_layout_root(document):
    """The element layout should start from: <body> if present, else
    <html>, else the first top-level element, else None if the document has
    no elements at all (e.g. an empty file) -- callers must handle that
    case explicitly rather than assuming a root always exists."""
    body = find_element(document, "body")
    if body is not None:
        return body
    html = find_element(document, "html")
    if html is not None:
        return html
    for child in document.children:
        if child.is_element:
            return child
    return None


def pretty(node, depth=0, out=None):
    """A tiny indented tree dump, useful for debugging/tests."""
    top = out is None
    if out is None:
        out = []
    out.append("  " * depth + repr(node))
    for child in node.children:
        pretty(child, depth + 1, out)
    if top:
        return "\n".join(out)
    return None
