"""Headless SVG snapshot of a World — no browser required.

Constraints are coloured by stress (current length vs rest), which makes ropes,
cloth and tearing visually legible in a static image.
"""
import math


def _stress_color(stress):
    """stress in roughly [-1, 1+]: blue (slack) -> grey (rest) -> red (taut)."""
    s = max(-1.0, min(1.5, stress))
    if s >= 0.0:
        t = min(1.0, s / 1.0)
        r = int(120 + 135 * t)
        g = int(120 - 90 * t)
        b = int(120 - 90 * t)
    else:
        t = min(1.0, -s)
        r = int(120 - 60 * t)
        g = int(120 - 20 * t)
        b = int(120 + 100 * t)
    return "#%02x%02x%02x" % (r, g, b)


def render(world, show_particles=True, bg="#0d1117"):
    w = world.width
    h = world.height
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%g" height="%g" '
             'viewBox="0 0 %g %g">' % (w, h, w, h)]
    parts.append('<rect width="%g" height="%g" fill="%s"/>' % (w, h, bg))

    # static segments
    for s in world.segments:
        parts.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#8b949e" '
                     'stroke-width="%g" stroke-linecap="round"/>'
                     % (s.ax, s.ay, s.bx, s.by, max(2.0, s.radius * 2)))

    # constraints, coloured by stress
    ps = world.particles
    for c in world.constraints:
        if not c.active:
            continue
        a = ps[c.i]; b = ps[c.j]
        dx = b.x - a.x; dy = b.y - a.y
        dist = math.sqrt(dx * dx + dy * dy)
        stress = (dist - c.rest) / c.rest if c.rest > 0 else 0.0
        parts.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" '
                     'stroke-width="2"/>'
                     % (a.x, a.y, b.x, b.y, _stress_color(stress)))

    # particles
    if show_particles:
        for p in ps:
            color = "#f0883e" if p.inv_mass == 0.0 else "#58a6ff"
            parts.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s"/>'
                         % (p.x, p.y, p.radius, color))

    parts.append('</svg>')
    return "\n".join(parts)
