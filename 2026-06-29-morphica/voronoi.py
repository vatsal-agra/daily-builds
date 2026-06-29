"""
Voronoi diagram (Fortune's sweep-line algorithm) + Lloyd relaxation + stippling.

Fortune's algorithm produces exact Voronoi diagrams in O(n log n).
Lloyd relaxation iteratively moves each site to the centroid of its cell,
producing a centroidal Voronoi tessellation (uniform spacing).
Weighted stippling varies point density to match a target luminance field.
"""
import math
import heapq
import random as _random


# ─────────────────────────────────────────────────────────────────────────────
# Fortune's sweep-line Voronoi
# ─────────────────────────────────────────────────────────────────────────────

class _Site:
    __slots__ = ("x", "y", "idx")
    def __init__(self, x, y, idx):
        self.x = x; self.y = y; self.idx = idx

class _Arc:
    __slots__ = ("site", "prev", "next", "ev")
    def __init__(self, site):
        self.site = site
        self.prev = self.next = self.ev = None

class _Event:
    __slots__ = ("x", "y", "valid", "arc", "is_circle")
    def __init__(self, x, y, arc=None, is_circle=False):
        self.x = x; self.y = y
        self.valid = True
        self.arc = arc
        self.is_circle = is_circle
    def __lt__(self, other):
        return (self.x, self.y) < (other.x, other.y)


def _parabola_x(site, sweep, query_y):
    """x-coordinate on the parabola from site at the given sweep line and y."""
    dp = site.x - sweep
    if abs(dp) < 1e-12:
        return float("inf")
    return ((query_y - site.y) ** 2 / (2 * dp)) + (site.x + sweep) / 2


