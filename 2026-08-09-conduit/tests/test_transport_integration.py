"""Integration tests: real ConduitSocket client/server pairs over real
loopback UDP sockets, several of them routed *through* NetworkSimulator
so the reliability layer is proven against genuine packet loss,
reordering, and duplication rather than a clean network.
"""

import hashlib
import threading
import time
import unittest

from conduit.api import Listener, connect
from conduit.netsim import NetworkSimulator
from conduit.transport import ConduitTimeout


def run_server(listener, expected_len, out, accept_timeout=5.0, recv_timeout=8.0):
    conn = listener.accept(timeout=accept_timeout)
    data = bytearray()
    try:
        while len(data) < expected_len:
            chunk = conn.recv(65536, timeout=recv_timeout)
            if not chunk:
                break
            data.extend(chunk)
    finally:
        out["data"] = bytes(data)
        out["conn"] = conn
        conn.close()


class TestCleanNetwork(unittest.TestCase):
    def test_small_message_roundtrip(self):
        listener = Listener(("127.0.0.1", 0))
        try:
            out = {}
            t = threading.Thread(target=run_server, args=(listener, 13, out))
            t.start()
            client = connect(listener.local_addr, timeout=5.0)
            client.sendall(b"hello, world!")
            client.close()
            t.join(timeout=10)
            self.assertEqual(out["data"], b"hello, world!")
        finally:
            listener.close()

    def test_bidirectional_data(self):
        listener = Listener(("127.0.0.1", 0))
        try:
            server_holder = {}

            def server():
                conn = listener.accept(timeout=5.0)
                msg = conn.recv_exact(5, timeout=5.0)
                conn.sendall(b"ack:" + msg)
                conn.close()
                server_holder["msg"] = msg

            t = threading.Thread(target=server)
            t.start()
            client = connect(listener.local_addr, timeout=5.0)
            client.sendall(b"ping!")
            reply = client.recv_exact(9, timeout=5.0)
            client.close()
            t.join(timeout=10)
            self.assertEqual(reply, b"ack:ping!")
        finally:
            listener.close()

    def test_large_transfer_exact_bytes(self):
        listener = Listener(("127.0.0.1", 0))
        try:
            payload = bytes((i * 2654435761 + 17) % 256 for i in range(300_000))
            out = {}
            t = threading.Thread(target=run_server, args=(listener, len(payload), out))
            t.start()
            client = connect(listener.local_addr, timeout=5.0)
            client.sendall(payload)
            client.close()
            t.join(timeout=20)
            self.assertEqual(len(out["data"]), len(payload))
            self.assertEqual(out["data"], payload)
        finally:
            listener.close()

    def test_multiple_sequential_connections(self):
        listener = Listener(("127.0.0.1", 0))
        try:
            for i in range(3):
                out = {}
                msg = f"connection number {i}".encode()
                t = threading.Thread(target=run_server, args=(listener, len(msg), out))
                t.start()
                client = connect(listener.local_addr, timeout=5.0)
                client.sendall(msg)
                client.close()
                t.join(timeout=10)
                self.assertEqual(out["data"], msg)
        finally:
            listener.close()


