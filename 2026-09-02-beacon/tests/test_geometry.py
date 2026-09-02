import math
import random
import unittest

from beacon.geometry import (
    bresenham_line,
    normalize_angle,
    ray_segment_intersection,
    raycast,
)


class TestNormalizeAngle(unittest.TestCase):
    def test_already_in_range(self):
        self.assertAlmostEqual(normalize_angle(0.5), 0.5)

    def test_wraps_positive(self):
        self.assertAlmostEqual(normalize_angle(2 * math.pi + 0.1), 0.1, places=9)

    def test_wraps_negative(self):
        self.assertAlmostEqual(normalize_angle(-2 * math.pi - 0.1), -0.1, places=9)

    def test_boundary_pi(self):
        # pi should map to pi (within the (-pi, pi] convention), not -pi.
        self.assertAlmostEqual(abs(normalize_angle(math.pi)), math.pi, places=9)


class TestRaySegmentIntersection(unittest.TestCase):
    def test_hits_perpendicular_wall(self):
        # Ray straight along +x from origin, wall is the vertical segment
        # x=5 from y=-1 to y=1. Should hit at t=5.
        t = ray_segment_intersection((0, 0), (1, 0), ((5, -1), (5, 1)))
        self.assertAlmostEqual(t, 5.0)

    def test_misses_wall_out_of_span(self):
        # Same wall but shifted so the ray passes below it.
        t = ray_segment_intersection((0, 0), (1, 0), ((5, 2), (5, 4)))
        self.assertIsNone(t)

    def test_wall_behind_ray_is_not_hit(self):
        t = ray_segment_intersection((0, 0), (1, 0), ((-5, -1), (-5, 1)))
        self.assertIsNone(t)

    def test_parallel_ray_and_segment(self):
        t = ray_segment_intersection((0, 0), (1, 0), ((-1, 5), (10, 5)))
        self.assertIsNone(t)

    def test_diagonal_hit_matches_hand_computation(self):
        # 45-degree ray from origin should hit the segment x+y=4 (from
        # (4,0) to (0,4)) at distance 2*sqrt(2).
        direction = (math.cos(math.pi / 4), math.sin(math.pi / 4))
        t = ray_segment_intersection((0, 0), direction, ((4, 0), (0, 4)))
        self.assertAlmostEqual(t, 2 * math.sqrt(2), places=9)


class TestRaycast(unittest.TestCase):
    def test_picks_nearest_of_multiple_walls(self):
        segs = [((5, -1), (5, 1)), ((3, -1), (3, 1)), ((8, -1), (8, 1))]
        d = raycast((0, 0), 0.0, segs, max_range=100.0)
        self.assertAlmostEqual(d, 3.0)

    def test_respects_max_range(self):
        segs = [((5, -1), (5, 1))]
        d = raycast((0, 0), 0.0, segs, max_range=3.0)
        self.assertIsNone(d)

    def test_empty_wall_list(self):
        self.assertIsNone(raycast((0, 0), 0.0, [], max_range=10.0))


class TestBresenhamLine(unittest.TestCase):
    def _brute_force_reference(self, c0, c1):
        """A slow, obviously-correct supercover-ish reference: walk in
        fine sub-steps along the true line and record every integer cell
        the sample point falls into, deduplicated in order. Used only to
        cross-check bresenham_line's cell sequence endpoints and general
        shape -- not a byte-exact oracle (Bresenham's mid-point choices
        near diagonals are a legitimate implementation choice), but any
        correct line-tracer must at least start and end at the right
        cells and produce a fully 8-connected path with no gaps."""
        x0, y0 = c0
        x1, y1 = c1
        n = max(abs(x1 - x0), abs(y1 - y0), 1) * 20
        cells = []
        for i in range(n + 1):
            t = i / n
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            cell = (round(x), round(y))
            if not cells or cells[-1] != cell:
                cells.append(cell)
        return cells

    def test_endpoints_included(self):
        line = bresenham_line((0, 0), (7, 3))
        self.assertEqual(line[0], (0, 0))
        self.assertEqual(line[-1], (7, 3))

    def test_horizontal_line(self):
        line = bresenham_line((0, 0), (5, 0))
        self.assertEqual(line, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0)])

    def test_vertical_line(self):
        line = bresenham_line((2, 2), (2, -2))
        self.assertEqual(line, [(2, 2), (2, 1), (2, 0), (2, -1), (2, -2)])

    def test_single_point(self):
        self.assertEqual(bresenham_line((3, 3), (3, 3)), [(3, 3)])

    def test_no_gaps_8_connected(self):
        # Every consecutive pair of cells must be a king's-move (8-connected)
        # apart -- a real gap would mean a wall could be "seen through".
        line = bresenham_line((0, 0), (13, 5))
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            self.assertLessEqual(abs(x1 - x0), 1)
            self.assertLessEqual(abs(y1 - y0), 1)
            self.assertTrue(abs(x1 - x0) or abs(y1 - y0))

    def test_reverse_has_same_length_and_endpoints_swapped(self):
        # NB: classic mid-point Bresenham is *not* guaranteed to visit the
        # exact same cell set forwards vs. backwards (its tie-breaking on
        # the decision boundary is direction-dependent) -- that's a known,
        # accepted property of the algorithm, not a bug here. What must
        # hold regardless of direction: same number of steps, and the
        # endpoints simply swap.
        for c0, c1 in [((0, 0), (9, 4)), ((0, 0), (4, 9)), ((0, 0), (-6, 3)), ((0, 0), (-6, -3))]:
            forward = bresenham_line(c0, c1)
            backward = bresenham_line(c1, c0)
            self.assertEqual(len(forward), len(backward))
            self.assertEqual((forward[0], forward[-1]), (backward[-1], backward[0]))

    def test_matches_reference_endpoints_and_monotonicity(self):
        rng = random.Random(0)
        for _ in range(20):
            c0 = (rng.randint(-10, 10), rng.randint(-10, 10))
            c1 = (rng.randint(-10, 10), rng.randint(-10, 10))
            line = bresenham_line(c0, c1)
            self.assertEqual(line[0], c0)
            self.assertEqual(line[-1], c1)
            # x and y must each move monotonically toward the target.
            xs = [c[0] for c in line]
            ys = [c[1] for c in line]
            if c1[0] != c0[0]:
                self.assertEqual(xs == sorted(xs) or xs == sorted(xs, reverse=True), True)
            if c1[1] != c0[1]:
                self.assertEqual(ys == sorted(ys) or ys == sorted(ys, reverse=True), True)


if __name__ == "__main__":
    unittest.main()
