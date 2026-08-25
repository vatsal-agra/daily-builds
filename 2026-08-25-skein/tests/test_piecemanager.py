import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import torrent as tm
from skein.piecemanager import PieceManager, PieceError, block_plan, BLOCK_SIZE


def _make_torrent(tmpdir, content: bytes, piece_length=32768):
    src = os.path.join(tmpdir, "src.bin")
    with open(src, "wb") as f:
        f.write(content)
    data = tm.create_torrent(src, "http://x/announce", piece_length=piece_length)
    return tm.parse_torrent(data), src


class TestBlockPlan(unittest.TestCase):
    def test_exact_multiple_of_block_size(self):
        plan = list(block_plan(BLOCK_SIZE * 3))
        self.assertEqual(plan, [(0, BLOCK_SIZE), (BLOCK_SIZE, BLOCK_SIZE), (BLOCK_SIZE * 2, BLOCK_SIZE)])

    def test_remainder_block(self):
        plan = list(block_plan(BLOCK_SIZE * 2 + 100))
        self.assertEqual(plan[-1], (BLOCK_SIZE * 2, 100))

    def test_smaller_than_one_block(self):
        self.assertEqual(list(block_plan(500)), [(0, 500)])


class TestPieceManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_seeder_starts_with_full_bitfield(self):
        content = os.urandom(70000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        pm = PieceManager(t, src, have_all=True)
        self.assertTrue(pm.is_complete())
        self.assertEqual(pm.missing_pieces(), [])

    def test_leecher_starts_empty(self):
        content = os.urandom(70000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        self.assertFalse(pm.is_complete())
        self.assertEqual(len(pm.missing_pieces()), t.num_pieces)
        self.assertEqual(os.path.getsize(dest), t.total_length)  # preallocated

    def test_receive_full_piece_verifies_and_writes(self):
        content = os.urandom(40000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)

        piece0 = content[0:16384]
        completed = False
        for offset, length in block_plan(t.piece_size(0)):
            completed = pm.receive_block(0, offset, piece0[offset:offset + length])
        self.assertTrue(completed)
        self.assertTrue(pm.has_piece(0))

        with open(dest, "rb") as f:
            f.seek(0)
            self.assertEqual(f.read(16384), piece0)

    def test_corrupt_piece_raises_and_is_not_marked_have(self):
        content = os.urandom(20000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)

        bad_piece = os.urandom(t.piece_size(0))  # definitely wrong content
        with self.assertRaises(PieceError):
            for offset, length in block_plan(t.piece_size(0)):
                pm.receive_block(0, offset, bad_piece[offset:offset + length])
        self.assertFalse(pm.has_piece(0))

    def test_duplicate_block_after_completion_is_noop(self):
        content = os.urandom(5000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        pm.receive_block(0, 0, content)
        self.assertTrue(pm.has_piece(0))
        # A late/duplicate delivery of the same block must not raise or
        # re-verify — just be ignored.
        self.assertFalse(pm.receive_block(0, 0, content))

    def test_read_block_before_complete_raises(self):
        content = os.urandom(5000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        with self.assertRaises(PieceError):
            pm.read_block(0, 0, 100)

    def test_seeder_read_block_matches_source(self):
        content = os.urandom(50000)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        pm = PieceManager(t, src, have_all=True)
        block = pm.read_block(1, 0, 100)
        self.assertEqual(block, content[16384:16384 + 100])

    def test_bitfield_bytes_packing(self):
        content = os.urandom(50000)  # 4 pieces at 16384
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        pm.receive_block(0, 0, content[0:16384])
        pm.receive_block(2, 0, content[32768:49152])
        bf = pm.bitfield_bytes()
        from skein.wire import bitfield_indices
        self.assertEqual(bitfield_indices(bf, t.num_pieces), {0, 2})

    def test_rarest_first_prefers_lowest_availability(self):
        content = os.urandom(4 * 16384)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        # piece 0: 3 peers have it, piece 1: 1 peer, piece 2: 2 peers
        pm.note_peer_bitfield([0])
        pm.note_peer_bitfield([0])
        pm.note_peer_bitfield([0, 1])
        pm.note_peer_bitfield([2])
        pm.note_peer_bitfield([2])
        peer_has = {0, 1, 2, 3}
        choice = pm.next_piece_rarest_first(peer_has)
        self.assertEqual(choice, 3)  # availability 0 (nobody announced it) is rarest

    def test_rarest_first_only_considers_pieces_peer_has(self):
        content = os.urandom(4 * 16384)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        choice = pm.next_piece_rarest_first({2})
        self.assertEqual(choice, 2)

    def test_rarest_first_skips_pieces_we_already_have(self):
        content = os.urandom(4 * 16384)
        t, src = _make_torrent(self.tmpdir, content, piece_length=16384)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        pm.receive_block(0, 0, content[0:16384])
        self.assertTrue(pm.has_piece(0))
        choice = pm.next_piece_rarest_first({0, 1})
        self.assertEqual(choice, 1)

    def test_has_block_tracks_partial_progress(self):
        # Use a piece length spanning multiple blocks so a single piece
        # has more than one (offset, length) block to track separately.
        content = os.urandom(BLOCK_SIZE * 6)
        t, src = _make_torrent(self.tmpdir, content, piece_length=BLOCK_SIZE * 3)
        dest = os.path.join(self.tmpdir, "dest.bin")
        pm = PieceManager(t, dest, have_all=False)
        self.assertFalse(pm.has_block(0, 0))
        pm.receive_block(0, 0, content[:BLOCK_SIZE])
        self.assertTrue(pm.has_block(0, 0))
        self.assertFalse(pm.has_block(0, BLOCK_SIZE))


if __name__ == "__main__":
    unittest.main()
