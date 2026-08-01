"""The painter: walks the final layout tree in paint order and rasterizes
backgrounds, borders, and glyph text into an RGB `Canvas`, ready for
`Canvas.to_png()`."""

from . import font
from .colors import parse_color
from .png_encoder import Canvas


def paint(layout_root, background=(255, 255, 255)):
    width = max(1, int(round(layout_root.border_box_width())))
    height = max(1, int(round(layout_root.border_box_height())))
    canvas = Canvas(width, height, background=background)
    _paint_box(layout_root, canvas)
    return canvas


def _paint_box(box, canvas):
    if box.box_type == 'line':
        _paint_line(box, canvas)
        return

    bg = parse_color(box.background)
    box_w = box.border_box_width()
    box_h = box.border_box_height()
    if bg is not None:
        canvas.fill_rect(box.x, box.y, box_w, box_h, bg)

    bt, br, bb, bl = box.border
    styles = box.border_style
    colors = box.border_color
    if bt > 0 and styles[0] not in (None, 'none'):
        canvas.fill_rect(box.x, box.y, box_w, bt, parse_color(colors[0]))
    if bb > 0 and styles[2] not in (None, 'none'):
        canvas.fill_rect(box.x, box.y + box_h - bb, box_w, bb, parse_color(colors[2]))
    if bl > 0 and styles[3] not in (None, 'none'):
        canvas.fill_rect(box.x, box.y, bl, box_h, parse_color(colors[3]))
    if br > 0 and styles[1] not in (None, 'none'):
        canvas.fill_rect(box.x + box_w - br, box.y, br, box_h, parse_color(colors[1]))

    for child in box.children:
        _paint_box(child, canvas)


def _paint_line(box, canvas):
    for frag in box.fragments:
        color = parse_color(frag['color']) or (0, 0, 0)
        scale = frag['scale']
        base_x = frag['x']
        base_y = frag['y']
        for index, ch in enumerate(frag['text']):
            glyph_x = base_x + index * font.GLYPH_ADVANCE * scale
            for dx, dy in font.render_glyph(ch, scale):
                canvas.set_pixel(int(round(glyph_x + dx)), int(round(base_y + dy)), color)
