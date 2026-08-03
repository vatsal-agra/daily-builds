import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import free_addr
from undertow.segment import FLAG_ACK, FLAG_PSH, Segment
from undertow.socket_ import ESTABLISHED, MAX_RETRANSMITS, ConnectionError_, MiniTCPSocket


class TestHandshakeAndTeardown(unittest.TestCase):
    def test_connect_accept_reach_established_directly(self):
        client_addr, server_addr = free_addr(), free_addr()
        server = MiniTCPSocket(server_addr, name="server")
        server.listen()
        result = {}

        def do_accept():
            server.accept(timeout=10)
            result["server_state"] = server.state

        t = threading.Thread(target=do_accept)
        t.start()

        client = MiniTCPSocket(client_addr, name="client")
        client.connect(server_addr, timeout=10)
        t.join(timeout=10)

        self.assertEqual(client.state, ESTABLISHED)
        self.assertEqual(result.get("server_state"), ESTABLISHED)

        # Both sides must close for either close() to complete: it waits
        # for its own FIN to be acked *and* for the peer's FIN to arrive,
        # so the two closes need to happen concurrently, not sequentially.
        tc = threading.Thread(target=lambda: client.close(timeout=10))
        ts = threading.Thread(target=lambda: server.close(timeout=10))
        tc.start()
        ts.start()
        tc.join(timeout=10)
        ts.join(timeout=10)
        self.assertEqual(client.state, "CLOSED")
        self.assertEqual(server.state, "CLOSED")

    def test_both_sides_reach_closed_after_graceful_close(self):
        client_addr, server_addr = free_addr(), free_addr()
        server = MiniTCPSocket(server_addr, name="server")
        server.listen()

        t = threading.Thread(target=lambda: server.accept(timeout=10))
        t.start()
        client = MiniTCPSocket(client_addr, name="client")
        client.connect(server_addr, timeout=10)
        t.join(timeout=10)

        server_recv = {}

        def do_server_close():
            server.recv_all(timeout=10)  # blocks until client's FIN
            server.close(timeout=10)
            server_recv["state"] = server.state

        ts = threading.Thread(target=do_server_close)
        ts.start()

        client.send(b"hello")
        client.close(timeout=10)
        ts.join(timeout=10)

        self.assertEqual(client.state, "CLOSED")
        self.assertEqual(server_recv.get("state"), "CLOSED")

    def test_connect_without_listener_times_out(self):
        client_addr = free_addr()
        dead_addr = free_addr()  # nothing bound/listening here
        client = MiniTCPSocket(client_addr, name="client")
        with self.assertRaises(TimeoutError):
            client.connect(dead_addr, timeout=0.5)
        client._running = False
        client.udp.close()

    def test_concurrent_close_calls_do_not_hang_or_error(self):
        # A second close() call (e.g. an app closing from two code paths,
        # or retrying after a transient error) used to send a *second*
        # FIN at a stale sequence number that the peer would never ack,
        # hanging until the timeout instead of converging cleanly.
        client_addr, server_addr = free_addr(), free_addr()
        server = MiniTCPSocket(server_addr, name="server")
        server.listen()
        t = threading.Thread(target=lambda: server.accept(timeout=10))
        t.start()
        client = MiniTCPSocket(client_addr, name="client")
        client.connect(server_addr, timeout=10)
        t.join(timeout=10)

        errors = []

        def do_close():
            try:
                client.close(timeout=5)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        c1 = threading.Thread(target=do_close)
        c2 = threading.Thread(target=do_close)
        ts = threading.Thread(target=lambda: server.close(timeout=5))
        c1.start()
        c2.start()
        ts.start()
        c1.join(timeout=6)
        c2.join(timeout=6)
        ts.join(timeout=6)

        self.assertEqual(errors, [])
        self.assertEqual(client.state, "CLOSED")
        self.assertEqual(server.state, "CLOSED")

    def test_segment_from_unknown_source_is_rejected(self):
        # Once a peer address is learned, a datagram from anywhere else
        # must be ignored — otherwise anything else on the loopback that
        # guesses the (unauthenticated) sequence numbers could inject data
        # into an active connection.
        client_addr, server_addr = free_addr(), free_addr()
        server = MiniTCPSocket(server_addr, name="server")
        server.listen()
        t = threading.Thread(target=lambda: server.accept(timeout=10))
        t.start()
        client = MiniTCPSocket(client_addr, name="client")
        client.connect(server_addr, timeout=10)
        t.join(timeout=10)

        forger = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        forger.bind(("127.0.0.1", 0))
        try:
            forged = Segment(seq=999_999, ack=0, flags=FLAG_PSH | FLAG_ACK, payload=b"INJECTED")
            forger.sendto(forged.encode(), server_addr)
            time.sleep(0.3)
            with server.lock:
                self.assertEqual(bytes(server.recv_queue), b"")
        finally:
            forger.close()
            client._running = False
            server._running = False
            client.udp.close()
            server.udp.close()

    def test_giving_up_sends_rst_so_peer_does_not_hang_forever(self):
        # If retransmits are exhausted, the peer must be told (a RST) —
        # otherwise it just blocks in recv()/close() until its own
        # timeout with no way to know the connection actually died.
        client_addr, server_addr = free_addr(), free_addr()
        server = MiniTCPSocket(server_addr, name="server")
        server.listen()
        t = threading.Thread(target=lambda: server.accept(timeout=10))
        t.start()
        client = MiniTCPSocket(client_addr, name="client")
        client.connect(server_addr, timeout=10)
        t.join(timeout=10)

        client.send(b"z" * 10)
        time.sleep(0.2)  # let the first send drain normally

        with client.lock:
            client.peer_addr = ("127.0.0.1", 1)  # black hole
        client.send(b"y" * 10)
        time.sleep(0.3)
        with client.lock:
            for entry in client.unacked.values():
                entry.retransmit_count = MAX_RETRANSMITS
                entry.last_send_time = 0
            client.peer_addr = server_addr  # restore so the RST can land

        deadline = time.monotonic() + 3.0
        while server.error is None and time.monotonic() < deadline:
            time.sleep(0.02)

        self.assertIsNotNone(client.error)
        self.assertIn("gave up", client.error)
        self.assertEqual(server.error, "connection reset by peer")
        # Already-buffered data (from the first, successful send) is still
        # delivered — a RST doesn't discard what was already received,
        # same as a real socket. Only once that's drained does the next
        # recv() surface the error.
        self.assertEqual(server.recv(timeout=1), b"z" * 10)
        with self.assertRaises(ConnectionError_):
            server.recv(timeout=1)

        client._running = False
        server._running = False
        client.udp.close()
        server.udp.close()


if __name__ == "__main__":
    unittest.main()
