import math
import unittest

from orrery import kepler


class TestKepler(unittest.TestCase):
    def test_solve_kepler_equation_circular(self):
        # e=0: E should equal M exactly (Kepler's equation degenerates).
        for M in (0.0, 1.0, -2.0, 3.0):
            self.assertAlmostEqual(kepler.solve_kepler_equation(M, 0.0), _wrap(M), places=10)

    def test_solve_kepler_equation_satisfies_equation(self):
        for e in (0.0, 0.1, 0.5, 0.9, 0.99):
            for M in (0.0, 0.5, 1.5, 3.0, -1.2):
                E = kepler.solve_kepler_equation(M, e)
                # Check the defining equation holds, not the exact value.
                self.assertAlmostEqual(E - e * math.sin(E), _wrap(M), places=9)

    def test_solve_kepler_equation_rejects_bad_eccentricity(self):
        with self.assertRaises(ValueError):
            kepler.solve_kepler_equation(0.0, 1.0)
        with self.assertRaises(ValueError):
            kepler.solve_kepler_equation(0.0, -0.1)
        with self.assertRaises(ValueError):
            kepler.solve_kepler_equation(0.0, 1.5)

    def test_elements_to_state_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            kepler.elements_to_state(0.0, 0.1, 0, 0, 0, 0, t=0, mu=1.0)
        with self.assertRaises(ValueError):
            kepler.elements_to_state(1.0, 0.1, 0, 0, 0, 0, t=0, mu=0.0)

    def test_circular_orbit_speed_matches_v_equals_sqrt_mu_over_r(self):
        mu = 4.0 * math.pi ** 2
        a = 1.0
        pos, vel = kepler.elements_to_state(a, 0.0, 0, 0, 0, 0, t=0.0, mu=mu)
        self.assertAlmostEqual(pos.norm(), a, places=10)
        self.assertAlmostEqual(vel.norm(), math.sqrt(mu / a), places=8)

    def test_vis_viva_matches_elements_to_state_at_arbitrary_time(self):
        mu = 4.0 * math.pi ** 2
        a, e = 1.0, 0.6
        period = kepler.orbital_period(a, mu)
        for frac in (0.0, 0.1, 0.37, 0.5, 0.83):
            t = frac * period
            pos, vel = kepler.elements_to_state(a, e, 0.3, 0.4, 0.5, 1.0, t=t, mu=mu)
            expected_speed = kepler.vis_viva_speed(pos.norm(), a, mu)
            self.assertAlmostEqual(vel.norm(), expected_speed, places=6)

    def test_orbital_period_matches_keplers_third_law(self):
        mu = 4.0 * math.pi ** 2  # AU/Msun/yr units: a=1 -> T=1 year
        self.assertAlmostEqual(kepler.orbital_period(1.0, mu), 1.0, places=8)
        self.assertAlmostEqual(kepler.orbital_period(4.0, mu), 8.0, places=6)  # T^2 = a^3

    def test_orbit_returns_to_start_after_one_period(self):
        mu = 4.0 * math.pi ** 2
        a, e = 2.0, 0.4
        period = kepler.orbital_period(a, mu)
        pos0, vel0 = kepler.elements_to_state(a, e, 0.2, 0.1, 0.3, 0.7, t=0.0, mu=mu)
        pos1, vel1 = kepler.elements_to_state(a, e, 0.2, 0.1, 0.3, 0.7, t=period, mu=mu)
        self.assertAlmostEqual((pos1 - pos0).norm(), 0.0, places=6)
        self.assertAlmostEqual((vel1 - vel0).norm(), 0.0, places=6)

    def test_vis_viva_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            kepler.vis_viva_speed(0.0, 1.0, 1.0)
        with self.assertRaises(ValueError):
            kepler.vis_viva_speed(1.0, -1.0, 1.0)


def _wrap(theta):
    return (theta + math.pi) % (2.0 * math.pi) - math.pi


if __name__ == "__main__":
    unittest.main()
