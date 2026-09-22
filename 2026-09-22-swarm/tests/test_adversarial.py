"""Regression tests for issues found during Phase 3's adversarial review:
a hostile or simply buggy peer/torrent should never crash this node or
extract more than it's entitled to."""
import os
import tempfile
import unittest

from swarm import piecemanager, torrentfile
from swarm.piecemanager import PieceManager


def _make_torrent(tmpdir, size=900, piece_length=300, name="src.bin"):
    path = os.path.join(tmpdir, name)
    with open(path, "wb") as f:
        f.write(os.urandom(size))
    info = torrentfile.create_torrent(path, announce="http://x/announce", piece_length=piece_length)
    return path, info


class TestTorrentInfoValidation(unittest.TestCase):
    def test_rejects_length_inconsistent_with_pieces(self):
        with self.assertRaises(ValueError):
            torrentfile.TorrentInfo(
                name="f", piece_length=100, length=1000, pieces=b"\x00" * 20, announce="http://x"  # only 1 piece hash but length implies 10
            )

    def test_rejects_zero_piece_length(self):
        with self.assertRaises(ValueError):
            torrentfile.TorrentInfo(name="f", piece_length=0, length=100, pieces=b"\x00" * 20, announce="http://x")

    def test_rejects_zero_length(self):
        with self.assertRaises(ValueError):
            torrentfile.TorrentInfo(name="f", piece_length=100, length=0, pieces=b"", announce="http://x")

    def test_rejects_pieces_not_multiple_of_20(self):
        with self.assertRaises(ValueError):
            torrentfile.TorrentInfo(name="f", piece_length=100, length=100, pieces=b"\x00" * 19, announce="http://x")

    def test_accepts_well_formed_torrent(self):
        info = torrentfile.TorrentInfo(name="f", piece_length=100, length=250, pieces=b"\x00" * 60, announce="http://x")
        self.assertEqual(info.num_pieces, 3)
        self.assertEqual(info.piece_size(2), 50)

    def test_malicious_torrent_bytes_rejected_at_parse_time_not_deep_in_piece_manager(self):
        from swarm import bencode

        bad = {
            b"announce": b"http://x/announce",
            b"info": {b"name": b"f", b"piece length": 100, b"pieces": b"\x00" * 20, b"length": 100000},
        }
        with self.assertRaises(ValueError):
            torrentfile.parse_torrent(bencode.encode(bad))


class TestHostilePeerInput(unittest.TestCase):
    def test_receive_block_rejects_out_of_range_piece_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, info = _make_torrent(tmp)
            pm = PieceManager(info, os.path.join(tmp, "out.bin"), seed=False)
            with self.assertRaises(ValueError):
                pm.receive_block(999999, 0, b"x", b"P" * 20)
            with self.assertRaises(ValueError):
                pm.receive_block(-1, 0, b"x", b"P" * 20)

    def test_read_block_for_upload_rejects_negative_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            pm = PieceManager(info, path, seed=True)
            with self.assertRaises(ValueError):
                pm.read_block_for_upload(0, 0, -1)

    def test_read_block_for_upload_rejects_out_of_range_piece_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            pm = PieceManager(info, path, seed=True)
            with self.assertRaises(ValueError):
                pm.read_block_for_upload(-1, 0, 10)
            with self.assertRaises(ValueError):
                pm.read_block_for_upload(info.num_pieces, 0, 10)

    def test_read_block_for_upload_rejects_overlong_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            pm = PieceManager(info, path, seed=True)
            with self.assertRaises(ValueError):
                pm.read_block_for_upload(0, 0, info.piece_size(0) + 1)

    def test_seed_with_preseed_args_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, info = _make_torrent(tmp)
            with self.assertRaises(ValueError):
                PieceManager(info, path, seed=True, preseed_source=path, preseed_pieces={0})


class TestHashFailureBan(unittest.TestCase):
    def test_peer_gets_disconnected_after_repeated_bad_hashes(self):
        # Full peer.py wiring test: a "peer" that always sends corrupt data
        # for the one piece it offers should get dropped, not retried forever.
        import socket
        import threading

        from swarm import protocol
        from swarm.node import Node

        with tempfile.TemporaryDirectory() as tmp:
            src_path, info = _make_torrent(tmp, size=300, piece_length=300, name="src.bin")  # 1 piece
            out_path = os.path.join(tmp, "out.bin")
            # A local, fast-failing (connection refused) tracker URL: this
            # test only cares about the direct peer<->peer wire exchange,
            # not tracker discovery, and an unresolvable hostname would
            # otherwise hang on a slow DNS lookup and spam warnings.
            node = Node(info, out_path, tracker_url="http://127.0.0.1:1/announce", port=0)

            def fake_malicious_peer():
                client = socket.create_connection(("127.0.0.1", node.port), timeout=2)
                try:
                    protocol.send_handshake(client, node.info_hash, b"M" * 20)
                    protocol.read_handshake(client)
                    protocol.send_message(client, protocol.bitfield(bytes([0b10000000])))
                    for _ in range(10):
                        msg = protocol.read_message(client)
                        if isinstance(msg, protocol.RequestMsg):
                            protocol.send_message(client, protocol.piece(msg.index, msg.begin, b"\x00" * msg.length))
                except (ConnectionError, OSError, protocol.ProtocolError):
                    pass  # expected once the node bans and closes on us
                finally:
                    client.close()

            t = threading.Thread(target=fake_malicious_peer, daemon=True)
            node.start()
            t.start()
            t.join(timeout=10)

            import time

            deadline = time.monotonic() + 5
            while node.connections and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(len(node.connections), 0, "malicious peer should have been disconnected")
            node.stop()


if __name__ == "__main__":
    unittest.main()
