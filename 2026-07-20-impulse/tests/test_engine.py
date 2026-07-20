"""
Unit tests for engine.py — the physics core.

Run with: python3 -m unittest tests.test_engine -v
(or just run tests/test_engine.py directly; it adds the repo root to
sys.path so `import engine` works either way)
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine as E


class TestVec2(unittest.TestCase):
    def test_arithmetic(self):
        a = E.Vec2(1, 2)
        b = E.Vec2(3, 4)
        self.assertEqual((a + b).to_tuple(), (4, 6))
        self.assertEqual((a - b).to_tuple(), (-2, -2))
        self.assertEqual((a * 2).to_tuple(), (2, 4))
        self.assertEqual((-a).to_tuple(), (-1, -2))

    def test_dot_and_length(self):
        a = E.Vec2(3, 4)
        self.assertAlmostEqual(a.length(), 5.0)
        self.assertAlmostEqual(a.dot(a), 25.0)

    def test_normalized(self):
        a = E.Vec2(3, 4)
        n = a.normalized()
        self.assertAlmostEqual(n.length(), 1.0)
        self.assertAlmostEqual(n.x, 0.6)
        self.assertAlmostEqual(n.y, 0.8)

    def test_normalized_zero_vector_is_safe(self):
        z = E.Vec2(0, 0).normalized()
        self.assertEqual(z.to_tuple(), (0.0, 0.0))

    def test_rotated_quarter_turn(self):
        v = E.Vec2(1, 0).rotated(math.pi / 2)
        self.assertAlmostEqual(v.x, 0.0, places=9)
        self.assertAlmostEqual(v.y, 1.0, places=9)

    def test_cross_products(self):
        a, b = E.Vec2(1, 0), E.Vec2(0, 1)
        self.assertAlmostEqual(E.cross_vv(a, b), 1.0)
        self.assertAlmostEqual(E.cross_vv(b, a), -1.0)


class TestMassProperties(unittest.TestCase):
    def test_circle_mass_and_inertia(self):
        c = E.Circle(10)
        mass, inertia = c.mass_data(density=1.0)
        self.assertAlmostEqual(mass, math.pi * 100, places=6)
        self.assertAlmostEqual(inertia, mass * 100 / 2.0, places=6)

    def test_box_mass_matches_area(self):
        box = E.Box(10, 20)
        mass, inertia = box.mass_data(density=2.0)
        self.assertAlmostEqual(mass, 2.0 * 10 * 20, places=6)
        self.assertGreater(inertia, 0)

    def test_box_is_recentered_on_centroid(self):
        # an off-center vertex list should still produce a body whose local
        # vertices are centered on (0,0) -- the constructor recenters them
        verts = [E.Vec2(0, 0), E.Vec2(10, 0), E.Vec2(10, 10), E.Vec2(0, 10)]
        poly = E.Polygon(verts)
        cx = sum(v.x for v in poly.vertices) / 4
        cy = sum(v.y for v in poly.vertices) / 4
        self.assertAlmostEqual(cx, 0.0, places=6)
        self.assertAlmostEqual(cy, 0.0, places=6)

    def test_degenerate_shapes_rejected(self):
        with self.assertRaises(ValueError):
            E.Circle(0)
        with self.assertRaises(ValueError):
            E.Circle(-5)
        with self.assertRaises(ValueError):
            E.Polygon([E.Vec2(0, 0), E.Vec2(1, 0)])  # only 2 points


class TestIntegration(unittest.TestCase):
    def test_free_fall_matches_kinematics(self):
        w = E.World(gravity=(0, 500))
        b = E.Body(E.Circle(10), (0, 0), linear_damping=0.0, angular_damping=0.0)
        w.add_body(b)
        dt = 1 / 120
        steps = 120
        for _ in range(steps):
            w.step(dt)
        t = steps * dt
        # semi-implicit Euler: v(t) = g*t exactly; y(t) = sum g*dt*i*dt slightly
        # differs from continuous 0.5*g*t^2, so allow a small tolerance
        expected_v = 500 * t
        self.assertAlmostEqual(b.velocity.y, expected_v, delta=1.0)
        expected_y_continuous = 0.5 * 500 * t * t
        self.assertAlmostEqual(b.position.y, expected_y_continuous, delta=15.0)

    def test_static_body_never_moves(self):
        w = E.World(gravity=(0, 500))
        b = E.Body(E.Circle(10), (100, 100), static=True)
        w.add_body(b)
        for _ in range(300):
            w.step(1 / 120)
        self.assertEqual(b.position.to_tuple(), (100.0, 100.0))

    def test_zero_gravity_body_drifts_at_constant_velocity(self):
        w = E.World(gravity=(0, 0))
        b = E.Body(E.Circle(10), (0, 0), linear_damping=0.0)
        b.velocity = E.Vec2(50, 0)
        w.add_body(b)
        for _ in range(120):
            w.step(1 / 120)
        self.assertAlmostEqual(b.position.x, 50.0, delta=0.5)
        self.assertAlmostEqual(b.position.y, 0.0, delta=0.01)


class TestCollisions(unittest.TestCase):
    def test_circle_circle_no_overlap(self):
        a = E.Body(E.Circle(10), (0, 0))
        b = E.Body(E.Circle(10), (30, 0))
        self.assertIsNone(E.collide(a, b))

    def test_circle_circle_overlap(self):
        a = E.Body(E.Circle(10), (0, 0))
        b = E.Body(E.Circle(10), (15, 0))
        m = E.collide(a, b)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m.penetrations[0], 5.0)
        self.assertAlmostEqual(m.normal.x, 1.0)

    def test_box_on_box_manifold_has_two_points_at_correct_face(self):
        ground = E.Body(E.Box(400, 40), (200, 580), static=True)
        box = E.Body(E.Box(50, 50), (200, 550))  # overlapping by 10px
        m = E.collide(box, ground)
        self.assertIsNotNone(m)
        self.assertEqual(len(m.points), 2)
        self.assertAlmostEqual(m.normal.y, 1.0, places=6)
        for p in m.points:
            self.assertAlmostEqual(p.y, 560.0, places=6)  # ground's top face
        for pen in m.penetrations:
            self.assertAlmostEqual(pen, 15.0, places=6)

    def test_circle_on_box_face_region(self):
        box = E.Body(E.Box(100, 20), (0, 0), static=True)
        ball = E.Body(E.Circle(10), (0, -15))  # resting on top face, 5px overlap
        m = E.collide(ball, box)
        self.assertIsNotNone(m)
        # Manifold.normal points from body_a to body_b (here: ball -> box);
        # box sits below the ball at larger y, so the normal points +y.
        self.assertAlmostEqual(m.normal.y, 1.0, places=6)
        self.assertAlmostEqual(m.penetrations[0], 5.0, places=6)

    def test_circle_on_box_corner_region(self):
        box = E.Body(E.Box(100, 20), (0, 0), static=True)
        # positioned diagonally off the top-right corner
        corner = E.Vec2(50, -10)
        ball_pos = corner + E.Vec2(1, -1).normalized() * 8  # 2px overlap (radius 10)
        ball = E.Body(E.Circle(10), ball_pos)
        m = E.collide(ball, box)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m.penetrations[0], 2.0, places=3)

    def test_box_resting_on_ground_settles_without_sinking_or_tipping(self):
        w = E.World(gravity=(0, 500))
        ground = E.Body(E.Box(800, 40), (400, 580), static=True, friction=0.5)
        w.add_body(ground)
        box = E.Body(E.Box(50, 50), (400, 100), restitution=0.1, friction=0.5)
        w.add_body(box)
        for _ in range(600):
            w.step(1 / 120)
        self.assertAlmostEqual(box.position.y, 535.0, delta=2.0)
        self.assertAlmostEqual(box.velocity.y, 0.0, delta=5.0)
        self.assertAlmostEqual(box.angle, 0.0, delta=0.01)

    def test_box_stack_is_stable(self):
        w = E.World(gravity=(0, 500))
        ground = E.Body(E.Box(400, 40), (200, 580), static=True, friction=0.6)
        w.add_body(ground)
        boxes = [E.Body(E.Box(50, 50), (200, 560 - i * 52), friction=0.6, restitution=0.05)
                 for i in range(5)]
        for b in boxes:
            w.add_body(b)
        for _ in range(1000):
            w.step(1 / 120)
        for i, b in enumerate(boxes):
            self.assertAlmostEqual(b.position.x, 200, delta=15.0, msg=f"box {i} slid sideways")
            self.assertLess(abs(b.angle), 0.05, msg=f"box {i} tipped over")


class TestRestitution(unittest.TestCase):
    def _drop_and_get_bounce_ratio(self, restitution):
        w = E.World(gravity=(0, 500))
        # Effective restitution is max(a, b) -- the ground must also be set
        # to the target value, or its 0.3 default silently dominates.
        ground = E.Body(E.Box(800, 40), (400, 580), static=True, friction=0.0,
                         restitution=restitution)
        w.add_body(ground)
        ball = E.Body(E.Circle(20), (400, 300), restitution=restitution, friction=0.0)
        w.add_body(ball)
        impact_speed = None
        rebound_speed = None
        for _ in range(400):
            prev_vy = ball.velocity.y
            w.step(1 / 120)
            if prev_vy > 0 and ball.velocity.y <= 0 and impact_speed is None:
                impact_speed = prev_vy
                rebound_speed = -ball.velocity.y
        return impact_speed, rebound_speed

    def test_inelastic_barely_bounces(self):
        impact, rebound = self._drop_and_get_bounce_ratio(0.0)
        self.assertIsNotNone(impact)
        self.assertLess(rebound, impact * 0.15)

    def test_partial_restitution_bounces_proportionally(self):
        impact, rebound = self._drop_and_get_bounce_ratio(0.5)
        self.assertIsNotNone(impact)
        self.assertAlmostEqual(rebound / impact, 0.5, delta=0.15)

    def test_near_elastic_bounces_almost_as_high(self):
        impact, rebound = self._drop_and_get_bounce_ratio(0.95)
        self.assertIsNotNone(impact)
        self.assertGreater(rebound / impact, 0.8)


class TestFriction(unittest.TestCase):
    def test_high_friction_box_does_not_slide_on_flat_ground(self):
        w = E.World(gravity=(0, 500))
        ground = E.Body(E.Box(800, 40), (400, 580), static=True, friction=1.0)
        w.add_body(ground)
        box = E.Body(E.Box(50, 50), (400, 100), friction=1.0, restitution=0.0)
        box.velocity = E.Vec2(80, 0)  # sliding horizontally as it lands
        w.add_body(box)
        for _ in range(300):
            w.step(1 / 120)
        # high friction should have killed most of the horizontal slide
        self.assertLess(abs(box.velocity.x), 15.0)

    def test_zero_friction_box_keeps_sliding(self):
        w = E.World(gravity=(0, 500))
        ground = E.Body(E.Box(800, 40), (400, 580), static=True, friction=0.0)
        w.add_body(ground)
        box = E.Body(E.Box(50, 50), (400, 100), friction=0.0, restitution=0.0)
        box.velocity = E.Vec2(80, 0)
        w.add_body(box)
        for _ in range(300):
            w.step(1 / 120)
        # frictionless: horizontal speed should barely change
        self.assertAlmostEqual(box.velocity.x, 80.0, delta=5.0)


class TestJoints(unittest.TestCase):
    def test_distance_joint_pendulum_keeps_constant_length(self):
        w = E.World(gravity=(0, 500))
        anchor = E.Vec2(400, 100)
        bob = E.Body(E.Circle(10), (400, 300), restitution=0.0, friction=0.0)
        bob.velocity = E.Vec2(150, 0)
        w.add_body(bob)
        w.add_joint(E.DistanceJoint(bob, (0, 0), None, anchor.to_tuple()))
        dists = []
        for _ in range(2000):
            w.step(1 / 120)
            dists.append((bob.position - anchor).length())
        self.assertAlmostEqual(max(dists), 200.0, delta=2.0)
        self.assertAlmostEqual(min(dists), 200.0, delta=2.0)

    def test_pin_joint_holds_physical_pendulum_anchor_fixed(self):
        pivot = E.Vec2(400, 100)
        theta = math.radians(30)
        local_anchor = E.Vec2(0, -60)
        start_pos = pivot - local_anchor.rotated(theta)
        w = E.World(gravity=(0, 500))
        rod = E.Body(E.Box(16, 120), start_pos, angle=theta, friction=0.0,
                     angular_damping=0.0, linear_damping=0.0)
        w.add_body(rod)
        w.add_joint(E.PinJoint(rod, (0, -60), None, pivot.to_tuple()))
        max_drift = 0.0
        for _ in range(3000):
            w.step(1 / 120)
            world_anchor = rod.position + local_anchor.rotated(rod.angle)
            max_drift = max(max_drift, (world_anchor - pivot).length())
        self.assertLess(max_drift, 1.0)

    def test_spring_joint_settles_at_hookes_law_equilibrium(self):
        w = E.World(gravity=(0, 500))
        anchor_body = E.Body(E.Circle(5), (400, 100), static=True)
        weight = E.Body(E.Circle(10), (400, 150), friction=0.0)
        w.add_body(anchor_body)
        w.add_body(weight)
        stiffness, damping = 2000.0, 1600.0  # heavily damped so it settles, not oscillates
        w.add_joint(E.SpringJoint(anchor_body, (0, 0), weight, (0, 0),
                                  rest_length=50, stiffness=stiffness, damping=damping))
        for _ in range(3000):
            w.step(1 / 120)
        dist = (weight.position - anchor_body.position).length()
        expected = 50 + weight.mass * 500 / stiffness  # k*x = m*g at equilibrium
        self.assertAlmostEqual(dist, expected, delta=3.0)
        self.assertAlmostEqual(weight.velocity.y, 0.0, delta=1.0)

    def test_joint_between_two_static_bodies_does_not_crash(self):
        w = E.World(gravity=(0, 500))
        a = E.Body(E.Circle(10), (0, 0), static=True)
        b = E.Body(E.Circle(10), (100, 0), static=True)
        w.add_body(a)
        w.add_body(b)
        w.add_joint(E.DistanceJoint(a, (0, 0), b, (0, 0)))
        w.add_joint(E.PinJoint(a, (0, 0), b, (0, 0)))
        for _ in range(60):
            w.step(1 / 120)  # should simply do nothing, not raise


class TestWorldSerialization(unittest.TestCase):
    def test_to_dict_round_trip_shapes(self):
        w = E.World()
        w.add_body(E.Body(E.Circle(15), (10, 20), name="ball"))
        w.add_body(E.Body(E.Box(30, 40), (50, 60), static=True, name="wall"))
        d = w.to_dict()
        self.assertEqual(len(d["bodies"]), 2)
        ball = d["bodies"][0]
        self.assertEqual(ball["shape"], "circle")
        self.assertEqual(ball["radius"], 15)
        self.assertIn("vx", ball)
        wall = d["bodies"][1]
        self.assertEqual(wall["shape"], "polygon")
        self.assertEqual(len(wall["vertices"]), 4)


if __name__ == "__main__":
    unittest.main()
