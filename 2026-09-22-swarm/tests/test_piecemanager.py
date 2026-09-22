import hashlib
import os
import tempfile
import unittest

from swarm import piecemanager, torrentfile
from swarm.piecemanager import PieceHashMismatch, PieceManager, bitfield_to_indices, indices_to_bitfield


def _make_torrent(tmpdir, size=1000, piece_length=300, name="data.bin", seed_byte_source=None):
    path = os.path.join(tmpdir, name)
    with open(path, "wb") as f:
        f.write(seed_byte_source if seed_byte_source is not None else os.urandom(size))
    info = torrentfile.create_torrent(path, announce="http://x/announce", piece_length=piece_length)
    return path, info


class TestBitfieldConversion(unittest.TestCase):
    def test_roundtrip(self):
        for indices, n in [({0, 1, 2}, 5), (set(), 8), ({7}, 8), ({0, 8, 15}, 16)]:
            bits = indices_to_bitfield(indices, n)
            self.assertEqual(bitfield_to_indices(bits, n), indices)

    def test_msb_is_piece_zero(self):
        bits = indices_to_bitfield({0}, 8)
        self.assertEqual(bits, bytes([0b10000000]))

    def test_short_bitfield_treated_as_all_missing_tail(self):
        # A malformed/truncated bitfield shouldn't crash -- just stop early.
        self.assertEqual(bitfield_to_indices(b"", 10), set())


class TestPieceManagerSeed(unittest.TestCase):
    def test_seed_starts_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            pm = PieceManager(info, path, seed=True)
            self.assertTrue(pm.is_complete())
            self.assertEqual(pm.have_count(), info.num_pieces)

    def test_seed_rejects_wrong_size_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            with open(path, "ab") as f:
                f.write(b"extra")
            with self.assertRaises(ValueError):
                PieceManager(info, path, seed=True)

    def test_read_block_for_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            with open(path, "rb") as f:
                original = f.read()
            pm = PieceManager(info, path, seed=True)
            block = pm.read_block_for_upload(0, 10, 50)
            self.assertEqual(block, original[10:60])


class TestPieceManagerLeech(unittest.TestCase):
    def _transfer_all(self, pm: PieceManager, info, original: bytes, peer_id=b"P" * 20):
        pm.mark_peer_has(peer_id, 0)
        for i in range(info.num_pieces):
            pm.mark_peer_has(peer_id, i)
        for i in range(info.num_pieces):
            idx = pm.choose_piece_for_peer(peer_id)
            self.assertIsNotNone(idx)
            size = info.piece_size(idx)
            offset = idx * info.piece_length
            piece_bytes = original[offset : offset + size]
            for begin, length in pm.blocks_for_piece(idx):
                complete = pm.receive_block(idx, begin, piece_bytes[begin : begin + length], peer_id)
            self.assertTrue(complete)

    def test_full_download_reconstructs_exact_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_path, info = _make_torrent(tmp, size=1000, piece_length=300, name="src.bin")
            with open(src_path, "rb") as f:
                original = f.read()
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False)
            self._transfer_all(pm, info, original)
            self.assertTrue(pm.is_complete())
            self.assertTrue(pm.verify_full_file())
            with open(out_path, "rb") as f:
                self.assertEqual(f.read(), original)

    def test_corrupt_block_rejected_and_piece_stays_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_path, info = _make_torrent(tmp, size=900, piece_length=300, name="src.bin")
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False)
            peer = b"P" * 20
            pm.mark_peer_has(peer, 0)
            idx = pm.choose_piece_for_peer(peer)
            blocks = pm.blocks_for_piece(idx)
            for begin, length in blocks[:-1]:
                pm.receive_block(idx, begin, b"\x00" * length, peer)
            begin, length = blocks[-1]
            with self.assertRaises(PieceHashMismatch):
                pm.receive_block(idx, begin, b"\xff" * length, peer)
            self.assertEqual(pm.state_snapshot()[idx], piecemanager.MISSING)
            self.assertFalse(pm.is_complete())

    def test_rarest_first_prefers_scarcer_piece(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, info = _make_torrent(tmp, size=1000, piece_length=300, name="src.bin")  # 4 pieces
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False)
            common_peer, rare_peer = b"C" * 20, b"R" * 20
            # every peer has piece 0 and 1; only rare_peer has piece 2
            pm.mark_peer_has(common_peer, 0)
            pm.mark_peer_has(common_peer, 1)
            pm.mark_peer_has(rare_peer, 0)
            pm.mark_peer_has(rare_peer, 1)
            pm.mark_peer_has(rare_peer, 2)
            chosen = pm.choose_piece_for_peer(rare_peer)
            self.assertEqual(chosen, 2)  # rarity 1, strictly rarer than 0/1 (rarity 2)

    def test_disconnect_releases_assigned_piece(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, info = _make_torrent(tmp, size=900, piece_length=300, name="src.bin")
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False)
            peer = b"P" * 20
            pm.mark_peer_has(peer, 0)
            idx = pm.choose_piece_for_peer(peer)
            self.assertEqual(pm.state_snapshot()[idx], piecemanager.DOWNLOADING)
            pm.remove_peer(peer)
            self.assertEqual(pm.state_snapshot()[idx], piecemanager.MISSING)

    def test_block_from_wrong_peer_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, info = _make_torrent(tmp, size=900, piece_length=300, name="src.bin")
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False)
            a, b = b"A" * 20, b"B" * 20
            pm.mark_peer_has(a, 0)
            idx = pm.choose_piece_for_peer(a)
            begin, length = pm.blocks_for_piece(idx)[0]
            result = pm.receive_block(idx, begin, b"\x00" * length, b)  # b never got this assignment
            self.assertFalse(result)

    def test_out_of_range_piece_index_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, info = _make_torrent(tmp, size=300, piece_length=300, name="src.bin")
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False)
            with self.assertRaises(ValueError):
                pm.mark_peer_has(b"P" * 20, 999)

    def test_preseed_copies_real_bytes_and_verifies_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_path, info = _make_torrent(tmp, size=900, piece_length=300, name="src.bin")
            with open(src_path, "rb") as f:
                original = f.read()
            out_path = os.path.join(tmp, "out.bin")
            pm = PieceManager(info, out_path, seed=False, preseed_source=src_path, preseed_pieces={0, 2})
            self.assertEqual(pm.state_snapshot(), [piecemanager.HAVE, piecemanager.MISSING, piecemanager.HAVE])
            with open(out_path, "rb") as f:
                data = f.read()
            self.assertEqual(data[0:300], original[0:300])
            self.assertEqual(data[600:900], original[600:900])

    def test_preseed_without_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, info = _make_torrent(tmp, size=300, piece_length=300, name="src.bin")
            out_path = os.path.join(tmp, "out.bin")
            with self.assertRaises(ValueError):
                PieceManager(info, out_path, seed=False, preseed_pieces={0})


if __name__ == "__main__":
    unittest.main()
