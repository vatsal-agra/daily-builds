"""Adversarial demonstration of tit-for-tat: a peer that never reciprocates
should measurably get worse service than one that does -- over the real
wire protocol against a real swarm.Node, not just the pure
compute_unchoke_set() unit tests in test_choking.py.

Setup: one real Node ("target", a seed with plenty to serve and nothing it
needs) gets two independent fake-peer connections over real sockets: GOOD
always serves target's requests with real data; BAD never serves anything
back. Both declare themselves "interested." With max_unchoked=1 (forcing a
strict single choice) target's tit-for-tat choking should reciprocally
unchoke whichever peer has actually given it something -- simulated here
by crediting GOOD's bytes_downloaded_from exactly as a real transfer would
have -- while BAD, who gave target nothing, stays choked.
"""
import os
import socket
import tempfile
import threading
import time
import unittest

from swarm import protocol, torrentfile
from swarm.choking import TitForTatChokePolicy
from swarm.node import Node


class _FakePeer:
    """A hand-rolled BEP-3 speaker over a real socket -- not swarm's own
    PeerConnection -- so the target Node is genuinely tested against an
    independent wire implementation."""

    def __init__(self, target_port: int, info_hash: bytes, peer_id: bytes, have_bits: bytes, serve: bool, source: bytes):
        self.sock = socket.create_connection(("127.0.0.1", target_port), timeout=10)
        self.peer_id = peer_id
        self.serve = serve
        self.source = source
        self.bytes_served = 0
        protocol.send_handshake(self.sock, info_hash, peer_id)
        protocol.read_handshake(self.sock)
        protocol.send_message(self.sock, protocol.bitfield(have_bits))
        protocol.send_message(self.sock, protocol.interested())
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            while not self._stop:
                msg = protocol.read_message(self.sock)
                if isinstance(msg, protocol.RequestMsg) and self.serve:
                    block = self.source[msg.begin : msg.begin + msg.length]
                    protocol.send_message(self.sock, protocol.piece(msg.index, msg.begin, block))
                    self.bytes_served += len(block)
                # BAD (serve=False) silently drops every request, exactly
                # like a peer that never uploads.
        except (ConnectionError, OSError, protocol.ProtocolError):
            pass

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


class TestFreeloaderGetsWorseService(unittest.TestCase):
    def test_reciprocating_peer_gets_unchoked_over_freeloader(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_path = os.path.join(tmp, "src.bin")
            data = os.urandom(64 * 1024 * 6)  # 6 pieces
            with open(src_path, "wb") as f:
                f.write(data)
            info = torrentfile.create_torrent(src_path, announce="http://127.0.0.1:1/announce", piece_length=64 * 1024)

            # target starts with everything -- it has plenty to serve and
            # nothing it needs, isolating the choking decision (who target
            # chooses to serve) from any download-side behavior of its own.
            target = Node(
                info,
                src_path,
                tracker_url="http://127.0.0.1:1/announce",
                seed=True,
                choke_policy=TitForTatChokePolicy(max_unchoked=1, optimistic_slots=0, seed=0),
                choke_interval=0.15,
            )
            target.start()
            self.addCleanup(target.stop)

            full_bits = bytes([0xFF] * ((info.num_pieces + 7) // 8))
            good = _FakePeer(target.port, target.info_hash, b"G" * 20, full_bits, serve=True, source=data)
            bad = _FakePeer(target.port, target.info_hash, b"B" * 20, full_bits, serve=False, source=data)
            self.addCleanup(good.close)
            self.addCleanup(bad.close)

            # A seed never actually requests anything, so
            # bytes_downloaded_from never grows for either peer through the
            # real request/piece path in this setup. Simulate GOOD as a
            # peer that keeps steadily giving us data -- a background
            # thread bumps its counter every tick, the same shape a real
            # ongoing transfer would produce -- and let the already-running
            # choke loop (driven by the real PeerConnection.peer_interested
            # state) react on its own schedule. A one-time lump credit was
            # tried first and is deliberately *not* what this does: the
            # policy measures rate (bytes since the last sample), not a
            # cumulative total, so a single one-off credit only wins
            # exactly one tick and then looks identical to having given
            # nothing at all -- which is correct tit-for-tat behavior (a
            # peer that reciprocated once and then went quiet shouldn't
            # keep permanent priority), but means the test has to model a
            # *sustained* difference to observe a sustained outcome.
            time.sleep(0.3)  # let both connections finish registering as interested
            stop_feed = threading.Event()

            def keep_crediting_good():
                total = 0
                while not stop_feed.is_set():
                    total += 50_000
                    target.piece_manager.bytes_downloaded_from[b"G" * 20] = total
                    time.sleep(0.05)

            feeder = threading.Thread(target=keep_crediting_good, daemon=True)
            feeder.start()
            self.addCleanup(stop_feed.set)
            time.sleep(0.6)  # several choke-loop ticks to react and settle

            good_conn = target.connections.get(b"G" * 20)
            bad_conn = target.connections.get(b"B" * 20)
            self.assertIsNotNone(good_conn, "GOOD's connection should still be registered")
            self.assertIsNotNone(bad_conn, "BAD's connection should still be registered")
            self.assertFalse(good_conn.am_choking, "the reciprocating peer should be unchoked")
            self.assertTrue(bad_conn.am_choking, "the freeloader should still be choked")


if __name__ == "__main__":
    unittest.main()
