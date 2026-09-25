"""The DOM tree produced by the HTML parser."""


class Node:
    __slots__ = ("parent", "children")

    def __init__(self):
        self.parent = None
        self.children = []

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def iter(self):
        yield self
        for c in self.children:
            yield from c.iter()

    def element_children(self):
        return [c for c in self.children if isinstance(c, Element)]


class Document(Node):
    __slots__ = ()

    def __repr__(self):
        return "#document"


class Element(Node):
    __slots__ = ("tag", "attrs")

    def __init__(self, tag, attrs=None):
        super().__init__()
        self.tag = tag
        self.attrs = attrs or {}

    def get(self, name, default=None):
        return self.attrs.get(name, default)

    @property
    def classes(self):
        cls = self.attrs.get("class", "")
        return [c for c in cls.split() if c]

    @property
    def id(self):
        return self.attrs.get("id")

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
        return f"#text({self.data!r})"


class Comment(Node):
    __slots__ = ("data",)

    def __init__(self, data):
        super().__init__()
        self.data = data

    def __repr__(self):
        return f"#comment({self.data!r})"


def find_first(root, tag):
    for n in root.iter():
        if isinstance(n, Element) and n.tag == tag:
            return n
    return None


def find_all(root, tag):
    return [n for n in root.iter() if isinstance(n, Element) and n.tag == tag]
