import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from folio.html_parser import parse_html
from folio.cascade import compute_style_tree
from folio.layout import layout_subtree
from folio.dom import find_element

VIEWPORT = 800


def render(body_html, css="", viewport=VIEWPORT):
    """Parse+cascade+layout a `<body>...</body>` fragment. Returns
    (document, styles, root_box, box_by_testid) where box_by_testid maps a
    `data-t` attribute value to its LayoutBox."""
    full_html = "<html><head><style>%s</style></head><body>%s</body></html>" % (css, body_html)
    doc = parse_html(full_html)
    styles = compute_style_tree(doc, [])
    body = find_element(doc, "body")
    root = layout_subtree(body, styles, viewport)

    by_testid = {}

    def walk(box):
        if box.element is not None:
            t = box.element.get_attr("data-t")
            if t:
                by_testid[t] = box
        for c in box.block_children:
            walk(c)
        # inline-mode boxes with data-t on nested inline elements aren't
        # tracked here (Folio doesn't build per-inline-element boxes) --
        # tests only tag block-level elements.

    walk(root)
    return doc, styles, root, by_testid


def full_document_html(body_html, css=""):
    # The doctype matters: without one, real browsers render in "quirks
    # mode" with different (legacy, non-CSS2.1) collapsing/box-model
    # behavior -- Folio implements standards-mode CSS2.1, so fixtures
    # compared against the Chromium oracle must opt into standards mode
    # the same way any real page does.
    return "<!DOCTYPE html><html><head><style>%s</style></head><body>%s</body></html>" % (css, body_html)
