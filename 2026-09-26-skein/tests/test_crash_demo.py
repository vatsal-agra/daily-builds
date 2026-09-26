"""Drives the real `skein crash-demo` CLI command: spawns a worker
process, sends it a real SIGKILL mid-write, and checks recovery held the
all-or-nothing transaction guarantee. This is the live counterpart to
test_storage.py's synthetic torn-write test.
"""
import os
import shutil
import tempfile
import unittest

from skein.cli import main


class TestCrashDemo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="skein_crashdemo_test_")
        self.path = os.path.join(self.tmpdir, "db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_survives_repeated_real_kills(self):
        rc = main(["crash-demo", self.path, "--rounds", "4", "--batch", "50"])
        self.assertEqual(rc, 0)

    def test_rejects_nonpositive_rounds_and_batch(self):
        self.assertNotEqual(main(["crash-demo", self.path, "--rounds", "0"]), 0)
        self.assertNotEqual(main(["crash-demo", self.path, "--batch", "0"]), 0)


if __name__ == "__main__":
    unittest.main()
