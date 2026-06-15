"""Tumble verification suite — exercises every feature.

Run:  python3 -m unittest discover -s tests      (from the project root)
  or: python3 tests/test_tumble.py

Covers the Python engine (physics invariants, builders, CLI, SVG) and the JS
mirror (bit-close parity, scene-builder parity) via Node. Node tests skip
gracefully if `node` is not on PATH.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tumble.engine import World, Particle, LineSegment   # noqa: E402
from tumble import scenes, builders                       # noqa: E402
from tumble.render_svg import render                      # noqa: E402

NODE = shutil.which("node")
PARITY = os.path.join(ROOT, "web", "node_parity.js")


def run_node(args, stdin=None):
    return subprocess.run([NODE, PARITY, *args], input=stdin,
                          capture_output=True, text=True, cwd=ROOT)


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


class PhysicsCore(unittest.TestCase):
    def test_free_fall_matches_analytic_verlet(self):
        w = World(width=10000, height=100000, gravity=(0, 980), dt=1 / 60,
                  iterations=1, damping=0.0, restitution=0, friction=0)
        w.add_particle(Particle(5000, 100, 1.0, 5.0))
        a, dt = 980, 1 / 60
        xa = xb = 100.0
        N = 60
        for _ in range(N):
            w.step()
        for _ in range(N):
            xn = 2 * xb - xa + a * dt * dt
            xa, xb = xb, xn
        self.assertAlmostEqual(w.particles[0].y, xb, places=9)

    def test_pendulum_conserves_length(self):
        w = scenes.build("pendulum")
        a, b = w.particles
        rest = w.constraints[0].rest
        worst = 0.0
        for _ in range(1000):
            w.step()
            worst = max(worst, abs(dist(a, b) - rest))
        self.assertLess(worst, rest * 0.001)   # within 0.1%

    def test_rigid_box_keeps_shape(self):
        w = World(iterations=12, damping=0.01, restitution=0.1, friction=0.3)
        idx = builders.box(w, 300, 80, 90, 70, stiffness=1.0)
        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
        rest = [dist(w.particles[i], w.particles[j]) for i, j in edges]
        for _ in range(400):
            w.step()
        err = max(abs(dist(w.particles[i], w.particles[j]) - r)
                  for (i, j), r in zip(edges, rest))
        self.assertLess(err, 0.05)
        # rests on the floor (center = height - radius)
        self.assertLess(abs(max(w.particles[i].y for i in idx)
                            - (w.height - w.particles[0].radius)), 1.0)

    def test_collision_no_overlap(self):
        w = World(width=200, height=400, iterations=8, restitution=0.1,
                  friction=0.2, self_collision=True, damping=0.02)
        w.add_particle(Particle(100, 100, 1.0, 20.0))
        w.add_particle(Particle(105, 150, 1.0, 20.0))
        for _ in range(600):
            w.step()
        a, b = w.particles
        self.assertGreaterEqual(dist(a, b), 40.0 - 0.5)

    def test_ballpit_settles_without_deep_overlap(self):
        w = scenes.build("ballpit")
        for _ in range(600):
            w.step()
        worst = 0.0
        ps = w.particles
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                d = dist(ps[i], ps[j])
                worst = max(worst, (ps[i].radius + ps[j].radius) - d)
        self.assertLess(worst, 4.0)   # only shallow residual overlap

    def test_tearing_reduces_constraints(self):
        w = World(gravity=(0, 2000), tearing=True, tear_strain=0.25, iterations=4)
        builders.cloth(w, 250, 40, 20, 14, spacing=22, pin_top=True,
                       pin_corners_only=True, stiffness=0.4)
        c0 = w.active_constraints()
        for _ in range(300):
            w.step()
        self.assertLess(w.active_constraints(), c0)
        self.assertTrue(w.all_finite())

    def test_no_tear_when_disabled(self):
        w = World(gravity=(0, 2000), tearing=False, iterations=4)
        builders.cloth(w, 250, 40, 20, 14, spacing=22, pin_top=True,
                       pin_corners_only=True, stiffness=0.4)
        c0 = w.active_constraints()
        for _ in range(300):
            w.step()
        self.assertEqual(w.active_constraints(), c0)

    def test_determinism(self):
        hashes = []
        for _ in range(2):
            w = scenes.build("ballpit")
            for _ in range(500):
                w.step()
            hashes.append(w.state_hash())
        self.assertEqual(hashes[0], hashes[1])

    def test_endurance_no_nan(self):
        w = scenes.build("blobs")
        for _ in range(5000):
            w.step()
        self.assertTrue(w.all_finite())

    def test_energy_does_not_explode(self):
        w = World(width=400, height=400, gravity=(0, 0), damping=0.0,
                  restitution=1.0, friction=0.0, self_collision=True, iterations=4)
        for i in range(25):
            p = Particle(40 + (i * 53) % 320, 40 + (i * 97) % 320, 1.0, 9.0)
            p.px = p.x - 3
            p.py = p.y - 2
            w.add_particle(p)
        e0 = w.kinetic_energy()
        peak = e0
        for _ in range(3000):
            w.step()
            peak = max(peak, w.kinetic_energy())
        self.assertLess(peak, e0 * 1.5)
        self.assertTrue(w.all_finite())

    def test_pinned_particle_stays_put(self):
        w = World(gravity=(0, 980))
        i = w.add_particle(Particle(100, 100, 0.0, 6.0))   # pinned
        for _ in range(200):
            w.step()
        self.assertEqual((w.particles[i].x, w.particles[i].y), (100.0, 100.0))

    def test_wind_pushes_horizontally(self):
        w = World(gravity=(0, 0), wind=(300, 0), damping=0.0)
        i = w.add_particle(Particle(100, 100, 1.0, 6.0))
        for _ in range(60):
            w.step()
        self.assertGreater(w.particles[i].x, 100.5)

    def test_segment_obstacle_blocks_fall(self):
        w = World(width=400, height=2000, gravity=(0, 980), iterations=10)
        w.add_segment(LineSegment(50, 300, 350, 300, radius=6.0))
        i = w.add_particle(Particle(200, 50, 1.0, 8.0))
        for _ in range(400):
            w.step()
        # particle should rest on top of the segment, not fall through it
        self.assertLess(w.particles[i].y, 300.0)

    def test_bounds_contain_all_scenes(self):
        for name in scenes.names():
            w = scenes.build(name)
            for _ in range(400):
                w.step()
            for p in w.particles:
                self.assertGreaterEqual(p.x, -0.001)
                self.assertLessEqual(p.x, w.width + 0.001)
                self.assertGreaterEqual(p.y, -0.001)
                self.assertLessEqual(p.y, w.height + 0.001)


class Builders(unittest.TestCase):
    def test_rope_counts(self):
        w = World()
        idx = builders.rope(w, 0, 0, 100, 0, segments=10)
        self.assertEqual(len(idx), 11)
        self.assertEqual(len(w.constraints), 10)
        self.assertTrue(w.particles[0].pinned)        # pin_start default

    def test_cloth_pin_corners(self):
        w = World()
        builders.cloth(w, 0, 0, 5, 5, pin_top=True, pin_corners_only=True)
        pinned = [p for p in w.particles if p.pinned]
        self.assertEqual(len(pinned), 2)

    def test_box_is_rigid_network(self):
        w = World()
        idx = builders.box(w, 100, 100, 50, 40)
        self.assertEqual(len(idx), 4)
        self.assertEqual(len(w.constraints), 6)        # 4 edges + 2 diagonals
        self.assertTrue(all(not c.tearable for c in w.constraints))

    def test_blob_has_hub(self):
        w = World()
        idx = builders.blob(w, 100, 100, 40, n=12)
        self.assertEqual(len(idx), 13)                 # hub + ring


class Serialization(unittest.TestCase):
    def test_round_trip_identity_all_scenes(self):
        for name in scenes.names():
            w = scenes.build(name)
            for _ in range(40):
                w.step()
            w2 = World.from_json(w.to_json())
            self.assertEqual(w.state_hash(), w2.state_hash(), name)


class SvgRenderer(unittest.TestCase):
    def test_render_produces_valid_svg(self):
        w = scenes.build("ballpit")
        for _ in range(150):
            w.step()
        svg = render(w)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertIn("<circle", svg)


class Cli(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, "-m", "tumble", *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_scenes(self):
        r = self._run("scenes")
        self.assertEqual(r.returncode, 0)
        self.assertIn("cloth", r.stdout)

    def test_sim(self):
        r = self._run("sim", "--scene", "rope", "--steps", "50")
        self.assertEqual(r.returncode, 0)
        self.assertIn("finite=True", r.stdout)

    def test_check_passes(self):
        r = self._run("check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ALL OK", r.stdout)

    def test_render_writes_svg(self):
        out = os.path.join(ROOT, "tests", "_tmp_render.svg")
        try:
            r = self._run("render", "--scene", "cloth", "--steps", "30",
                          "--out", out)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(out))
            with open(out) as f:
                self.assertIn("<svg", f.read())
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_unknown_scene_errors(self):
        r = self._run("sim", "--scene", "does-not-exist")
        self.assertNotEqual(r.returncode, 0)


@unittest.skipIf(NODE is None, "node not available")
class JsParity(unittest.TestCase):
    def test_builder_parity_all_scenes(self):
        for name in scenes.names():
            w = scenes.build(name)
            r = run_node(["build", name])
            self.assertEqual(r.returncode, 0, r.stderr)
            jd = json.loads(r.stdout)
            pd = w.to_dict()
            self.assertEqual(len(jd["particles"]), len(pd["particles"]), name)
            self.assertEqual(len(jd["constraints"]), len(pd["constraints"]), name)
            for a, b in zip(jd["particles"], pd["particles"]):
                for k in ("x", "y", "px", "py", "inv_mass", "radius"):
                    self.assertAlmostEqual(a[k], b[k], places=12, msg=name)

    def test_step_parity_all_scenes(self):
        steps = 250
        worst = 0.0
        for name in scenes.names():
            w = scenes.build(name)
            payload = json.dumps(w.to_dict())
            r = run_node(["stepjson", str(steps)], stdin=payload)
            self.assertEqual(r.returncode, 0, r.stderr)
            pos = json.loads(r.stdout)["positions"]
            for _ in range(steps):
                w.step()
            self.assertEqual(len(pos), len(w.particles), name)
            for (x, y, px, py), p in zip(pos, w.particles):
                worst = max(worst, abs(x - p.x), abs(y - p.y),
                            abs(px - p.px), abs(py - p.py))
        # identical operations on IEEE-754 doubles -> expect exact (allow 1e-6)
        self.assertLess(worst, 1e-6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