def fortune_voronoi(points, width, height):
    """
    Compute 2-D Voronoi diagram for a list of (x, y) points.

    Returns:
        vertices: list of (x, y) Voronoi vertex positions
        ridges:   list of (v0, v1, s0, s1) — two vertex indices and the two
                  site indices sharing this ridge (-1 = boundary)
        regions:  list of lists of vertex indices per site (may be empty for
                  sites with only boundary edges)
    """
    n = len(points)
    if n == 0:
        return [], [], []
    if n == 1:
        return [], [], [[]]

    sites = sorted(
        [_Site(p[0], p[1], i) for i, p in enumerate(points)],
        key=lambda s: (s.x, s.y),
    )

    vertices = []
    edges = []           # list of [v0, v1, s0, s1]
    half_edges = {}      # (s0, s1) -> edge index

    heap = []
    for s in sites:
        heapq.heappush(heap, _Event(s.x, s.y))

    beach = None         # doubly-linked list of arcs
    site_idx = 0
    pending_sites = list(sites)
    pending_sites.sort(key=lambda s: s.x)
    si = 0

    def get_y(arc, sweep):
        """y-coordinate of intersection between arc.prev and arc parabola."""
        if arc.prev is None:
            return float("-inf")
        return _parabola_x(arc.prev.site, sweep, arc.site.y)

    def circle_event(arc, sweep):
        """Compute and schedule the circle event for arc if it converges."""
        if arc.prev is None or arc.next is None:
            return
        a, b, c = arc.prev.site, arc.site, arc.next.site
        # circumcentre
        ax, ay = a.x, a.y
        bx, by = b.x, b.y
        cx, cy = c.x, c.y
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-10:
            return
        ux = ((ax*ax + ay*ay) * (by - cy) + (bx*bx + by*by) * (cy - ay) +
              (cx*cx + cy*cy) * (ay - by)) / d
        uy = ((ax*ax + ay*ay) * (cx - bx) + (bx*bx + by*by) * (ax - cx) +
              (cx*cx + cy*cy) * (bx - ax)) / d
        r = math.hypot(ux - ax, uy - ay)
        ev_x = ux + r
        if ev_x < sweep - 1e-10:
            return
        ev = _Event(ev_x, uy, arc=arc, is_circle=True)
        arc.ev = ev
        heapq.heappush(heap, ev)

    def add_edge(s0, s1):
        key = (min(s0, s1), max(s0, s1))
        if key not in half_edges:
            half_edges[key] = len(edges)
            edges.append([-1, -1, s0, s1])
        return half_edges[key]

    def complete_edge(s0, s1, vx, vy):
        key = (min(s0, s1), max(s0, s1))
        if key not in half_edges:
            return
        eid = half_edges[key]
        vid = len(vertices)
        vertices.append((vx, vy))
        e = edges[eid]
        if e[0] == -1:
            e[0] = vid
        else:
            e[1] = vid

    # Process events
    while heap:
        ev = heapq.heappop(heap)
        if not ev.valid:
            continue
        sweep = ev.x

        if not ev.is_circle:
            # Site event
            s = pending_sites[si]; si += 1
            if beach is None:
                beach = _Arc(s)
                continue
            # Find arc on beach line above this site
            cur = beach
            while cur.next:
                # Check if site.y is above the intersection
                # between cur and cur.next
                iy = get_y(cur.next, sweep)
                if s.y < iy:
                    break
                cur = cur.next

            # Split cur into cur | new | cur2
            new_arc = _Arc(s)
            cur2 = _Arc(cur.site)
            cur2.next = cur.next
            if cur.next:
                cur.next.prev = cur2
            cur.next = new_arc
            new_arc.prev = cur
            new_arc.next = cur2
            cur2.prev = new_arc

            add_edge(cur.site.idx, s.idx)
            add_edge(s.idx, cur.site.idx)

            # Invalidate old circle events
            if cur.ev:
                cur.ev.valid = False
                cur.ev = None
            if cur2.ev:
                cur2.ev.valid = False
                cur2.ev = None

            circle_event(cur, sweep)
            circle_event(cur2, sweep)

        else:
            # Circle event — remove arc
            arc = ev.arc
            if arc.ev != ev:
                continue

            vx, vy = ev.y, ev.y    # reuse ev.y as circle centre y
            # Recompute properly from the three sites
            a = arc.prev.site if arc.prev else None
            b = arc.site
            c = arc.next.site if arc.next else None
            if a and c:
                ax, ay = a.x, a.y
                bx, by = b.x, b.y
                cx2, cy2 = c.x, c.y
                denom = 2*(ax*(by-cy2)+bx*(cy2-ay)+cx2*(ay-by))
                if abs(denom) > 1e-10:
                    vx = ((ax*ax+ay*ay)*(by-cy2)+(bx*bx+by*by)*(cy2-ay)+
                          (cx2*cx2+cy2*cy2)*(ay-by)) / denom
                    vy = ((ax*ax+ay*ay)*(cx2-bx)+(bx*bx+by*by)*(ax-cx2)+
                          (cx2*cx2+cy2*cy2)*(bx-ax)) / denom

            complete_edge(arc.prev.site.idx if arc.prev else -1, b.idx, vx, vy)
            complete_edge(b.idx, arc.next.site.idx if arc.next else -1, vx, vy)

            if arc.prev:
                arc.prev.next = arc.next
            if arc.next:
                arc.next.prev = arc.prev

            if arc.prev and arc.prev.ev:
                arc.prev.ev.valid = False
                arc.prev.ev = None
            if arc.next and arc.next.ev:
                arc.next.ev.valid = False
                arc.next.ev = None

            if arc.prev:
                circle_event(arc.prev, sweep)
            if arc.next:
                circle_event(arc.next, sweep)

    return vertices, edges, []


# ─────────────────────────────────────────────────────────────────────────────
# Simple fallback: brute-force nearest-neighbour Voronoi (always correct)
# ─────────────────────────────────────────────────────────────────────────────

def brute_voronoi_pixels(points, width, height, palette_fn=None, bg=(10, 10, 10)):
    """
    Rasterise Voronoi diagram by nearest-site lookup (O(w*h*n), exact, simple).
    Each cell gets a distinct colour.
    Returns flat list of (r,g,b), width, height.
    """
    n = len(points)
    if n == 0:
        return [bg] * (width * height), width, height

    from palette import hsv_cycle_palette
    colors = hsv_cycle_palette(n)

    pixels = []
    for row in range(height):
        y = row / height
        for col in range(width):
            x = col / width
            best = 0
            best_d = float("inf")
            for i, (px, py) in enumerate(points):
                d = (x - px) ** 2 + (y - py) ** 2
                if d < best_d:
                    best_d = d
                    best = i
            pixels.append(colors[best])
    return pixels, width, height


