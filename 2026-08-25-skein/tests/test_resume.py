"""Resume support: a leecher killed mid-download and restarted against
the same dest_file should pick up from its on-disk partial state
instead of re-downloading everything from scratch — verified here with
a real kill-and-restart of a real Node against a real partial file."""

import hashlib
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import torrent as tm
from skein.node import Node
from skein.piecemanager import PieceManager
from skein.tracker import TrackerServer


def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestResumeUnit(unittest.TestCase):
    """Unit-level: PieceManager rechecks an existing file directly."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_recheck_recovers_correct_pieces_and_ignores_wrong_ones(self):
        content = os.urandom(4 * 16384)
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(content)
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        t = tm.parse_torrent(data)

        dest = os.path.join(self.tmpdir, "dest.bin")
        # Simulate a previous partial run: pieces 0 and 2 correct, piece 1
        # garbage (interrupted mid-write), piece 3 all zero (never touched).
        partial = bytearray(t.total_length)
        partial[0:16384] = content[0:16384]
        partial[16384:32768] = os.urandom(16384)  # wrong
        partial[32768:49152] = content[32768:49152]
        with open(dest, "wb") as f:
            f.write(partial)

        pm = PieceManager(t, dest, have_all=False, resume=True)
        self.assertEqual(pm.recovered_on_resume, 2)
        self.assertTrue(pm.has_piece(0))
        self.assertFalse(pm.has_piece(1))
        self.assertTrue(pm.has_piece(2))
        self.assertFalse(pm.has_piece(3))

    def test_resume_false_ignores_existing_correct_data(self):
        content = os.urandom(16384)
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(content)
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        t = tm.parse_torrent(data)

        dest = os.path.join(self.tmpdir, "dest.bin")
        with open(dest, "wb") as f:
            f.write(content)  # already fully correct on disk

        pm = PieceManager(t, dest, have_all=False, resume=False)
        self.assertEqual(pm.recovered_on_resume, 0)
        self.assertFalse(pm.has_piece(0))

    def test_no_existing_file_has_nothing_to_recover(self):
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(20000))
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        t = tm.parse_torrent(data)
        dest = os.path.join(self.tmpdir, "fresh.bin")
        pm = PieceManager(t, dest, have_all=False)
        self.assertEqual(pm.recovered_on_resume, 0)


class TestResumeIntegration(unittest.TestCase):
    """End-to-end: kill a real leecher Node mid-transfer, start a fresh
    Node instance pointed at the same dest_file, and confirm it resumes
    (rather than re-downloading everything) and still finishes correctly.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = TrackerServer().start()
        self.addCleanup(self.tracker.stop)

    def test_kill_and_restart_resumes_and_completes(self):
        # Large enough (~60 pieces) that a single-connection transfer
        # takes a few real seconds, giving the poll loop below a
        # comfortable window to reliably catch it mid-download.
        content = os.urandom(1_000_000)
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(content)
        data = tm.create_torrent(src, self.tracker.url, piece_length=16384)
        t = tm.parse_torrent(data)

        seed = Node(t, src, self.tracker.url, have_all=True, name="seed",
                    choke_interval=0.5, announce_interval=0.3)
        seed.start()
        self.addCleanup(seed.stop)

        dest = os.path.join(self.tmpdir, "leech.out")
        leech1 = Node(t, dest, self.tracker.url, have_all=False, name="leech-run1",
                       choke_interval=0.5, announce_interval=0.3)
        leech1.start()
        # Let it get partway, then kill it before it finishes — a real
        # "process died mid-download" scenario.
        deadline = time.time() + 15
        while time.time() < deadline:
            done, total = leech1.pm.progress()
            if 0 < done < total:
                break
            time.sleep(0.05)
        done, total = leech1.pm.progress()
        self.assertGreater(done, 0, "test setup: leecher never got any pieces before kill")
        self.assertLess(done, total, "test setup: leecher finished before we could kill it")
        leech1.stop()

        # Fresh Node instance, same dest_file: this is what a restarted
        # `skein leech` process looks like.
        leech2 = Node(t, dest, self.tracker.url, have_all=False, name="leech-run2",
                       choke_interval=0.5, announce_interval=0.3)
        self.assertGreaterEqual(leech2.pm.recovered_on_resume, done,
                                 "resume must recover at least what was verified before the kill")
        leech2.start()
        self.addCleanup(leech2.stop)

        self.assertTrue(leech2.wait_until_complete(timeout=30))
        self.assertEqual(_sha256(dest), _sha256(src))


if __name__ == "__main__":
    unittest.main()
