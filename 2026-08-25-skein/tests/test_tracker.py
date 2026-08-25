"""Tests for the real HTTP tracker, exercised via real HTTP requests
against a real (localhost) ThreadingHTTPServer instance."""

import os
import socket
import struct
import sys
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote_from_bytes

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import bencode
from skein.tracker import TrackerServer, pack_compact_peers, PeerRecord


def announce(base_url, info_hash, peer_id, port, uploaded=0, downloaded=0, left=0, event=""):
    params = {
        "info_hash": info_hash, "peer_id": peer_id, "port": str(port).encode(),
        "uploaded": str(uploaded).encode(), "downloaded": str(downloaded).encode(),
        "left": str(left).encode(),
    }
    if event:
        params["event"] = event.encode()
    qs = "&".join(f"{k}={quote_from_bytes(v)}" for k, v in params.items())
    with urllib.request.urlopen(f"{base_url}/announce?{qs}", timeout=5) as resp:
        return bencode.decode(resp.read())


class TestPackCompactPeers(unittest.TestCase):
    def test_pack_format(self):
        r = PeerRecord(b"x" * 20, "10.0.0.1", 6881)
        packed = pack_compact_peers([r])
        self.assertEqual(len(packed), 6)
        self.assertEqual(packed[:4], socket.inet_aton("10.0.0.1"))
        self.assertEqual(struct.unpack(">H", packed[4:6])[0], 6881)


class TestTrackerServer(unittest.TestCase):
    def setUp(self):
        self.srv = TrackerServer().start()
        self.addCleanup(self.srv.stop)

    def test_first_peer_gets_empty_peer_list(self):
        info_hash = os.urandom(20)
        resp = announce(self.srv.url, info_hash, os.urandom(20), 6881, left=1000, event="started")
        self.assertEqual(resp[b"peers"], b"")
        self.assertIsInstance(resp[b"interval"], int)

    def test_second_peer_sees_first_but_not_itself(self):
        info_hash = os.urandom(20)
        pid1, pid2 = os.urandom(20), os.urandom(20)
        announce(self.srv.url, info_hash, pid1, 6001, left=1000, event="started")
        resp2 = announce(self.srv.url, info_hash, pid2, 6002, left=1000, event="started")
        self.assertEqual(len(resp2[b"peers"]), 6)  # exactly one peer (pid1)
        (port,) = struct.unpack(">H", resp2[b"peers"][4:6])
        self.assertEqual(port, 6001)

        # First peer's next announce should see the second, not itself.
        resp1b = announce(self.srv.url, info_hash, pid1, 6001, left=1000)
        self.assertEqual(len(resp1b[b"peers"]), 6)
        (port_b,) = struct.unpack(">H", resp1b[b"peers"][4:6])
        self.assertEqual(port_b, 6002)

    def test_stopped_event_removes_peer(self):
        info_hash = os.urandom(20)
        pid1, pid2 = os.urandom(20), os.urandom(20)
        announce(self.srv.url, info_hash, pid1, 6001, left=1000, event="started")
        announce(self.srv.url, info_hash, pid1, 6001, event="stopped")
        resp2 = announce(self.srv.url, info_hash, pid2, 6002, left=1000, event="started")
        self.assertEqual(resp2[b"peers"], b"")

    def test_different_info_hashes_are_isolated_swarms(self):
        ih1, ih2 = os.urandom(20), os.urandom(20)
        pid1, pid2 = os.urandom(20), os.urandom(20)
        announce(self.srv.url, ih1, pid1, 6001, left=1000, event="started")
        resp = announce(self.srv.url, ih2, pid2, 6002, left=1000, event="started")
        self.assertEqual(resp[b"peers"], b"")  # ih1's peer must not leak into ih2's swarm

    def test_missing_required_param_returns_failure(self):
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.srv.url}/announce?peer_id=x", timeout=5)

    def test_wrong_length_info_hash_returns_failure(self):
        params = {"info_hash": b"short", "peer_id": os.urandom(20), "port": b"6881"}
        qs = "&".join(f"{k}={quote_from_bytes(v)}" for k, v in params.items())
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.srv.url}/announce?{qs}", timeout=5)

    def test_unknown_endpoint_404s(self):
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.srv.url}/nonsense", timeout=5)

    def test_scrape_reports_counts(self):
        info_hash = os.urandom(20)
        pid1, pid2 = os.urandom(20), os.urandom(20)
        announce(self.srv.url, info_hash, pid1, 6001, left=0, event="started")  # seeder
        announce(self.srv.url, info_hash, pid2, 6002, left=500, event="started")  # leecher
        qs = f"info_hash={quote_from_bytes(info_hash)}"
        with urllib.request.urlopen(f"{self.srv.url}/scrape?{qs}", timeout=5) as resp:
            data = bencode.decode(resp.read())
        files = data[b"files"]
        self.assertIn(info_hash, files)
        self.assertEqual(files[info_hash][b"complete"], 1)
        self.assertEqual(files[info_hash][b"incomplete"], 1)


if __name__ == "__main__":
    unittest.main()