# ─────────────────────────────────────────────────────────────────────────────
# Lloyd relaxation
# ─────────────────────────────────────────────────────────────────────────────

def lloyd_relax(points, width, height, iterations=10):
    """
    Iteratively move each site to the centroid of its Voronoi cell
    (brute-force, works for moderate n).

    Returns relaxed list of (x, y) in [0,1]x[0,1].
    """
    pts = list(points)
    for _ in range(iterations):
        sums_x = [0.0] * len(pts)
        sums_y = [0.0] * len(pts)
        counts = [0] * len(pts)
        # sample on a grid
        grid_res = min(200, max(50, int(math.sqrt(width * height / len(pts))) * 2))
        for row in range(grid_res):
            y = (row + 0.5) / grid_res
            for col in range(grid_res):
                x = (col + 0.5) / grid_res
                best = 0
                best_d = float("inf")
                for i, (px, py) in enumerate(pts):
                    d = (x - px) ** 2 + (y - py) ** 2
                    if d < best_d:
                        best_d = d
                        best = i
                sums_x[best] += x
                sums_y[best] += y
                counts[best] += 1
        pts = [
            (sums_x[i] / counts[i], sums_y[i] / counts[i]) if counts[i] > 0 else pts[i]
            for i in range(len(pts))
        ]
    return pts


# ─────────────────────────────────────────────────────────────────────────────
# Weighted stippling
# ─────────────────────────────────────────────────────────────────────────────

def stipple(
    n_points,
    width,
    height,
    weight_field=None,
    lloyd_iters=5,
    seed=None,
    palette_fn=None,
):
    """
    Generate n_points stipple dots whose density follows weight_field.

    weight_field: flat list of floats in [0,1] (row-major, height*width).
                  None → uniform.  Higher values = more dots.
    Returns (pixels, width, height).
    """
    rng = _random.Random(seed)

    if weight_field is None:
        # Uniform
        pts = [(rng.random(), rng.random()) for _ in range(n_points)]
    else:
        # Rejection sampling from weight field
        wf = weight_field
        wmax = max(wf) or 1.0
        pts = []
        attempts = 0
        max_attempts = n_points * 200
        fw = width   # field width
        fh = height  # field height
        while len(pts) < n_points and attempts < max_attempts:
            x = rng.random()
            y = rng.random()
            col = min(int(x * fw), fw - 1)
            row = min(int(y * fh), fh - 1)
            w = wf[row * fw + col] / wmax
            if rng.random() < w:
                pts.append((x, y))
            attempts += 1
        # Fill remainder if not enough accepted
        while len(pts) < n_points:
            pts.append((rng.random(), rng.random()))

    # Lloyd relaxation
    pts = lloyd_relax(pts, width, height, iterations=lloyd_iters, rng=rng)

    # Rasterise: draw small circles for each stipple dot
    pixels = [(10, 10, 10)] * (width * height)

    from palette import hsv_cycle_palette
    colors = hsv_cycle_palette(max(n_points, 1), saturation=0.7, value=0.95)

    for i, (x, y) in enumerate(pts):
        cx = int(x * width)
        cy = int(y * height)
        color = colors[i % len(colors)]
        r = 2
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    px_ = cx + dx
                    py_ = cy + dy
                    if 0 <= px_ < width and 0 <= py_ < height:
                        pixels[py_ * width + px_] = color

    return pixels, width, height, pts


# ─────────────────────────────────────────────────────────────────────────────
# Voronoi SVG output (using brute-force cell colouring)
# ─────────────────────────────────────────────────────────────────────────────

