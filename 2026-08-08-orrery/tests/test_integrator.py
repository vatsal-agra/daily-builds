import unittest

from orrery.vector import Vec3
from orrery.body import Body
from orrery import bruteforce, integrator, kepler, scenarios


def _accel_fn(G, softening):
    return lambda bodies: bruteforce.compute_accelerations(bodies, G=G, softening=softening)


class TestIntegrator(unittest.TestCase):
    def test_leapfrog_conserves_energy_far_better_than_euler(self):
        mu = scenarios.G_ASTRO * 1.0
        a, e = 1.0, 0.5
        pos, vel = kepler.elements_to_state(a, e, 0, 0, 0, 0, t=0.0, mu=mu)
        period = kepler.orbital_period(a, mu)
        dt = period / 2000.0

        lf_bodies = [Body("Sun", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("P", 1e-8, pos, vel)]
        e0 = integrator.total_energy(lf_bodies, scenarios.G_ASTRO, 1e-6)
        accel = None
        for _ in range(4000):
            accel = integrator.leapfrog_step(lf_bodies, dt, _accel_fn(scenarios.G_ASTRO, 1e-6), prev_accel=accel)
        e1 = integrator.total_energy(lf_bodies, scenarios.G_ASTRO, 1e-6)
        lf_drift = abs((e1 - e0) / e0)

        eu_bodies = [Body("Sun", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("P", 1e-8, pos, vel)]
        e0b = integrator.total_energy(eu_bodies, scenarios.G_ASTRO, 1e-6)
        for _ in range(4000):
            integrator.euler_step(eu_bodies, dt, _accel_fn(scenarios.G_ASTRO, 1e-6))
        e1b = integrator.total_energy(eu_bodies, scenarios.G_ASTRO, 1e-6)
        eu_drift = abs((e1b - e0b) / e0b)

        self.assertLess(lf_drift, 1e-6)
        self.assertGreater(eu_drift, 0.05)
        self.assertLess(lf_drift, eu_drift / 1000)

    def test_leapfrog_prev_accel_reuse_matches_recompute(self):
        # Reusing the returned acceleration as prev_accel next step should
        # give bit-for-bit the same trajectory as always recomputing,
        # since it's the same value either way -- just fewer force evals.
        bodies_reuse = [Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("b", 1.0, Vec3(2, 0, 0), Vec3(0, 1, 0))]
        bodies_recompute = [Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)), Body("b", 1.0, Vec3(2, 0, 0), Vec3(0, 1, 0))]
        accel_fn = _accel_fn(1.0, 0.05)

        accel = None
        for _ in range(50):
            accel = integrator.leapfrog_step(bodies_reuse, 0.01, accel_fn, prev_accel=accel)
        for _ in range(50):
            integrator.leapfrog_step(bodies_recompute, 0.01, accel_fn, prev_accel=None)

        self.assertAlmostEqual(bodies_reuse[1].position.x, bodies_recompute[1].position.x, places=10)
        self.assertAlmostEqual(bodies_reuse[1].position.y, bodies_recompute[1].position.y, places=10)

    def test_total_momentum_and_angular_momentum(self):
        bodies = [
            Body("a", 1.0, Vec3(1, 0, 0), Vec3(0, 1, 0)),
            Body("b", 1.0, Vec3(-1, 0, 0), Vec3(0, -1, 0)),
        ]
        self.assertEqual(integrator.total_momentum(bodies), Vec3(0, 0, 0))
        L = integrator.total_angular_momentum(bodies)
        # Each body: r x p = (1,0,0)x(0,1,0) = (0,0,1), summed twice.
        self.assertAlmostEqual(L.z, 2.0, places=10)

    def test_dead_bodies_excluded_from_diagnostics(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(1, 0, 0)),
            Body("b", 1.0, Vec3(5, 0, 0), Vec3(0, 0, 0)),
        ]
        bodies[1].alive = False
        self.assertEqual(integrator.total_kinetic_energy(bodies), 0.5)
        self.assertEqual(integrator.total_potential_energy(bodies, G=1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
