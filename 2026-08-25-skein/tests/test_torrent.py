import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import torrent as tm
from skein import bencode


class TestTorrent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_file(self, name, content: bytes):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_create_and_parse_round_trip(self):
        content = os.urandom(70_000)
        src = self._make_file("data.bin", content)
        data = tm.create_torrent(src, "http://tracker.example/announce", piece_length=16384)
        t = tm.parse_torrent(data)
        self.assertEqual(t.name, "data.bin")
        self.assertEqual(t.total_length, len(content))
        self.assertEqual(t.piece_length, 16384)
        self.assertEqual(t.num_pieces, 5)  # ceil(70000/16384) = 5
        self.assertEqual(t.announce, "http://tracker.example/announce")

    def test_piece_hashes_match_manual_sha1(self):
        content = os.urandom(50_000)
        src = self._make_file("data.bin", content)
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        t = tm.parse_torrent(data)
        for i in range(t.num_pieces):
            start = i * t.piece_length
            end = start + t.piece_size(i)
            expected = hashlib.sha1(content[start:end]).digest()
            self.assertEqual(t.pieces[i], expected)

    def test_last_piece_is_shorter(self):
        src = self._make_file("data.bin", os.urandom(16384 * 3 + 100))
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        t = tm.parse_torrent(data)
        self.assertEqual(t.num_pieces, 4)
        self.assertEqual(t.piece_size(0), 16384)
        self.assertEqual(t.piece_size(3), 100)

    def test_exact_multiple_of_piece_length(self):
        src = self._make_file("data.bin", os.urandom(16384 * 4))
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        t = tm.parse_torrent(data)
        self.assertEqual(t.num_pieces, 4)
        self.assertEqual(t.piece_size(3), 16384)

    def test_info_hash_matches_independent_bencode_computation(self):
        src = self._make_file("data.bin", os.urandom(5000))
        data = tm.create_torrent(src, "http://x/announce", piece_length=16384)
        top = bencode.decode(data)
        expected = hashlib.sha1(bencode.encode(top[b"info"])).digest()
        t = tm.parse_torrent(data)
        self.assertEqual(t.info_hash, expected)

    def test_info_hash_changes_if_content_changes(self):
        src1 = self._make_file("a.bin", b"hello world" * 100)
        src2 = self._make_file("b.bin", b"goodbye world" * 100)
        t1 = tm.parse_torrent(tm.create_torrent(src1, "http://x/announce"))
        t2 = tm.parse_torrent(tm.create_torrent(src2, "http://x/announce"))
        self.assertNotEqual(t1.info_hash, t2.info_hash)

    def test_empty_file_rejected(self):
        src = self._make_file("empty.bin", b"")
        with self.assertRaises(tm.TorrentError):
            tm.create_torrent(src, "http://x/announce")

    def test_missing_file_rejected(self):
        with self.assertRaises(tm.TorrentError):
            tm.create_torrent(os.path.join(self.tmpdir, "nope.bin"), "http://x/announce")

    def test_parse_rejects_malformed_pieces_length(self):
        top = {
            b"announce": b"http://x/announce",
            b"info": {b"name": b"x", b"piece length": 16384, b"pieces": b"x" * 19, b"length": 100},
        }
        with self.assertRaises(tm.TorrentError):
            tm.parse_torrent(bencode.encode(top))

    def test_parse_rejects_piece_count_mismatch(self):
        # 'length' implies 2 pieces at this piece_length, but 'pieces' only has 1
        top = {
            b"announce": b"http://x/announce",
            b"info": {b"name": b"x", b"piece length": 10, b"pieces": b"\0" * 20, b"length": 15},
        }
        with self.assertRaises(tm.TorrentError):
            tm.parse_torrent(bencode.encode(top))

    def test_parse_rejects_not_bencode(self):
        with self.assertRaises(tm.TorrentError):
            tm.parse_torrent(b"this is not bencode")

    def test_parse_rejects_missing_info(self):
        top = {b"announce": b"http://x/announce"}
        with self.assertRaises(tm.TorrentError):
            tm.parse_torrent(bencode.encode(top))


if __name__ == "__main__":
    unittest.main()
