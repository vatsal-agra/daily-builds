"""The top-level pipeline: HTML text -> DOM -> cascade -> layout -> paint
-> pixels. Every other module is a stage in this pipeline; this is the
only module that wires all of them together end to end.
"""

from .cascade import collect_author_css, compute_styles
from .dom import Element
from .html_parser import parse_html
from .layout import (
    DEFAULT_VIEWPORT_WIDTH,
    char_width,
    layout_document,
    line_height_px,
    parse_length,
)
from .paint import build_paint_commands
from .png_encoder import encode_png
from .raster import render_canvas


class Page:
    """The fully-processed result of rendering one HTML document: every
    intermediate stage is kept around so tests/tools/the inspector can
    inspect it, not just the final pixels."""

    def __init__(self, html_text, viewport_width=DEFAULT_VIEWPORT_WIDTH):
        self.html_text = html_text
        self.viewport_width = viewport_width
        self.document = parse_html(html_text)
        self.author_css = collect_author_css(self.document)
        self.styles = compute_styles(self.document, self.author_css)
        self.root_box = layout_document(self.document, self.styles, viewport_width)
        self.paint_commands = build_paint_commands(self.root_box)

    @property
    def height(self):
        return self.root_box.height if self.root_box else 0

    def _font_size_of(self, style):
        if style is None:
            return 16
        size = parse_length(style.get("font-size"), None)
        return size if isinstance(size, int) and size > 0 else 16

    def to_canvas(self):
        return render_canvas(
            self.paint_commands, self.viewport_width, max(1, self.height),
            char_width_fn=char_width, line_height_fn=line_height_px,
            font_size_of=self._font_size_of,
        )

    def to_png_bytes(self):
        canvas = self.to_canvas()
        return encode_png(canvas.pixels, canvas.width, canvas.height)

    def save_png(self, path):
        with open(path, "wb") as f:
            f.write(self.to_png_bytes())


def render_file(path, viewport_width=DEFAULT_VIEWPORT_WIDTH):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        html_text = f.read()
    return Page(html_text, viewport_width=viewport_width)


def render_html(html_text, viewport_width=DEFAULT_VIEWPORT_WIDTH):
    return Page(html_text, viewport_width=viewport_width)
