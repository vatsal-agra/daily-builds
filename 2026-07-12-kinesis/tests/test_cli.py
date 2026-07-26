import json
import os
import shutil
import tempfile
import unittest

from kinesis import cli


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)


class TestArgValidation(CliTestCase):
    def test_pop_size_below_tournament_size_is_rejected(self):
        rc = cli.main(["evolve", "--generations", "1", "--pop-size", "2",
                       "--out", self.p("pop.json")])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.p("pop.json")))

    def test_zero_generations_is_rejected(self):
        rc = cli.main(["evolve", "--generations", "0", "--pop-size", "8",
                        "--out", self.p("pop.json")])
        self.assertEqual(rc, 1)

    def test_negative_duration_is_rejected(self):
        rc = cli.main(["evolve", "--generations", "1", "--pop-size", "8",
                        "--duration", "-1", "--out", self.p("pop.json")])
        self.assertEqual(rc, 1)

    def test_rank_out_of_range_is_a_clean_error(self):
        cli.main(["evolve", "--generations", "1", "--pop-size", "8", "--duration", "1.0",
                  "--seed", "1", "--out", self.p("pop.json")])
        rc = cli.main(["replay", "--checkpoint", self.p("pop.json"), "--rank", "999",
                        "--out", self.p("r.html")])
        self.assertEqual(rc, 1)


class TestCleanErrorsNotTracebacks(CliTestCase):
    def test_missing_checkpoint_file(self):
        rc = cli.main(["gallery", "--checkpoint", self.p("nope.json"), "--out", self.p("g.html")])
        self.assertEqual(rc, 1)

    def test_malformed_json(self):
        with open(self.p("bad.json"), "w") as f:
            f.write("{not json")
        rc = cli.main(["replay", "--genome", self.p("bad.json"), "--out", self.p("r.html")])
        self.assertEqual(rc, 1)

    def test_checkpoint_passed_where_bare_genome_expected(self):
        cli.main(["evolve", "--generations", "1", "--pop-size", "8", "--duration", "1.0",
                  "--seed", "1", "--out", self.p("pop.json")])
        rc = cli.main(["replay", "--genome", self.p("pop.json"), "--out", self.p("r.html")])
        self.assertEqual(rc, 1)

    def test_bare_genome_passed_where_checkpoint_expected(self):
        cli.main(["evolve", "--generations", "1", "--pop-size", "8", "--duration", "1.0",
                  "--seed", "1", "--out", self.p("pop.json")])
        with open(self.p("pop.json")) as f:
            checkpoint = json.load(f)
        bare_genome_path = self.p("genome_only.json")
        with open(bare_genome_path, "w") as f:
            json.dump(checkpoint["individuals"][0]["genome"], f)
        rc = cli.main(["gallery", "--checkpoint", bare_genome_path, "--out", self.p("g.html")])
        self.assertEqual(rc, 1)


class TestEndToEndPipeline(CliTestCase):
    def test_evolve_replay_gallery_fitness_chart(self):
        rc = cli.main(["evolve", "--generations", "2", "--pop-size", "8", "--duration", "1.5",
                        "--seed", "3", "--out", self.p("pop.json")])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.p("pop.json")))

        rc = cli.main(["replay", "--checkpoint", self.p("pop.json"), "--rank", "0",
                        "--duration", "2.0", "--out", self.p("replay.html")])
        self.assertEqual(rc, 0)
        html = open(self.p("replay.html")).read()
        self.assertIn("<canvas", html)

        rc = cli.main(["gallery", "--checkpoint", self.p("pop.json"), "--out", self.p("gallery.html")])
        self.assertEqual(rc, 0)
        self.assertIn("<svg", open(self.p("gallery.html")).read())

        rc = cli.main(["fitness-chart", "--checkpoint", self.p("pop.json"),
                        "--out", self.p("fitness.html")])
        self.assertEqual(rc, 0)
        self.assertIn("<canvas", open(self.p("fitness.html")).read())

    def test_output_directories_are_auto_created(self):
        rc = cli.main(["evolve", "--generations", "1", "--pop-size", "8", "--duration", "1.0",
                        "--seed", "1", "--out", self.p("deep", "nested", "pop.json")])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(self.p("deep", "nested", "pop.json")))

    def test_resume_continues_generation_count(self):
        pop_path = self.p("pop.json")
        cli.main(["evolve", "--generations", "2", "--pop-size", "6", "--duration", "1.0",
                  "--seed", "2", "--out", pop_path])
        with open(pop_path) as f:
            before = json.load(f)
        rc = cli.main(["evolve", "--resume", pop_path, "--generations", "2", "--out", pop_path])
        self.assertEqual(rc, 0)
        with open(pop_path) as f:
            after = json.load(f)
        self.assertGreater(after["generation"], before["generation"])
        gens = [h["generation"] for h in after["history"]]
        self.assertEqual(gens, list(range(len(gens))))

    def test_demo_runs_end_to_end(self):
        rc = cli.main(["demo", "--out-dir", self.p("demo_out")])
        self.assertEqual(rc, 0)
        for fname in ("demo_population.json", "demo_replay.html",
                      "demo_gallery.html", "demo_fitness.html"):
            self.assertTrue(os.path.exists(self.p("demo_out", fname)), fname)


if __name__ == "__main__":
    unittest.main()
