import hashlib
import os
import tempfile
import unittest

from swarm import bencode, torrentfile


class TestTorrentFile(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.tmpdir, "data.bin")
        with open(self.file_path, "wb") as f:
            f.write(os.urandom(1000))

    def test_piece_count_and_sizes(self):
        info = torrentfile.create_torrent(self.file_path, announce="http://x/announce", piece_length=300)
        self.assertEqual(info.length, 1000)
        self.assertEqual(info.num_pieces, 4)  # 300,300,300,100
        self.assertEqual(info.piece_size(0), 300)
        self.assertEqual(info.piece_size(3), 100)
        self.assertEqual(sum(info.piece_size(i) for i in range(info.num_pieces)), 1000)

    def test_piece_hashes_match_content(self):
        info = torrentfile.create_torrent(self.file_path, announce="http://x/announce", piece_length=300)
        with open(self.file_path, "rb") as f:
            data = f.read()
        for i in range(info.num_pieces):
            start = i * 300
            chunk = data[start : start + info.piece_size(i)]
            self.assertEqual(info.piece_hash(i), hashlib.sha1(chunk).digest())

    def test_info_hash_is_sha1_of_bencoded_info_dict(self):
        info = torrentfile.create_torrent(self.file_path, announce="http://x/announce", piece_length=300)
        expected = hashlib.sha1(bencode.encode(info.info_dict())).digest()
        self.assertEqual(info.info_hash(), expected)

    def test_save_and_load_roundtrip(self):
        info = torrentfile.create_torrent(self.file_path, announce="http://x/announce", piece_length=300)
        out = os.path.join(self.tmpdir, "out.torrent")
        torrentfile.save_torrent(info, out)
        loaded = torrentfile.load_torrent(out)
        self.assertEqual(loaded, info)
        self.assertEqual(loaded.info_hash(), info.info_hash())

    def test_deterministic_across_two_independent_builds(self):
        # Same file, two independent create_torrent calls -> identical info_hash,
        # the property real peers rely on to agree they're in the same swarm.
        info1 = torrentfile.create_torrent(self.file_path, announce="http://a/announce", piece_length=300)
        info2 = torrentfile.create_torrent(self.file_path, announce="http://b/announce", piece_length=300)
        self.assertEqual(info1.info_hash(), info2.info_hash())  # announce URL isn't part of info dict

    def test_empty_file_rejected(self):
        empty = os.path.join(self.tmpdir, "empty.bin")
        open(empty, "wb").close()
        with self.assertRaises(ValueError):
            torrentfile.create_torrent(empty, announce="http://x/announce")

    def test_negative_piece_length_rejected(self):
        with self.assertRaises(ValueError):
            torrentfile.create_torrent(self.file_path, announce="http://x/announce", piece_length=0)

    def test_exact_multiple_of_piece_length(self):
        path = os.path.join(self.tmpdir, "exact.bin")
        with open(path, "wb") as f:
            f.write(os.urandom(600))
        info = torrentfile.create_torrent(path, announce="http://x/announce", piece_length=300)
        self.assertEqual(info.num_pieces, 2)
        self.assertEqual(info.piece_size(1), 300)

    def test_parse_rejects_malformed_metainfo(self):
        with self.assertRaises(ValueError):
            torrentfile.parse_torrent(bencode.encode({b"not_info": 1}))

    def test_parse_rejects_bad_pieces_length(self):
        bad = {
            b"announce": b"http://x/announce",
            b"info": {b"name": b"f", b"piece length": 10, b"pieces": b"short", b"length": 10},
        }
        with self.assertRaises(ValueError):
            torrentfile.parse_torrent(bencode.encode(bad))


if __name__ == "__main__":
    unittest.main()
