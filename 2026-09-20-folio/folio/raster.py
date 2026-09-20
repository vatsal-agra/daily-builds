"""Rasterizes a paint-command list to an RGB pixel buffer -- fills, strokes,
and from-scratch bitmap-font text -- with zero help from any imaging
library. This is the code that actually draws every pixel; png_encoder.py
only frames the result as a valid PNG file afterward.
"""

from .bitmap_font import GLYPH_HEIGHT, GLYPH_WIDTH, glyph_for

BACKGROUND = (255, 255, 255)


class Canvas:
    def __init__(self, width, height, background=BACKGROUND):
        self.width = max(1, width)
        self.height = max(1, height)
        self.pixels = bytearray(background * (self.width * self.height))

    def set_pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 3
            self.pixels[idx] = color[0]
            self.pixels[idx + 1] = color[1]
            self.pixels[idx + 2] = color[2]

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.width, int(x + w))
        y1 = min(self.height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            start = (yy * self.width + x0) * 3
            self.pixels[start:start + len(row)] = row

    def draw_char(self, x, y, char, color, cell_w, cell_h, bold=False, italic=False):
        glyph = glyph_for(char)
        scale_x = max(1, cell_w // GLYPH_WIDTH)
        scale_y = max(1, cell_h // GLYPH_HEIGHT)
        shear_rows = GLYPH_HEIGHT
        for row_idx, row in enumerate(glyph):
            shear = (shear_rows - 1 - row_idx) // 3 if italic else 0
            for col_idx, ch in enumerate(row):
                if ch != "#":
                    continue
                px0 = x + (col_idx + shear) * scale_x
                py0 = y + row_idx * scale_y
                self.fill_rect(px0, py0, scale_x + (1 if bold else 0), scale_y, color)

    def draw_text(self, x, y, text, color, char_width, line_height, bold=False,
                  italic=False, underline=False):
        cell_h = min(line_height, GLYPH_HEIGHT * 2)
        cx = x
        for ch in text:
            self.draw_char(cx, y, ch, color, char_width, cell_h, bold, italic)
            cx += char_width
        if underline:
            self.fill_rect(x, y + cell_h, len(text) * char_width, 1, color)


def render_canvas(paint_commands, width, height, char_width_fn, line_height_fn,
                   font_size_of):
    canvas = Canvas(width, height)
    for cmd in paint_commands:
        if cmd.kind == "rect":
            canvas.fill_rect(cmd.x, cmd.y, cmd.width, cmd.height, cmd.color)
        elif cmd.kind == "text":
            font_size = font_size_of(cmd.box.style)
            cw = char_width_fn(font_size)
            lh = line_height_fn(font_size)
            canvas.draw_text(
                cmd.x, cmd.y, cmd.extra["text"], cmd.color, cw, lh,
                bold=cmd.extra.get("bold", False),
                italic=cmd.extra.get("italic", False),
                underline=cmd.extra.get("underline", False),
            )
    return canvas
