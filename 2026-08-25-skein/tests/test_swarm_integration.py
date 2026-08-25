"""End-to-end integration test: real TCP sockets, a real HTTP tracker,
and multiple real threads driving Node objects (the same code path the
`skein seed`/`leech`/`swarm` CLI commands run in their own OS processes —
see demo.sh for the full separate-process version) to reconstruct a file
via genuine piece exchange, then byte-for-byte verify the result.
"""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import torrent as tm
from skein.node import Node
from skein.tracker import TrackerServer


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


class TestSwarmIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracker = TrackerServer().start()
        self.addCleanup(self.tracker.stop)
        self.nodes = []
        self.addCleanup(self._stop_all_nodes)

    def _stop_all_nodes(self):
        for n in self.nodes:
            n.stop()

    def _start_node(self, t, path, have_all, name):
        node = Node(t, path, self.tracker.url, have_all=have_all, name=name,
                    choke_interval=0.5, announce_interval=0.3)
        node.start()
        self.nodes.append(node)
        return node

    def test_single_leecher_downloads_complete_file(self):
        content = os.urandom(80_000)
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(content)
        data = tm.create_torrent(src, self.tracker.url, piece_length=16384)
        t = tm.parse_torrent(data)

        self._start_node(t, src, True, "seed")
        dest = os.path.join(self.tmpdir, "leech.out")
        leech = self._start_node(t, dest, False, "leech")

        self.assertTrue(leech.wait_until_complete(timeout=20))
        self.assertEqual(_sha256(dest), _sha256(src))

    def test_multiple_leechers_all_reconstruct_file_with_cross_seeding(self):
        content = os.urandom(150_000)
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(content)
        data = tm.create_torrent(src, self.tracker.url, piece_length=16384)
        t = tm.parse_torrent(data)

        self._start_node(t, src, True, "seed")
        leechers = []
        for i in range(3):
            dest = os.path.join(self.tmpdir, f"leech-{i}.out")
            leechers.append((self._start_node(t, dest, False, f"leech-{i}"), dest))

        for node, dest in leechers:
            self.assertTrue(node.wait_until_complete(timeout=30), f"{node.name} never completed")
            self.assertEqual(_sha256(dest), _sha256(src), f"{node.name} produced wrong bytes")

        # Prove this was a real swarm, not "everyone downloads from the
        # seed": at least one leecher must have served a block to another
        # peer (tit-for-tat cross-seeding actually happened).
        import time
        time.sleep(1.0)  # let a final choke round record any late uploads
        any_leecher_served = any(
            any(e["kind"] == "block_sent" for e in node.events.snapshot())
            for node, _ in leechers
        )
        self.assertTrue(any_leecher_served, "no leecher-to-leecher piece exchange was observed")

    def test_corrupt_block_from_a_malicious_peer_is_rejected_not_written(self):
        # A leecher that receives a block not matching the piece hash
        # must raise/drop it rather than silently accepting bad data.
        content = os.urandom(20_000)
        src = os.path.join(self.tmpdir, "src.bin")
        with open(src, "wb") as f:
            f.write(content)
        data = tm.create_torrent(src, self.tracker.url, piece_length=16384)
        t = tm.parse_torrent(data)
        dest = os.path.join(self.tmpdir, "dest.bin")
        from skein.piecemanager import PieceManager, PieceError
        pm = PieceManager(t, dest, have_all=False)
        with self.assertRaises(PieceError):
            pm.receive_block(0, 0, os.urandom(t.piece_size(0)))
        self.assertFalse(pm.has_piece(0))


if __name__ == "__main__":
    unittest.main()