def voronoi_to_svg(points, width=800, height=800, bg="#111111"):
    """
    Render Voronoi diagram to SVG using rasterised approach
    (each cell coloured by distinct hue, boundary drawn as thin white lines).
    """
    from palette import hsv_cycle_palette
    n = len(points)
    colors = hsv_cycle_palette(n)

    # Build cell map at reduced resolution for edge detection
    res = min(width, height, 400)
    scale_x = res / width * width
    scale_y = res / height * height

    cell = []
    for row in range(res):
        y = row / res
        for col in range(res):
            x = col / res
            best = 0
            best_d = float("inf")
            for i, (px, py) in enumerate(points):
                d = (x - px) ** 2 + (y - py) ** 2
                if d < best_d:
                    best_d = d
                    best = i
            cell.append(best)

    # Build SVG rects at 1×1 pixel (slow but correct for SVG)
    # Instead, output coloured pixel data embedded as SVG image
    # — just build an SVG with dots for the sites and polyline borders
    # Cap SVG resolution to avoid generating >10K elements
    svg_res = min(res, 100)
    svg_cell = []
    for row in range(svg_res):
        y = row / svg_res
        for col in range(svg_res):
            x = col / svg_res
            best = 0
            best_d = float("inf")
            for i, (px, py) in enumerate(points):
                d = (x - px) ** 2 + (y - py) ** 2
                if d < best_d:
                    best_d = d
                    best = i
            svg_cell.append(best)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        f'<rect width="{width}" height="{height}" fill="{bg}"/>',
    ]

    # Draw cell-coloured rectangles (downsampled)
    pixel_w = width / svg_res
    pixel_h = height / svg_res
    for row in range(svg_res):
        for col in range(svg_res):
            site_i = svg_cell[row * svg_res + col]
            r, g, b = colors[site_i]
            lines.append(
                f'<rect x="{col*pixel_w:.1f}" y="{row*pixel_h:.1f}" '
                f'width="{pixel_w+0.5:.1f}" height="{pixel_h+0.5:.1f}" '
                f'fill="rgb({r},{g},{b})"/>'
            )

    # Draw edges (neighbours with different cells)
    for row in range(svg_res - 1):
        for col in range(svg_res - 1):
            c = svg_cell[row * svg_res + col]
            cr = svg_cell[row * svg_res + col + 1]
            cd = svg_cell[(row + 1) * svg_res + col]
            if c != cr:
                x = (col + 1) * pixel_w
                lines.append(
                    f'<line x1="{x:.1f}" y1="{row*pixel_h:.1f}" '
                    f'x2="{x:.1f}" y2="{(row+1)*pixel_h:.1f}" '
                    f'stroke="white" stroke-width="1"/>'
                )
            if c != cd:
                y = (row + 1) * pixel_h
                lines.append(
                    f'<line x1="{col*pixel_w:.1f}" y1="{y:.1f}" '
                    f'x2="{(col+1)*pixel_w:.1f}" y2="{y:.1f}" '
                    f'stroke="white" stroke-width="1"/>'
                )

    # Draw site dots
    for i, (px, py) in enumerate(points):
        cx = px * width
        cy = py * height
        lines.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" '
            f'fill="white" opacity="0.9"/>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def render_voronoi(
    n_points=80,
    width=800,
    height=800,
    lloyd_iterations=5,
    seed=None,
    output_format="svg",
    weight_field=None,
    stipple_mode=False,
):
    """
    Render a Voronoi diagram (or stipple art).

    output_format: "svg" | "pixels"
    stipple_mode: if True, render as weighted stipple dots instead of filled cells
    """
    rng = _random.Random(seed)
    points = [(rng.random(), rng.random()) for _ in range(n_points)]
    points = lloyd_relax(points, width, height, iterations=lloyd_iterations)

    if stipple_mode:
        pixels, w, h, _ = stipple(
            n_points, width, height,
            weight_field=weight_field,
            lloyd_iters=lloyd_iterations,
            seed=seed,
        )
        return pixels, w, h

    if output_format == "svg":
        return voronoi_to_svg(points, width=width, height=height)
    elif output_format == "pixels":
        pixels, w, h = brute_voronoi_pixels(points, width, height)
        return pixels, w, h
    else:
        raise ValueError(f"Unknown format '{output_format}'")
