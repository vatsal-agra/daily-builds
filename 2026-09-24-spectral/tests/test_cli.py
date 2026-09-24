import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "spectral.cli", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


class TestCLI(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            jpg = os.path.join(d, "out.jpg")
            bmp = os.path.join(d, "out.bmp")
            r1 = run_cli("encode", "--test-image", "gradient", "--width", "32", "--height", "24",
                         "--output", jpg, "--quality", "70")
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertTrue(os.path.exists(jpg))
            r2 = run_cli("decode", jpg, "--output", bmp)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertTrue(os.path.exists(bmp))

    def test_progressive_and_optimize_together_rejected_cleanly(self):
        # Regression: this used to silently drop --optimize instead of
        # rejecting the unsupported combination -- found during Phase 4
        # polish by directly probing the CLI, the same "fake no-op flag"
        # class of bug this repo's history has flagged before.
        with tempfile.TemporaryDirectory() as d:
            jpg = os.path.join(d, "out.jpg")
            r = run_cli("encode", "--test-image", "gradient", "--width", "16", "--height", "16",
                        "--output", jpg, "--progressive", "--optimize")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("error", r.stderr.lower())
            self.assertFalse(os.path.exists(jpg))

    def test_decode_missing_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_cli("decode", os.path.join(d, "nope.jpg"), "--output", os.path.join(d, "x.bmp"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("error", r.stderr.lower())
            self.assertNotIn("Traceback", r.stderr)

    def test_decode_malformed_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.jpg")
            with open(bad, "wb") as f:
                f.write(b"not a real jpeg")
            r = run_cli("decode", bad, "--output", os.path.join(d, "x.bmp"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("error", r.stderr.lower())
            self.assertNotIn("Traceback", r.stderr)

    def test_encode_negative_dimensions_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_cli("encode", "--test-image", "gradient", "--width", "-5", "--height", "10",
                        "--output", os.path.join(d, "x.jpg"))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("error", r.stderr.lower())
            self.assertNotIn("Traceback", r.stderr)

    def test_encode_unwritable_output_path_fails_cleanly(self):
        r = run_cli("encode", "--test-image", "gradient", "--width", "8", "--height", "8",
                    "--output", "/nonexistent_dir_xyz_abc/out.jpg")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("error", r.stderr.lower())
        self.assertNotIn("Traceback", r.stderr)

    def test_progressive_round_trip_via_cli(self):
        with tempfile.TemporaryDirectory() as d:
            jpg = os.path.join(d, "out.jpg")
            bmp = os.path.join(d, "out.bmp")
            r1 = run_cli("encode", "--test-image", "photo", "--width", "48", "--height", "48",
                         "--output", jpg, "--progressive")
            self.assertEqual(r1.returncode, 0, r1.stderr)
            r2 = run_cli("decode", jpg, "--output", bmp)
            self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_dct_demo_runs(self):
        r = run_cli("dct-demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("max abs diff", r.stdout)

    def test_compare_runs(self):
        r = run_cli("compare", "--test-image", "gradient", "--width", "24", "--height", "24",
                    "--qualities", "30", "70")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("psnr", r.stdout.lower())

    def test_viz_generates_a_real_html_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "viz.html")
            r = run_cli("viz", "--output", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.exists(out))
            with open(out) as f:
                content = f.read()
            self.assertIn("<html", content)
            self.assertIn("data:image/jpeg;base64,", content)


if __name__ == "__main__":
    unittest.main()
