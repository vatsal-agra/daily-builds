"""Named, deterministic preset scenes shared by the CLI, tests and (mirrored) the
JS playground. Each builder returns a fully-populated World."""
from .engine import World, LineSegment, Particle
from . import builders

W, H = 900.0, 600.0


def scene_rope():
    w = World(width=W, height=H, iterations=10, damping=0.02)
    builders.rope(w, 250, 40, 650, 40, segments=18, pin_start=True, pin_end=True,
                  stiffness=1.0)
    return w


def scene_pendulum():
    """A pinned anchor + a single bob on a stiff link — the length-conservation test."""
    w = World(width=W, height=H, iterations=30, damping=0.0, restitution=0.0)
    builders.rope(w, 450, 80, 650, 80, segments=1, pin_start=True, pin_end=False,
                  radius=12.0, stiffness=1.0, mass=1.0)
    return w


def scene_cloth():
    w = World(width=W, height=H, iterations=8, damping=0.02, wind=(60.0, 0.0),
              tearing=True, tear_strain=0.8)
    builders.cloth(w, 230, 50, cols=22, rows=15, spacing=20.0, pin_top=True,
                   stiffness=0.9)
    return w


def scene_curtain():
    w = World(width=W, height=H, iterations=10, damping=0.02, tearing=True,
              tear_strain=0.7)
    builders.cloth(w, 200, 60, cols=24, rows=14, spacing=22.0, pin_top=True,
                   pin_corners_only=True, stiffness=0.9)
    return w


def scene_ballpit():
    """Many free circles with self-collision on — the collision + parity workhorse."""
    w = World(width=W, height=H, iterations=6, damping=0.01, restitution=0.35,
              friction=0.08, self_collision=True, cell_size=44.0)
    # deterministic pseudo-random scatter (no RNG dependency across languages)
    seed = 1234567
    n = 60
    for k in range(n):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        x = 80.0 + (seed % 740)
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        y = 40.0 + (seed % 260)
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        r = 10.0 + (seed % 12)
        w.add_particle(Particle(float(x), float(y), 1.0, float(r)))
    return w


def scene_boxes():
    w = World(width=W, height=H, iterations=12, damping=0.01, restitution=0.1,
              friction=0.2)
    builders.box(w, 300, 120, 90, 70, vx=20.0)
    builders.box(w, 520, 80, 70, 70)
    builders.box(w, 680, 150, 110, 60, vx=-15.0)
    return w


def scene_blobs():
    w = World(width=W, height=H, iterations=10, damping=0.02, restitution=0.2,
              friction=0.1, self_collision=True, cell_size=60.0)
    builders.blob(w, 350, 120, 55, n=16, vx=10.0)
    builders.blob(w, 560, 90, 45, n=14, vx=-10.0)
    return w


def scene_obstacles():
    """A rope + cloth raining onto angled static line obstacles."""
    w = World(width=W, height=H, iterations=10, damping=0.02)
    builders.cloth(w, 280, 40, cols=16, rows=10, spacing=22.0, pin_top=False,
                   stiffness=0.9)
    w.add_segment(LineSegment(120, 360, 460, 460, radius=6.0))
    w.add_segment(LineSegment(780, 360, 460, 520, radius=6.0))
    w.add_segment(LineSegment(300, 540, 600, 540, radius=6.0))
    return w


SCENES = {
    "rope": scene_rope,
    "pendulum": scene_pendulum,
    "cloth": scene_cloth,
    "curtain": scene_curtain,
    "ballpit": scene_ballpit,
    "boxes": scene_boxes,
    "blobs": scene_blobs,
    "obstacles": scene_obstacles,
}


def names():
    return list(SCENES.keys())


def build(name):
    if name not in SCENES:
        raise KeyError("unknown scene %r; choose from %s" % (name, ", ".join(names())))
    return SCENES[name]()