class TestLossyNetwork(unittest.TestCase):
    """Every test here routes through NetworkSimulator with real fault
    injection — this is the core claim of the project under test."""

    def _run_transfer(self, payload, loss, dup_prob, reorder_prob, seed,
                       delay=0.003, jitter=0.002, reorder_delay=0.02, timeout=25.0):
        listener = Listener(("127.0.0.1", 0))
        sim = NetworkSimulator(
            ("127.0.0.1", 0), listener.local_addr, loss=loss, dup_prob=dup_prob,
            reorder_prob=reorder_prob, reorder_delay=reorder_delay, delay=delay,
            jitter=jitter, seed=seed,
        )
        try:
            out = {}
            t = threading.Thread(target=run_server, args=(listener, len(payload), out),
                                  kwargs={"recv_timeout": timeout})
            t.start()
            client = connect(sim.local_addr, timeout=timeout)
            client.sendall(payload)
            client.close()
            t.join(timeout=timeout + 5)
            self.assertFalse(t.is_alive(), "server thread never finished")
            return out.get("data", b""), sim.stats
        finally:
            sim.close()
            listener.close()

    def test_moderate_loss_delivers_exact_bytes(self):
        payload = hashlib.sha256(b"conduit-seed-1").digest() * 4000  # 128,000 bytes
        got, stats = self._run_transfer(payload, loss=0.03, dup_prob=0.01, reorder_prob=0.03, seed=1)
        self.assertEqual(got, payload)
        self.assertGreater(stats["dropped"], 0, "test is meaningless if netsim never actually dropped anything")

    def test_high_loss_still_delivers_exact_bytes(self):
        payload = hashlib.sha256(b"conduit-seed-2").digest() * 2000  # 64,000 bytes
        got, stats = self._run_transfer(payload, loss=0.15, dup_prob=0.0, reorder_prob=0.0, seed=2, timeout=40.0)
        self.assertEqual(got, payload)
        self.assertGreater(stats["dropped"], 5)

    def test_reordering_only_delivers_in_order(self):
        payload = bytes(range(256)) * 500  # 128,000 bytes, highly structured — reordering bugs show up fast
        got, stats = self._run_transfer(payload, loss=0.0, dup_prob=0.0, reorder_prob=0.35,
                                         reorder_delay=0.05, seed=3)
        self.assertEqual(got, payload)
        self.assertGreater(stats["reordered"], 0)

    def test_duplication_only_no_corruption(self):
        payload = hashlib.sha256(b"conduit-seed-4").digest() * 1000  # 32,000 bytes
        got, stats = self._run_transfer(payload, loss=0.0, dup_prob=0.2, reorder_prob=0.0, seed=4)
        self.assertEqual(got, payload)
        self.assertGreater(stats["duplicated"], 0)

    def test_combined_chaos(self):
        payload = hashlib.sha256(b"conduit-seed-5").digest() * 3000  # 96,000 bytes
        got, stats = self._run_transfer(payload, loss=0.05, dup_prob=0.03, reorder_prob=0.08,
                                         reorder_delay=0.03, seed=5, timeout=40.0)
        self.assertEqual(got, payload)


class TestConnectionLifecycle(unittest.TestCase):
    """Regression tests for bugs found during adversarial review."""

    def test_failed_connect_does_not_leak_threads(self):
        # Nothing is listening on this port — connect() must time out and
        # clean up its reader thread + UDP socket rather than leaking them.
        # (Compares thread *names*, not counts: other tests' background
        # threads may be winding down concurrently in the same process,
        # which makes a raw active_count() comparison flaky.)
        before_names = {t.name for t in threading.enumerate()}
        with self.assertRaises(ConduitTimeout):
            connect(("127.0.0.1", 1), timeout=1.0)
        time.sleep(0.3)
        after_names = {t.name for t in threading.enumerate()}
        leaked = {n for n in (after_names - before_names) if "conduit-client" in n}
        self.assertFalse(leaked, f"leaked threads: {leaked}")

    def test_double_close_is_safe(self):
        listener = Listener(("127.0.0.1", 0))
        try:
            out = {}
            t = threading.Thread(target=run_server, args=(listener, 5, out))
            t.start()
            client = connect(listener.local_addr, timeout=5.0)
            client.sendall(b"hello")
            client.close()
            client.close()  # must not raise
            t.join(timeout=10)
            self.assertEqual(out["data"], b"hello")
        finally:
            listener.close()

    def test_passive_close_reaches_closed_final(self):
        # Exercises CLOSE_WAIT -> LAST_ACK -> CLOSED_FINAL on the server
        # side (the side that did NOT initiate close()).
        listener = Listener(("127.0.0.1", 0))
        try:
            server_conn = {}

            def server():
                conn = listener.accept(timeout=5.0)
                server_conn["conn"] = conn
                conn.recv_exact(4, timeout=5.0)
                time.sleep(0.2)  # let the client's FIN arrive and put us in CLOSE_WAIT
                conn.close()

            t = threading.Thread(target=server)
            t.start()
            client = connect(listener.local_addr, timeout=5.0)
            client.sendall(b"ping")
            client.close()
            t.join(timeout=10)
            self.assertEqual(server_conn["conn"].state, "CLOSED_FINAL")
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
