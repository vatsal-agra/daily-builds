"""CSS color-value parsing: named colors, `#rgb`/`#rrggbb` hex, and
`rgb(r, g, b)` functional notation, resolved to an (r, g, b) tuple or
`None` for `transparent`/`none` (meaning: don't paint, let what's behind
show through)."""

NAMED_COLORS = {
    'black': (0, 0, 0), 'white': (255, 255, 255), 'red': (255, 0, 0),
    'green': (0, 128, 0), 'blue': (0, 0, 255), 'yellow': (255, 255, 0),
    'gray': (128, 128, 128), 'grey': (128, 128, 128),
    'orange': (255, 165, 0), 'purple': (128, 0, 128),
    'pink': (255, 192, 203), 'brown': (165, 42, 42),
    'cyan': (0, 255, 255), 'magenta': (255, 0, 255), 'lime': (0, 255, 0),
    'navy': (0, 0, 128), 'teal': (0, 128, 128), 'maroon': (128, 0, 0),
    'olive': (128, 128, 0), 'silver': (192, 192, 192), 'gold': (255, 215, 0),
    'coral': (255, 127, 80), 'salmon': (250, 128, 114),
    'indigo': (75, 0, 130), 'violet': (238, 130, 238),
    'darkred': (139, 0, 0), 'darkblue': (0, 0, 139), 'darkgreen': (0, 100, 0),
    'lightblue': (173, 216, 230), 'lightgreen': (144, 238, 144),
    'lightgray': (211, 211, 211), 'lightgrey': (211, 211, 211),
    'darkgray': (169, 169, 169), 'darkgrey': (169, 169, 169),
    'beige': (245, 245, 220), 'ivory': (255, 255, 240),
    'crimson': (220, 20, 60), 'chocolate': (210, 105, 30),
    'skyblue': (135, 206, 235), 'slategray': (112, 128, 144),
    'tomato': (255, 99, 71), 'khaki': (240, 230, 140),
}


def parse_color(value, default=(0, 0, 0)):
    if value is None:
        return None
    value = str(value).strip().lower()
    if value in ('', 'transparent', 'none'):
        return None
    if value.startswith('#'):
        hex_part = value[1:]
        try:
            if len(hex_part) == 3:
                return tuple(int(c * 2, 16) for c in hex_part)
            if len(hex_part) == 6:
                return tuple(int(hex_part[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return default
        return default
    if value.startswith('rgb'):
        start = value.find('(')
        end = value.find(')')
        if start == -1 or end == -1:
            return default
        parts = [p.strip() for p in value[start + 1:end].split(',')]
        try:
            r, g, b = (max(0, min(255, int(float(parts[i])))) for i in range(3))
            return (r, g, b)
        except (ValueError, IndexError):
            return default
    return NAMED_COLORS.get(value, default)
