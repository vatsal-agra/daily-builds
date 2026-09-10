"""Paints a laid-out box tree to a Canvas: solid backgrounds, all four
border edges, and hand-rolled bitmap-font text -- no browser, no imaging
library involved in producing the pixels."""

from font import GLYPH_H, GLYPH_W, char_advance, glyph_for
from png_encoder import Canvas


def paint_tree(box, viewport_width, viewport_height=None, background=(255, 255, 255, 255)):
    height = viewport_height if viewport_height is not None else max(box.height, 1)
    canvas = Canvas(viewport_width, int(height) + 1, background=background)
    paint_box(canvas, box)
    return canvas


def paint_box(canvas, box):
    if box.box_type not in ("text",):
        if box.background_color[3] > 0:
            canvas.fill_rect(box.x, box.y, box.width, box.height, box.background_color)
        b = box.border
        bc = box.border_color
        if b.top > 0:
            canvas.fill_rect(box.x, box.y, box.width, b.top, bc.top)
        if b.bottom > 0:
            canvas.fill_rect(box.x, box.y + box.height - b.bottom, box.width, b.bottom, bc.bottom)
        if b.left > 0:
            canvas.fill_rect(box.x, box.y, b.left, box.height, bc.left)
        if b.right > 0:
            canvas.fill_rect(box.x + box.width - b.right, box.y, b.right, box.height, bc.right)

    if box.box_type == "text" and box.text:
        draw_text(canvas, box.x, box.y, box.text, box.font_size, box.color, box.font_weight)

    for child in box.children:
        paint_box(canvas, child)


def draw_text(canvas, x, y, text, font_size, color, weight):
    px = max(font_size / 10.0, 1.0)
    top_pad = font_size * 0.15
    cx = float(x)
    for ch in text:
        if ch == " ":
            cx += char_advance(font_size)
            continue
        glyph = glyph_for(ch)
        if glyph is not None:
            for row in range(GLYPH_H):
                bits = glyph[row]
                for col in range(GLYPH_W):
                    if bits & (1 << (GLYPH_W - 1 - col)):
                        canvas.fill_rect(cx + col * px, y + top_pad + row * px, px, px, color)
                        if weight >= 700:
                            canvas.fill_rect(cx + col * px + px * 0.5, y + top_pad + row * px, px, px, color)
        cx += char_advance(font_size)
