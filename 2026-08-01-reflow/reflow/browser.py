"""Ties the four pipeline stages together: HTML text (+ optional external
CSS text) in, a rendered page (DOM, CSSOM, layout tree, and real PNG
bytes) out."""

from .cascade import compute_styles
from .html_parser import parse
from .layout import layout_document
from .paint import paint


class RenderResult:
    def __init__(self, dom, styles, stylesheet, layout_root, canvas):
        self.dom = dom
        self.styles = styles
        self.stylesheet = stylesheet
        self.layout_root = layout_root
        self.canvas = canvas

    @property
    def png(self):
        return self.canvas.to_png()


def render_page(html_text, extra_css='', viewport_width=800):
    dom = parse(html_text)
    styles, stylesheet = compute_styles(dom, extra_css)
    layout_root = layout_document(dom, styles, viewport_width)
    canvas = paint(layout_root)
    return RenderResult(dom, styles, stylesheet, layout_root, canvas)
