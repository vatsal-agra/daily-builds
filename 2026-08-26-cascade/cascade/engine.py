"""Top-level entry point: HTML + CSS text -> DOM, computed styles, layout
box tree, and painted SVG, in one call."""

from .html_parser import parse as parse_html
from .cascade import compute_styles
from .layout import layout_document
from .paint import paint_svg
from .dom import Element


def _collect_author_css(dom):
    """Author CSS = any <style> element text, in document order."""
    parts = []
    for el in dom.walk_elements():
        if el.tag == "style":
            parts.append(el.text_content())
    return "\n".join(parts)


class RenderResult:
    def __init__(self, dom, styles, box, svg, viewport_width):
        self.dom = dom
        self.styles = styles
        self.box = box
        self.svg = svg
        self.viewport_width = viewport_width


def render_html(html, extra_css="", viewport_width=800):
    dom = parse_html(html)
    css = _collect_author_css(dom)
    if extra_css:
        css = css + "\n" + extra_css
    styles = compute_styles(dom, css)
    box, bfc = layout_document(dom, styles, viewport_width)
    svg = paint_svg(box, viewport_width) if box is not None else _empty_svg(viewport_width)
    return RenderResult(dom, styles, box, svg, viewport_width)


def _empty_svg(viewport_width):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{viewport_width}" height="0" '
            f'viewBox="0 0 {viewport_width} 0"></svg>')
