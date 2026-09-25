"""Top-level pipeline: HTML+CSS source -> PNG bytes + exported layout JSON."""

import math

from . import css_parser, html_parser, paint, png_encoder, style
from .dom import Element, find_all
from .layout import (
    ContainingBlock,
    LayoutBox,
    _resolve_edges,
    apply_relative_offset,
    build_document_box,
    layout_box,
    resolve_absolutes_against,
)


def assign_cids(document):
    """Tag every Element with a stable `data-cid` attribute, used to match
    elements between Casement's own box tree and an external oracle (e.g.
    a real browser) rendering the same (cid-tagged) HTML source."""
    i = 0
    for node in document.iter():
        if isinstance(node, Element):
            node.attrs["data-cid"] = str(i)
            i += 1


def collect_css(document, extra_css=""):
    parts = []
    for style_el in find_all(document, "style"):
        for child in style_el.children:
            if hasattr(child, "data"):
                parts.append(child.data)
    if extra_css:
        parts.append(extra_css)
    return "\n".join(parts)


def compute_page_height(root_box, min_height=0.0):
    max_bottom = [min_height]

    def visit(box):
        _, y, _, h = box.dims.margin_box()
        if y + h > max_bottom[0]:
            max_bottom[0] = y + h
        for c in box.children:
            if isinstance(c, tuple):
                continue
            visit(c)
        if box.lines:
            for line in box.lines:
                for item in line.items:
                    if item[1] in ("replaced", "inline-block"):
                        visit(item[2])
        for a in box.absolute_children:
            visit(a)

    visit(root_box)
    return max_bottom[0]


class RenderResult:
    def __init__(self, png_bytes, width, height, root_box, style_map, document):
        self.png_bytes = png_bytes
        self.width = width
        self.height = height
        self.root_box = root_box
        self.style_map = style_map
        self.document = document


def render(html_text, extra_css="", viewport_width=800, tag_cids=True):
    document = html_parser.parse(html_text)
    if tag_cids:
        assign_cids(document)
    css_text = collect_css(document, extra_css)
    sheet = css_parser.parse_stylesheet(css_text)
    style_map = style.compute_styles(document, sheet)
    root_box, root_absolutes = build_document_box(document, style_map)
    if root_box is None:
        root_box = LayoutBox("block", None, None)

    cb = ContainingBlock(width=float(viewport_width), height=None)
    if root_box.style is not None:
        ml, mr = _resolve_edges(root_box, cb.width)
        d = root_box.dims
        d.margin.left = ml if ml is not None else 0.0
        d.margin.right = mr if mr is not None else 0.0
        d.x = d.margin.left + d.border.left + d.padding.left
        d.y = d.margin.top + d.border.top + d.padding.top
    layout_box(root_box, cb, cb)
    apply_relative_offset(root_box, cb.width)

    # Absolutely-positioned elements with no positioned ancestor anywhere
    # resolve against the true viewport (the initial containing block),
    # not against <body>'s own content box -- so these are positioned in a
    # separate pass here rather than through root_box.absolute_children.
    if root_absolutes:
        prelim_height = compute_page_height(root_box, min_height=1.0)
        resolve_absolutes_against(root_absolutes, 0.0, 0.0, cb.width, prelim_height, cb)
        root_box.absolute_children.extend(root_absolutes)

    page_height = compute_page_height(root_box, min_height=1.0)
    height_px = max(1, int(math.ceil(page_height)))
    width_px = max(1, int(viewport_width))

    fb = paint.paint_document(root_box, width_px, height_px)
    png_bytes = png_encoder.encode_rgba(width_px, height_px, fb.pixels)
    return RenderResult(png_bytes, width_px, height_px, root_box, style_map, document)


def export_layout_json(root_box):
    def box_json(box):
        node = box.node
        entry = {
            "box_type": box.box_type,
            "tag": node.tag if isinstance(node, Element) else None,
            "cid": node.attrs.get("data-cid") if isinstance(node, Element) else None,
            "dims": box.dims.to_dict(),
            "children": [],
        }
        for c in box.children:
            if isinstance(c, tuple):
                entry["children"].append(box_json(c[1]))
            else:
                entry["children"].append(box_json(c))
        for a in box.absolute_children:
            entry["children"].append(box_json(a))
        if box.lines:
            words = []
            for line in box.lines:
                for item in line.items:
                    if item[1] == "word":
                        words.append(item[2])
                    elif item[1] in ("replaced", "inline-block"):
                        entry["children"].append(box_json(item[2]))
            if words:
                entry["text"] = " ".join(words)
        return entry

    return box_json(root_box)
