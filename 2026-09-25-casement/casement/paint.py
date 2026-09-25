"""The software rasterizer: walks a laid-out box tree and paints an RGBA
framebuffer -- backgrounds, borders, and bitmap-font text -- which the
caller then hands to `png_encoder`.

Paint order: normal-flow content paints in document (pre-)order (parents
before children, matching the real "backgrounds/borders below content"
rule closely enough for flat, non-overlapping layouts); every
`position: absolute` box and its whole descendant subtree is pulled into
its own paint group and painted afterward, groups sorted by `z-index`
(default 0) -- an approximation of real nested stacking contexts, not a
full implementation of the CSS stacking-context algorithm.
"""

from .font import GLYPH_H, advance_width, glyph_bitmap

WHITE = (255, 255, 255, 255)


class Framebuffer:
    def __init__(self, width, height, background=WHITE):
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 4)
        r, g, b, a = background
        for i in range(0, len(self.pixels), 4):
            self.pixels[i] = r
            self.pixels[i + 1] = g
            self.pixels[i + 2] = b
            self.pixels[i + 3] = 255

    def set_pixel(self, x, y, r, g, b, a):
        if x < 0 or y < 0 or x >= self.width or y >= self.height or a <= 0:
            return
        idx = (y * self.width + x) * 4
        px = self.pixels
        if a >= 255:
            px[idx], px[idx + 1], px[idx + 2], px[idx + 3] = r, g, b, 255
            return
        na = a / 255.0
        ia = 1.0 - na
        px[idx] = int(r * na + px[idx] * ia)
        px[idx + 1] = int(g * na + px[idx + 1] * ia)
        px[idx + 2] = int(b * na + px[idx + 2] * ia)
        px[idx + 3] = 255

    def fill_rect(self, x, y, w, h, color):
        r, g, b, a = color
        if a <= 0 or w <= 0 or h <= 0:
            return
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = int(round(x + w)), int(round(y + h))
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(self.width, x1), min(self.height, y1)
        if a >= 255:
            for yy in range(y0c, y1c):
                idx0 = (yy * self.width + x0c) * 4
                idx1 = (yy * self.width + x1c) * 4
                self.pixels[idx0:idx1] = bytes((r, g, b, 255)) * (x1c - x0c)
        else:
            for yy in range(y0c, y1c):
                for xx in range(x0c, x1c):
                    self.set_pixel(xx, yy, r, g, b, a)

    def draw_line(self, x0, y0, x1, y1, color, thickness=1):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.fill_rect(x0 - thickness // 2, y0 - thickness // 2, thickness, thickness, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy


def draw_text(fb, x, y, text, font_size, color, bold=False):
    scale = max(1.0, font_size / GLYPH_H)
    adv = advance_width(font_size)
    cursor_x = x
    for ch in text:
        bitmap = glyph_bitmap(ch)
        for row, bits in enumerate(bitmap):
            for col, on in enumerate(bits):
                if not on:
                    continue
                px0 = cursor_x + col * scale
                py0 = y + row * scale
                fb.fill_rect(px0, py0, scale, scale, color)
                if bold:
                    fb.fill_rect(px0 + scale * 0.45, py0, scale, scale, color)
        cursor_x += adv


def _collect_paint_order(root):
    normal = []
    groups = []  # list of (z_index, [boxes])

    def walk_children(box, group):
        for c in box.children:
            if isinstance(c, tuple):
                continue
            walk(c, group)
        if box.lines:
            for line in box.lines:
                for item in line.items:
                    if item[1] in ("replaced", "inline-block"):
                        walk(item[2], group)
        for a in box.absolute_children:
            walk(a, None)

    def walk(box, group):
        if group is not None:
            group.append(box)
            walk_children(box, group)
            return
        is_abs = box.style is not None and box.style.keyword("position") == "absolute"
        if is_abs:
            try:
                z = int(box.style.raw("z-index"))
            except ValueError:
                z = 0
            new_group = [box]
            groups.append((z, new_group))
            walk_children(box, new_group)
        else:
            normal.append(box)
            walk_children(box, None)

    walk(root, None)
    groups.sort(key=lambda g: g[0])
    positioned = [b for _, g in groups for b in g]
    return normal, positioned


def paint_document(root_box, width, height):
    fb = Framebuffer(width, height)
    normal, positioned = _collect_paint_order(root_box)
    for box in normal:
        paint_box(fb, box)
    for box in positioned:
        paint_box(fb, box)
    return fb


def paint_box(fb, box):
    if box.box_type == "anonymous-block":
        _paint_lines(fb, box)
        return
    if box.style is None:
        return
    bx, by, bw, bh = box.dims.border_box()
    bg = box.style.color("background-color")
    if bg[3] > 0:
        fb.fill_rect(bx, by, bw, bh, bg)

    d = box.dims
    border_color_top = box.style.color("border-top-color")
    border_color_right = box.style.color("border-right-color")
    border_color_bottom = box.style.color("border-bottom-color")
    border_color_left = box.style.color("border-left-color")
    if d.border.top > 0:
        fb.fill_rect(bx, by, bw, d.border.top, border_color_top)
    if d.border.bottom > 0:
        fb.fill_rect(bx, by + bh - d.border.bottom, bw, d.border.bottom, border_color_bottom)
    if d.border.left > 0:
        fb.fill_rect(bx, by + d.border.top, d.border.left, bh - d.border.top - d.border.bottom, border_color_left)
    if d.border.right > 0:
        fb.fill_rect(bx + bw - d.border.right, by + d.border.top, d.border.right, bh - d.border.top - d.border.bottom, border_color_right)

    if box.box_type == "replaced" and box.replaced_kind == "img":
        _paint_image_placeholder(fb, box)


def _paint_image_placeholder(fb, box):
    x, y, w, h = box.dims.x, box.dims.y, box.dims.width, box.dims.height
    if w <= 0 or h <= 0:
        return
    frame_color = (150, 150, 150, 255)
    fb.fill_rect(x, y, w, 2, frame_color)
    fb.fill_rect(x, y + h - 2, w, 2, frame_color)
    fb.fill_rect(x, y, 2, h, frame_color)
    fb.fill_rect(x + w - 2, y, 2, h, frame_color)
    fb.draw_line(x + 3, y + 3, x + w - 3, y + h - 3, frame_color, thickness=1)
    fb.draw_line(x + w - 3, y + 3, x + 3, y + h - 3, frame_color, thickness=1)


def _paint_lines(fb, box):
    if not box.lines:
        return
    origin_x, origin_y = box.dims.x, box.dims.y
    for line in box.lines:
        for (x, kind, payload, style, w, h) in line.items:
            if kind == "word":
                color = style.color("color")
                draw_text(fb, origin_x + x, origin_y + line.y, payload, style.font_size_px(), color, style.is_bold())
