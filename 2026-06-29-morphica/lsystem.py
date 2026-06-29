"""
L-System engine: rewriting + turtle-graphics interpreter.

Produces SVG path strings and bounding-box metadata.
Stochastic rules supported: rule value can be a list of (weight, str) pairs.
"""
import math
import random


# ── built-in presets ─────────────────────────────────────────────────────────

PRESETS = {
    "sierpinski": {
        "axiom": "F-G-G",
        "rules": {"F": "F-G+F+G-F", "G": "GG"},
        "angle": 120,
        "iterations": 6,
        "step": 4.0,
        "description": "Sierpinski triangle",
    },
    "koch": {
        "axiom": "F--F--F",
        "rules": {"F": "F+F--F+F"},
        "angle": 60,
        "iterations": 5,
        "step": 5.0,
        "description": "Koch snowflake",
    },
    "dragon": {
        "axiom": "FX",
        "rules": {"X": "X+YF+", "Y": "-FX-Y"},
        "angle": 90,
        "iterations": 12,
        "step": 6.0,
        "description": "Dragon curve",
    },
    "barnsley": {
        "axiom": "X",
        "rules": {
            "X": "F+[[X]-X]-F[-FX]+X",
            "F": "FF",
        },
        "angle": 25,
        "iterations": 6,
        "step": 5.0,
        "description": "Barnsley fern",
    },
    "plant": {
        "axiom": "F",
        "rules": {"F": "F[+F]F[-F][F]"},
        "angle": 25.7,
        "iterations": 5,
        "step": 6.0,
        "description": "Fractal plant",
    },
    "hilbert": {
        "axiom": "A",
        "rules": {
            "A": "-BF+AFA+FB-",
            "B": "+AF-BFB-FA+",
        },
        "angle": 90,
        "iterations": 6,
        "step": 8.0,
        "description": "Hilbert curve",
    },
    "pentigree": {
        "axiom": "F-F-F-F-F",
        "rules": {"F": "F-F++F+F-F-F"},
        "angle": 72,
        "iterations": 4,
        "step": 6.0,
        "description": "Pentigree (pentaflake)",
    },
    "bush": {
        "axiom": "VZFFF",
        "rules": {
            "V": "[+++W][---W]YV",
            "W": "+X[-W]Z",
            "X": "-W[+X]Z",
            "Y": "YZ",
            "Z": "[-FFF][+FFF]F",
        },
        "angle": 20,
        "iterations": 4,  # 5 produces >1M char strings; 4 is still visually rich
        "step": 5.0,
        "description": "Bush / branching structure",
    },
    "stochastic_plant": {
        "axiom": "F",
        "rules": {
            "F": [
                (0.33, "F[+F]F[-F]F"),
                (0.33, "F[+F]F"),
                (0.34, "F[-F]F"),
            ],
        },
        "angle": 25.0,
        "iterations": 5,
        "step": 6.0,
        "description": "Stochastic plant (probabilistic branching)",
    },
}


# ── rewriter ─────────────────────────────────────────────────────────────────

def rewrite(axiom, rules, iterations, rng=None):
    """Apply L-system rules `iterations` times starting from `axiom`."""
    if rng is None:
        rng = random.Random()
    current = axiom
    for _ in range(iterations):
        buf = []
        for ch in current:
            rule = rules.get(ch)
            if rule is None:
                buf.append(ch)
            elif isinstance(rule, list):
                # stochastic: list of (weight, production)
                weights = [w for w, _ in rule]
                prods = [p for _, p in rule]
                total = sum(weights)
                r = rng.random() * total
                cumul = 0.0
                for w, p in zip(weights, prods):
                    cumul += w
                    if r <= cumul:
                        buf.append(p)
                        break
            else:
                buf.append(rule)
        current = "".join(buf)
    return current


# ── turtle interpreter ────────────────────────────────────────────────────────

def turtle_to_paths(
    string,
    angle_deg,
    step,
    start_x=0.0,
    start_y=0.0,
    start_heading=90.0,
):
    """
    Interpret turtle-graphics symbols in `string`.

    Symbols:
        F, G     — draw forward
        f        — move forward (pen up)
        +        — turn left by angle
        -        — turn right by angle
        |        — turn 180°
        [        — push state
        ]        — pop state
        Any other character is ignored.

    Returns:
        paths: list of lists of (x, y) points (each sub-list is one pen-down segment)
        bbox: (min_x, min_y, max_x, max_y)
    """
    angle_rad = math.radians(angle_deg)
    x, y = start_x, start_y
    heading = math.radians(start_heading)
    stack = []
    paths = []
    current_path = [(x, y)]
    pen_down = True

    def flush():
        nonlocal current_path
        if len(current_path) >= 2:
            paths.append(current_path)
        current_path = [(x, y)]

    for ch in string:
        if ch in ("F", "G"):
            nx = x + step * math.cos(heading)
            ny = y - step * math.sin(heading)  # SVG y-down
            if not pen_down:
                flush()
                current_path = [(x, y)]
                pen_down = True
            current_path.append((nx, ny))
            x, y = nx, ny
        elif ch == "f":
            flush()
            x += step * math.cos(heading)
            y -= step * math.sin(heading)
            current_path = [(x, y)]
            pen_down = False
        elif ch == "+":
            heading += angle_rad
        elif ch == "-":
            heading -= angle_rad
        elif ch == "|":
            heading += math.pi
        elif ch == "[":
            stack.append((x, y, heading, pen_down, list(current_path)))
        elif ch == "]":
            if stack:
                flush()
                x, y, heading, pen_down, current_path = stack.pop()
        # else: ignore (variables not used as turtle commands)

    flush()

    # Compute bounding box
    all_pts = [(px, py) for path in paths for (px, py) in path]
    if all_pts:
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        bbox = (min(xs), min(ys), max(xs), max(ys))
    else:
        bbox = (0, 0, 1, 1)

    return paths, bbox


