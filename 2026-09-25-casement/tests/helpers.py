from casement.dom import Element


def iter_boxes(box):
    yield box
    for c in box.children:
        if isinstance(c, tuple):
            continue
        yield from iter_boxes(c)
    if box.lines:
        for line in box.lines:
            for item in line.items:
                if item[1] in ("replaced", "inline-block"):
                    yield from iter_boxes(item[2])
    for a in box.absolute_children:
        yield from iter_boxes(a)


def find_box(root, tag=None, cls=None, node_id=None):
    for b in iter_boxes(root):
        node = b.node
        if not isinstance(node, Element):
            continue
        if tag is not None and node.tag != tag:
            continue
        if cls is not None and cls not in node.classes:
            continue
        if node_id is not None and node.id != node_id:
            continue
        return b
    return None


def find_all_boxes(root, tag=None, cls=None):
    out = []
    for b in iter_boxes(root):
        node = b.node
        if not isinstance(node, Element):
            continue
        if tag is not None and node.tag != tag:
            continue
        if cls is not None and cls not in node.classes:
            continue
        out.append(b)
    return out
