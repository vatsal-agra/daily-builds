import unittest

from kinesis.ga import Population


class TestEvolutionImproves(unittest.TestCase):
    """The core required-feature gate: a genetic algorithm that
    measurably improves locomotion fitness over generations."""

    def test_best_fitness_is_monotonically_non_decreasing(self):
        # Guaranteed by elitism (the top performer is always cloned
        # unchanged into the next generation), so this must hold for
        # *any* seed -- a strong, deterministic regression guard.
        pop = Population(pop_size=10, seed=1, sim_duration=1.5)
        pop.run(5)
        bests = [h["best"] for h in pop.history]
        for i in range(1, len(bests)):
            self.assertGreaterEqual(bests[i], bests[i - 1] - 1e-9)

    def test_fitness_meaningfully_improves_from_random_baseline(self):
        pop = Population(pop_size=10, seed=7, sim_duration=2.0)
        pop.run(5)
        first, last = pop.history[0], pop.history[-1]
        self.assertGreater(last["best"], first["best"])
        self.assertGreater(last["mean"], first["mean"])

    def test_champion_is_never_nan(self):
        pop = Population(pop_size=8, seed=2, sim_duration=1.5)
        pop.run(3)
        champ = pop.best()
        self.assertEqual(champ.fitness, champ.fitness)  # NaN != NaN


class TestPopulationApiRobustness(unittest.TestCase):
    """Regression tests for adversarial-review findings around
    Population's public API."""

    def test_best_is_safe_immediately_after_step_generation(self):
        # step_generation() leaves the *new* generation's non-elite
        # members unevaluated (fitness=None) -- best() used to crash
        # here with a TypeError comparing None to float.
        pop = Population(pop_size=4, seed=4, sim_duration=1.0)
        pop.step_generation()
        champ = pop.best()
        self.assertIsInstance(champ.fitness, float)

    def test_save_creates_missing_parent_directories(self):
        import tempfile
        import os
        import shutil
        tmp = tempfile.mkdtemp()
        try:
            pop = Population(pop_size=4, seed=5, sim_duration=1.0)
            pop.step_generation()
            out_path = os.path.join(tmp, "nested", "dir", "pop.json")
            pop.save(out_path)  # must not raise FileNotFoundError
            self.assertTrue(os.path.exists(out_path))
        finally:
            shutil.rmtree(tmp)

    def test_save_never_writes_null_fitness(self):
        import tempfile, os, json, shutil
        tmp = tempfile.mkdtemp()
        try:
            pop = Population(pop_size=4, seed=6, sim_duration=1.0)
            pop.step_generation()  # new generation has unevaluated members
            out_path = os.path.join(tmp, "pop.json")
            pop.save(out_path)
            with open(out_path) as f:
                d = json.load(f)
            for ind in d["individuals"]:
                self.assertIsNotNone(ind["fitness"])
        finally:
            shutil.rmtree(tmp)


class TestResumeHistoryIntegrity(unittest.TestCase):
    """Regression test for the duplicate-history-entry bug found while
    building the checkpoint-resume stretch feature."""

    def test_resumed_history_has_no_duplicate_or_missing_generations(self):
        pop = Population(pop_size=6, seed=8, sim_duration=1.0)
        pop.run(2)
        checkpoint = pop.to_dict()

        resumed = Population.from_dict(checkpoint, seed=9)
        resumed.run(2)

        gens = [h["generation"] for h in resumed.history]
        self.assertEqual(gens, list(range(len(gens))))
        self.assertEqual(len(gens), len(set(gens)))


if __name__ == "__main__":
    unittest.main()