# ── SVG output ───────────────────────────────────────────────────────────────

def paths_to_svg(
    paths,
    bbox,
    width=800,
    height=800,
    stroke="#FFFFFF",
    stroke_width=0.8,
    bg="#111111",
    margin=20,
):
    """Render turtle paths to an SVG string, auto-scaled to fit."""
    bx0, by0, bx1, by1 = bbox
    bw = bx1 - bx0 or 1
    bh = by1 - by0 or 1
    avail_w = width - 2 * margin
    avail_h = height - 2 * margin
    scale = min(avail_w / bw, avail_h / bh)

    def tx(px):
        return margin + (px - bx0) * scale

    def ty(py):
        return margin + (py - by0) * scale

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
    ]
    for path in paths:
        if len(path) < 2:
            continue
        coords = " ".join(f"L{tx(px):.2f},{ty(py):.2f}" for px, py in path[1:])
        d = f"M{tx(path[0][0]):.2f},{ty(path[0][1]):.2f} {coords}"
        lines.append(
            f'<path d="{d}" stroke="{stroke}" stroke-width="{stroke_width}" '
            f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    lines.append("</svg>")
    return "\n".join(lines)


# ── PNG rasteriser ────────────────────────────────────────────────────────────

def paths_to_pixels(paths, bbox, width=800, height=800, margin=20, bg=(17, 17, 17)):
    """Rasterise paths into a flat list of (r,g,b) tuples using Bresenham's line."""
    pixels = [bg] * (width * height)
    bx0, by0, bx1, by1 = bbox
    bw = bx1 - bx0 or 1
    bh = by1 - by0 or 1
    avail_w = width - 2 * margin
    avail_h = height - 2 * margin
    scale = min(avail_w / bw, avail_h / bh)

    def tx(px):
        return int(margin + (px - bx0) * scale)

    def ty(py):
        return int(margin + (py - by0) * scale)

    def draw_line(x0, y0, x1, y1, color=(255, 255, 255)):
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            if 0 <= x0 < width and 0 <= y0 < height:
                pixels[y0 * width + x0] = color
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    for path in paths:
        for i in range(1, len(path)):
            x0, y0 = path[i - 1]
            x1, y1 = path[i]
            draw_line(tx(x0), ty(y0), tx(x1), ty(y1))

    return pixels


# ── public API ────────────────────────────────────────────────────────────────

def render_lsystem(
    name_or_config,
    iterations=None,
    step=None,
    width=800,
    height=800,
    output_format="svg",
    stroke="#00CFFF",
    bg="#111111",
    seed=None,
):
    """
    Render an L-system to SVG string or list of RGB pixels.

    name_or_config: preset name string or dict with keys
        axiom, rules, angle, [iterations], [step]
    output_format: "svg" | "pixels"
    """
    rng = random.Random(seed)
    if isinstance(name_or_config, str):
        if name_or_config not in PRESETS:
            raise ValueError(f"Unknown L-system preset '{name_or_config}'. "
                             f"Available: {sorted(PRESETS.keys())}")
        cfg = dict(PRESETS[name_or_config])
    else:
        cfg = dict(name_or_config)

    n_iter = iterations if iterations is not None else cfg.get("iterations", 4)
    st = step if step is not None else cfg.get("step", 5.0)

    string = rewrite(cfg["axiom"], cfg["rules"], n_iter, rng=rng)
    paths, bbox = turtle_to_paths(string, cfg["angle"], st)

    if output_format == "svg":
        return paths_to_svg(paths, bbox, width=width, height=height,
                             stroke=stroke, bg=bg)
    elif output_format == "pixels":
        bg_rgb = _parse_hex_color(bg)
        return paths_to_pixels(paths, bbox, width=width, height=height, bg=bg_rgb), width, height
    else:
        raise ValueError(f"Unknown format '{output_format}'")


def _parse_hex_color(hex_str):
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
