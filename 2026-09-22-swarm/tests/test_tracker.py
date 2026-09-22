import unittest

from swarm import tracker


class TestSwarmTable(unittest.TestCase):
    def test_announce_returns_other_peers_only(self):
        table = tracker.SwarmTable(interval=60)
        info_hash = b"H" * 20
        peers = table.announce(info_hash, b"A" * 20, "127.0.0.1", 1111, left=100, event="started")
        self.assertEqual(peers, [])  # first peer sees nobody yet
        peers_for_b = table.announce(info_hash, b"B" * 20, "127.0.0.1", 2222, left=100, event="started")
        self.assertEqual([p[0] for p in peers_for_b], [b"A" * 20])
        peers_for_a_again = table.announce(info_hash, b"A" * 20, "127.0.0.1", 1111, left=0, event=None)
        self.assertEqual([p[0] for p in peers_for_a_again], [b"B" * 20])

    def test_swarms_are_isolated_by_info_hash(self):
        table = tracker.SwarmTable(interval=60)
        table.announce(b"H" * 20, b"A" * 20, "127.0.0.1", 1, left=1, event="started")
        peers = table.announce(b"X" * 20, b"B" * 20, "127.0.0.1", 2, left=1, event="started")
        self.assertEqual(peers, [])  # different info_hash -> different swarm, A invisible here

    def test_stopped_event_removes_peer(self):
        table = tracker.SwarmTable(interval=60)
        info_hash = b"H" * 20
        table.announce(info_hash, b"A" * 20, "127.0.0.1", 1, left=1, event="started")
        table.announce(info_hash, b"A" * 20, "127.0.0.1", 1, left=0, event="stopped")
        peers = table.announce(info_hash, b"B" * 20, "127.0.0.1", 2, left=1, event="started")
        self.assertEqual(peers, [])

    def test_stale_peer_expires(self):
        table = tracker.SwarmTable(interval=0)  # expires immediately on the next announce
        info_hash = b"H" * 20
        table.announce(info_hash, b"A" * 20, "127.0.0.1", 1, left=1, event="started")
        import time

        time.sleep(0.01)
        peers = table.announce(info_hash, b"B" * 20, "127.0.0.1", 2, left=1, event="started")
        self.assertEqual(peers, [])  # A should have expired

    def test_scrape_counts_complete_vs_incomplete(self):
        table = tracker.SwarmTable(interval=60)
        info_hash = b"H" * 20
        table.announce(info_hash, b"A" * 20, "127.0.0.1", 1, left=0, event="started")  # seed
        table.announce(info_hash, b"B" * 20, "127.0.0.1", 2, left=500, event="started")  # leecher
        complete, incomplete = table.scrape(info_hash)
        self.assertEqual((complete, incomplete), (1, 1))


class TestCompactPeerPacking(unittest.TestCase):
    def test_pack_and_unpack_roundtrip(self):
        peers = [(b"A" * 20, "127.0.0.1", 6881), (b"B" * 20, "10.0.0.5", 51413)]
        packed = tracker._pack_compact_peers(peers)
        self.assertEqual(len(packed), 12)  # 6 bytes per peer
        import socket
        import struct

        unpacked = []
        for i in range(0, len(packed), 6):
            chunk = packed[i : i + 6]
            ip = socket.inet_ntoa(chunk[:4])
            (port,) = struct.unpack(">H", chunk[4:6])
            unpacked.append((ip, port))
        self.assertEqual(unpacked, [("127.0.0.1", 6881), ("10.0.0.5", 51413)])


class TestLiveTrackerHTTP(unittest.TestCase):
    """Exercise the real HTTP server end to end -- actual sockets, actual
    bencode over the wire, not just the in-memory SwarmTable."""

    def setUp(self):
        self.server = tracker.run_tracker("127.0.0.1", 0, interval=60)
        self.addCleanup(self._teardown)

    def _teardown(self):
        self.server.shutdown()
        self.server.server_close()

    def _url(self):
        return f"http://127.0.0.1:{self.server.server_port}/announce"

    def test_announce_roundtrip_compact(self):
        info_hash = b"\x01" * 20
        interval, peers = tracker.announce(self._url(), info_hash, b"A" * 20, port=6881, left=0, event="started", compact=True)
        self.assertEqual(peers, [])
        interval, peers = tracker.announce(self._url(), info_hash, b"B" * 20, port=6882, left=100, event="started", compact=True)
        self.assertEqual(peers, [("127.0.0.1", 6881)])

    def test_announce_roundtrip_noncompact(self):
        info_hash = b"\x02" * 20
        tracker.announce(self._url(), info_hash, b"A" * 20, port=7001, left=0, event="started", compact=False)
        _, peers = tracker.announce(self._url(), info_hash, b"B" * 20, port=7002, left=1, event="started", compact=False)
        self.assertEqual(peers, [("127.0.0.1", 7001)])

    def test_malformed_announce_returns_failure(self):
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{self.server.server_port}/announce?info_hash=short&peer_id=alsoshort&port=1"
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(url, timeout=5)
        self.assertEqual(cm.exception.code, 400)

    def test_unknown_endpoint_404(self):
        import urllib.error
        import urllib.request

        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}/nope", timeout=5)
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
