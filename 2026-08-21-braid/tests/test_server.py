import base64
import json
import os
import socket
import struct
import threading
import time
import unittest
import urllib.request

from server import ws
from server.braid_server import BraidServer


class TinyWSClient:
    """Minimal RFC 6455 client using the project's own frame codec."""

    def __init__(self, host, port, path):
        self.sock = socket.create_connection((host, port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        self.sock.sendall(req)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("handshake failed")
            buf += chunk
        assert b"101" in buf.splitlines()[0], buf

    def send(self, obj):
        payload = json.dumps(obj).encode()
        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        if length <= 125:
            header = bytes([0x81, 0x80 | length])
        elif length <= 0xFFFF:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", length)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", length)
        self.sock.sendall(header + mask_key + masked)

    def recv(self, timeout=5):
        self.sock.settimeout(timeout)
        opcode, payload, fin = ws.decode_frame(self.sock)
        return json.loads(payload.decode())

    def recv_until(self, predicate, timeout=5, max_messages=20):
        deadline = time.time() + timeout
        for _ in range(max_messages):
            remaining = max(0.05, deadline - time.time())
            msg = self.recv(timeout=remaining)
            if predicate(msg):
                return msg
        raise TimeoutError("predicate never matched")

    def close(self):
        self.sock.close()


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BraidServerTestCase(unittest.TestCase):
    """Spins up one real BraidServer per test class on a free port."""

    anti_entropy_every_n_ticks = 100

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.server = BraidServer(
            "127.0.0.1", cls.port, seed=1, anti_entropy_every_n_ticks=cls.anti_entropy_every_n_ticks
        )
        cls.thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def room(self, name_prefix="room"):
        return f"{name_prefix}-{os.getpid()}-{time.time_ns()}"


class TestBasicIntegration(BraidServerTestCase):
    def test_static_files_served(self):
        for path in ("/", "/app.js", "/rga.js", "/style.css"):
            resp = urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(resp.status, 200)

    def test_bootstrap_presence_and_realtime_delivery(self):
        room = self.room()
        alice = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=alice")
        boot = alice.recv()
        self.assertEqual(boot["type"], "bootstrap")
        self.assertEqual(boot["ops"], [])

        bob = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=bob")
        self.assertEqual(bob.recv()["type"], "bootstrap")

        pres = alice.recv_until(lambda m: m["type"] == "presence" and set(m["peers"]) == {"alice", "bob"})
        self.assertEqual(set(pres["peers"]), {"alice", "bob"})

        alice.send({"type": "insert", "id": [1, "alice"], "parent": None, "value": "h", "deps": []})
        alice.send({"type": "insert", "id": [2, "alice"], "parent": [1, "alice"], "value": "i", "deps": [[1, "alice"]]})

        got = []
        deadline = time.time() + 3
        while len(got) < 2 and time.time() < deadline:
            msg = bob.recv(timeout=3)
            if msg["type"] == "insert":
                got.append(msg)
        self.assertEqual(len(got), 2)
        values = sorted((tuple(m["id"]), m["value"]) for m in got)
        self.assertEqual(values, [((1, "alice"), "h"), ((2, "alice"), "i")])

        carol = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=carol")
        boot_c = carol.recv()
        self.assertEqual(sorted(tuple(o["id"]) for o in boot_c["ops"]), [(1, "alice"), (2, "alice")])

        for c in (alice, bob, carol):
            c.close()

    def test_chaos_api_reports_clamped_values(self):
        room = self.room()
        url = f"http://127.0.0.1:{self.port}/api/chaos?room={room}&loss=99&dup=-5&lat_min=10&lat_max=5"
        data = json.loads(urllib.request.urlopen(url).read())
        self.assertEqual(data["loss_p"], 1.0)
        self.assertEqual(data["dup_p"], 0.0)
        self.assertEqual(data["latency_range"], [5, 10])  # swapped back into order, not crashed

    def test_server_survives_malformed_chaos_request(self):
        room = self.room()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/chaos?room={room}&loss=notanumber")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
        # server must still be alive and answering for an unrelated room
        resp = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/")
        self.assertEqual(resp.status, 200)


class TestSlowClientIsolation(BraidServerTestCase):
    def test_slow_client_does_not_block_room(self):
        room = self.room()
        # a peer that completes the handshake but never reads again --
        # its OS receive buffer will eventually back up
        stalled_sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        stalled_sock.sendall(
            (f"GET /ws?room={room}&peer=stalled HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
             f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += stalled_sock.recv(1)
        # never call recv() again on stalled_sock from here on

        healthy = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=healthy")
        healthy.recv()  # bootstrap
        healthy.recv_until(lambda m: m["type"] == "presence" and "stalled" in m["peers"])

        # flood enough traffic toward the stalled peer to fill real OS
        # socket buffers, then confirm the healthy peer still gets its
        # own op quickly -- proving the stall isn't blocking the room
        sender = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=sender")
        sender.recv()
        sender.recv_until(lambda m: m["type"] == "presence" and set(m["peers"]) >= {"stalled", "healthy", "sender"})

        prev_id = None
        for i in range(400):
            node_id = [i + 1, "sender"]
            sender.send({"type": "insert", "id": node_id, "parent": prev_id, "value": "x",
                         "deps": [] if prev_id is None else [prev_id]})
            prev_id = node_id

        start = time.time()
        got_inserts = 0
        deadline = start + 5
        while got_inserts < 400 and time.time() < deadline:
            msg = healthy.recv(timeout=5)
            if msg["type"] == "insert":
                got_inserts += 1
        elapsed = time.time() - start

        self.assertEqual(got_inserts, 400, "healthy peer should receive every op")
        self.assertLess(elapsed, 4.0, "delivery to the healthy peer should not be stalled by the frozen peer")

        stalled_sock.close()
        healthy.close()
        sender.close()


class TestAntiEntropyLive(BraidServerTestCase):
    # Fast enough that the test doesn't take real minutes, but slow enough
    # (~1s) to stay clearly distinguishable from the "did NOT arrive via
    # the direct lossy path yet" check below, which uses a much shorter
    # window -- too fast an interval here would race that check.
    anti_entropy_every_n_ticks = 25

    def test_loss_recovers_via_anti_entropy_without_reconnect(self):
        room = self.room()
        # crank loss to ~100% for the fan-out so the live insert never
        # reaches the second peer via the normal chaotic path
        urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/chaos?room={room}&loss=1.0")

        a = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=a")
        a.recv()
        b = TinyWSClient("127.0.0.1", self.port, f"/ws?room={room}&peer=b")
        b.recv()
        # drain both sides' own startup presence messages fully so the
        # "didn't arrive quickly" check below can't mistake a queued
        # presence update for the (not yet sent) insert op
        a.recv_until(lambda m: m["type"] == "presence" and set(m["peers"]) == {"a", "b"})
        b.recv_until(lambda m: m["type"] == "presence" and set(m["peers"]) == {"a", "b"})

        a.send({"type": "insert", "id": [1, "a"], "parent": None, "value": "Q", "deps": []})

        # confirm it really did NOT arrive via the normal path (loss=1.0);
        # window is well under the anti-entropy interval above so this
        # isn't racing the periodic resync
        with self.assertRaises((socket.timeout, TimeoutError)):
            b.recv(timeout=0.3)

        # now heal loss for FUTURE sends, but do NOT resend -- the only
        # way b can recover this specific already-lost op is the
        # periodic anti-entropy resync pushing the room's reliable state
        urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/chaos?room={room}&loss=0")

        resync = b.recv_until(lambda m: m["type"] == "resync" and any(o["type"] == "insert" for o in m["ops"]), timeout=6)
        values = [o["value"] for o in resync["ops"] if o["type"] == "insert"]
        self.assertIn("Q", values, "anti-entropy should have delivered the previously-lost op")

        a.close()
        b.close()


if __name__ == "__main__":
    unittest.main()
