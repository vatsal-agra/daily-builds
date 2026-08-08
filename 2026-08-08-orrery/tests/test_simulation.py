import json
import os
import tempfile
import unittest

from orrery.vector import Vec3
from orrery.body import Body
from orrery.simulation import Simulation
from orrery import scenarios


def _two_body():
    return [
        Body("Sun", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
        Body("P", 1e-6, Vec3(1, 0, 0), Vec3(0, 2 * 3.14159265, 0)),
    ]


class TestSimulation(unittest.TestCase):
    def test_rejects_empty_body_list(self):
        with self.assertRaises(ValueError):
            Simulation([])

    def test_rejects_unknown_method(self):
        with self.assertRaises(ValueError):
            Simulation(_two_body(), method="rk4")

    def test_rejects_negative_softening_and_theta(self):
        with self.assertRaises(ValueError):
            Simulation(_two_body(), softening=-1.0)
        with self.assertRaises(ValueError):
            Simulation(_two_body(), theta=-1.0)

    def test_step_rejects_nonpositive_dt(self):
        sim = Simulation(_two_body(), G=scenarios.G_ASTRO, use_barnes_hut=False, softening=1e-4)
        with self.assertRaises(ValueError):
            sim.step(0.0)
        with self.assertRaises(ValueError):
            sim.step(-0.1)

    def test_run_rejects_bad_steps_and_record_every(self):
        sim = Simulation(_two_body(), G=scenarios.G_ASTRO, use_barnes_hut=False, softening=1e-4)
        with self.assertRaises(ValueError):
            sim.run(-1, 0.01)
        with self.assertRaises(ValueError):
            sim.run(10, 0.01, record_every=0)

    def test_run_zero_steps_records_only_initial_snapshot(self):
        sim = Simulation(_two_body(), G=scenarios.G_ASTRO, use_barnes_hut=False, softening=1e-4)
        history = sim.run(0, 0.01)
        self.assertEqual(len(history), 1)
        self.assertEqual(sim.t, 0.0)

    def test_run_advances_time_and_step_count(self):
        sim = Simulation(_two_body(), G=scenarios.G_ASTRO, use_barnes_hut=False, softening=1e-4)
        sim.run(100, 0.01)
        self.assertAlmostEqual(sim.t, 1.0, places=8)
        self.assertEqual(sim.step_count, 100)

    def test_record_every_thins_history_but_keeps_endpoints(self):
        sim = Simulation(_two_body(), G=scenarios.G_ASTRO, use_barnes_hut=False, softening=1e-4)
        history = sim.run(50, 0.01, record_every=1000)
        # record_every far exceeds steps, but first+last are always kept.
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["step"], 0)
        self.assertEqual(history[-1]["step"], 50)

    def test_divergence_raises_floatingpointerror_cleanly(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(1e300, 0, 0)),
            Body("b", 1.0, Vec3(10, 0, 0), Vec3(0, 0, 0)),
        ]
        sim = Simulation(bodies, G=1.0, use_barnes_hut=False, softening=0.1)
        with self.assertRaises(FloatingPointError):
            sim.step(1e20)

    def test_checkpoint_round_trip(self):
        sim = Simulation.from_scenario(scenarios.binary_star(), use_barnes_hut=False)
        sim.run(20, 0.001)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt.json")
            sim.save(path)
            restored = Simulation.load(path)
        self.assertAlmostEqual(restored.t, sim.t, places=10)
        self.assertEqual(restored.step_count, sim.step_count)
        self.assertEqual(len(restored.bodies), len(sim.bodies))
        for a, b in zip(restored.bodies, sim.bodies):
            self.assertAlmostEqual((a.position - b.position).norm(), 0.0, places=10)

    def test_resume_continues_physics_correctly(self):
        sim = Simulation.from_scenario(scenarios.binary_star(), use_barnes_hut=False)
        sim.run(500, 0.001)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt.json")
            sim.save(path)
            resumed = Simulation.load(path)
        resumed.run(500, 0.001)

        # Reference: run the same total step count in one continuous sim.
        ref = Simulation.from_scenario(scenarios.binary_star(), use_barnes_hut=False)
        ref.run(1000, 0.001)

        for a, b in zip(resumed.bodies, ref.bodies):
            self.assertAlmostEqual((a.position - b.position).norm(), 0.0, places=6)

    def test_from_checkpoint_rejects_missing_fields(self):
        with self.assertRaises(ValueError):
            Simulation.from_checkpoint({"t": 0})

    def test_from_checkpoint_rejects_empty_bodies(self):
        d = {"t": 0, "step_count": 0, "G": 1.0, "method": "leapfrog", "theta": 0.5, "softening": 0.0, "bodies": []}
        with self.assertRaises(ValueError):
            Simulation.from_checkpoint(d)

    def test_load_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            Simulation.load("/nonexistent/path/checkpoint.json")

    def test_load_malformed_json_raises_valueerror(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            with self.assertRaises(ValueError):
                Simulation.load(path)

    def test_collisions_reset_cached_leapfrog_acceleration(self):
        bodies = [
            Body("a", 1.0, Vec3(-1, 0, 0), Vec3(1, 0, 0), radius=0.5),
            Body("b", 1.0, Vec3(1, 0, 0), Vec3(-1, 0, 0), radius=0.5),
        ]
        sim = Simulation(bodies, G=0.0, use_barnes_hut=False, collisions=True, softening=0.01)
        sim.run(60, 0.02)
        alive = [b for b in sim.bodies if b.alive]
        self.assertEqual(len(alive), 1)
        self.assertEqual(len(sim.collision_log), 1)


if __name__ == "__main__":
    unittest.main()
