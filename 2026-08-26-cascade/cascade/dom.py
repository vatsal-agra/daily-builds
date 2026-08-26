"""DOM node types produced by the HTML parser."""

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# Elements whose content is raw text (not re-tokenized as markup) until the
# matching end tag is found. Real HTML5 also raw-texts <textarea>/<title>;
# we handle those the same way.
RAWTEXT_ELEMENTS = {"script", "style", "textarea", "title"}


class Node:
    __slots__ = ("parent", "children")

    def __init__(self):
        self.parent = None
        self.children = []

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def element_children(self):
        return [c for c in self.children if isinstance(c, Element)]

    def walk(self):
        """Pre-order traversal of self and all descendants."""
        yield self
        for c in self.children:
            yield from c.walk()

    def walk_elements(self):
        for n in self.walk():
            if isinstance(n, Element):
                yield n

    def find(self, tag):
        """First descendant (or self) with this tag name."""
        for e in self.walk_elements():
            if e.tag == tag:
                return e
        return None

    def find_all(self, tag):
        return [e for e in self.walk_elements() if e.tag == tag]


class Document(Node):
    __slots__ = ()

    def __repr__(self):
        return f"Document({len(self.children)} children)"


class Element(Node):
    __slots__ = ("tag", "attrs")

    def __init__(self, tag, attrs=None):
        super().__init__()
        self.tag = tag
        self.attrs = attrs or {}

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    def classes(self):
        c = self.attrs.get("class", "")
        return [x for x in c.split() if x]

    def id(self):
        return self.attrs.get("id")

    def text_content(self):
        out = []
        for n in self.walk():
            if isinstance(n, Text):
                out.append(n.data)
        return "".join(out)

    def __repr__(self):
        bits = [self.tag]
        if self.attrs.get("id"):
            bits.append(f"#{self.attrs['id']}")
        if self.attrs.get("class"):
            bits.append("." + ".".join(self.classes()))
        return f"<{' '.join(bits)}>"


class Text(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        d = self.data if len(self.data) <= 20 else self.data[:17] + "..."
        return f"Text({d!r})"


class Comment(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        return f"Comment({self.data!r})"
