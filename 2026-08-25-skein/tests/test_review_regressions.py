"""Regression tests for every bug found in REVIEW.md's adversarial pass.
Each test reproduces the exact original repro; before the fix these all
either raised an unhandled traceback or produced a misleading result."""

import io
import os
import socket
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import torrent as tm, wire
from skein.node import Node
from skein.tracker import TrackerServer
from skein.cli import main as cli_main


class TestFinding1MalformedPeerMessages(unittest.TestCase):
    """A malicious/buggy peer must never crash a connection thread."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(5000))
        self.tracker = TrackerServer().start()
        self.addCleanup(self.tracker.stop)
        data = tm.create_torrent(src, self.tracker.url, piece_length=32768)
        self.t = tm.parse_torrent(data)

    def _attack(self, node, payload, pre_unchoke=False):
        node.start()
        self.addCleanup(node.stop)
        time.sleep(0.2)
        s = socket.create_connection((node.listen_host, node.listen_port))
        self.addCleanup(s.close)
        wire.send_handshake(s, self.t.info_hash, os.urandom(20))
        wire.recv_handshake(s)
        if pre_unchoke:
            time.sleep(0.1)
            with node._conns_lock:
                for c in node._conns.values():
                    c.am_choking = False
        s.sendall(payload)
        time.sleep(0.4)
        return node

    def test_out_of_range_have_index_drops_connection_not_crash(self):
        dest = os.path.join(self.tmpdir, "leech.out")
        node = Node(self.t, dest, self.tracker.url, have_all=False, name="leech")
        self._attack(node, wire.encode_message(wire.HAVE, wire.pack_have(999999)))
        self.assertEqual(len(node._conns), 0)  # dropped, not stuck/crashed

    def test_truncated_have_payload_drops_connection_not_crash(self):
        dest = os.path.join(self.tmpdir, "leech.out")
        node = Node(self.t, dest, self.tracker.url, have_all=False, name="leech")
        self._attack(node, wire.encode_message(wire.HAVE, b"\x00\x01"))
        self.assertEqual(len(node._conns), 0)

    def test_out_of_range_piece_index_drops_connection_not_crash(self):
        dest = os.path.join(self.tmpdir, "leech.out")
        node = Node(self.t, dest, self.tracker.url, have_all=False, name="leech")
        self._attack(node, wire.encode_message(wire.PIECE, wire.pack_piece(999999, 0, b"x" * 10)))
        self.assertEqual(len(node._conns), 0)

    def test_out_of_range_request_while_unchoked_drops_connection_not_crash(self):
        dest = os.path.join(self.tmpdir, "seed_dest.bin")
        node = Node(self.t, dest, self.tracker.url, have_all=True, name="seed")
        self._attack(node, wire.encode_message(wire.REQUEST, wire.pack_request(999999, 0, 10)),
                     pre_unchoke=True)
        self.assertEqual(len(node._conns), 0)

    def test_node_process_stays_healthy_after_attack(self):
        # The node's background threads (accept/announce/choke loops) must
        # still be alive and the node still usable after an attack — this
        # is what "crashed a thread" vs. "handled the bad peer" looks like
        # from the outside.
        dest = os.path.join(self.tmpdir, "leech.out")
        node = self._attack(
            Node(self.t, dest, self.tracker.url, have_all=False, name="leech"),
            wire.encode_message(wire.HAVE, wire.pack_have(999999)),
        )
        self.assertTrue(all(t.is_alive() for t in node._threads))


class TestFinding2CleanCliErrors(unittest.TestCase):
    """Every subcommand should exit 1 with a clean message, not a traceback,
    on ordinary expected user error."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_create_torrent_missing_source_no_traceback(self):
        code, out, err = self._run(
            ["create-torrent", os.path.join(self.tmpdir, "nope.bin"), "--tracker", "http://x/announce"]
        )
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertIn("error:", err)

    def test_create_torrent_empty_file_no_traceback(self):
        empty = os.path.join(self.tmpdir, "empty.bin")
        open(empty, "wb").close()
        code, out, err = self._run(["create-torrent", empty, "--tracker", "http://x/announce"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_create_torrent_zero_piece_length_no_traceback(self):
        src = os.path.join(self.tmpdir, "f.bin")
        with open(src, "wb") as f:
            f.write(b"hello")
        code, out, err = self._run(
            ["create-torrent", src, "--tracker", "http://x/announce", "--piece-length", "0"]
        )
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_seed_missing_torrent_no_traceback(self):
        code, out, err = self._run(["seed", os.path.join(self.tmpdir, "nope.torrent"), "data.bin"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_seed_corrupt_torrent_no_traceback(self):
        bad = os.path.join(self.tmpdir, "corrupt.torrent")
        with open(bad, "wb") as f:
            f.write(b"not bencode")
        code, out, err = self._run(["seed", bad, "data.bin"])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_viz_malformed_json_no_traceback(self):
        bad = os.path.join(self.tmpdir, "bad.json")
        with open(bad, "w") as f:
            f.write("not json")
        code, out, err = self._run(["viz", bad])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)


class TestFinding3LeechersMustBePositive(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_zero_leechers_fails_clearly_instead_of_claiming_success(self):
        tmpdir = tempfile.mkdtemp()
        src = os.path.join(tmpdir, "f.bin")
        with open(src, "wb") as f:
            f.write(b"hello world")
        code, out, err = self._run(["swarm", src, "--leechers", "0", "--out-dir", tmpdir])
        self.assertEqual(code, 1)
        self.assertIn("at least 1", err)
        self.assertNotIn("RESULT: OK", out)

    def test_negative_leechers_fails_clearly(self):
        tmpdir = tempfile.mkdtemp()
        src = os.path.join(tmpdir, "f.bin")
        with open(src, "wb") as f:
            f.write(b"hello world")
        code, out, err = self._run(["swarm", src, "--leechers", "-3", "--out-dir", tmpdir])
        self.assertEqual(code, 1)
        self.assertIn("at least 1", err)


if __name__ == "__main__":
    unittest.main()
