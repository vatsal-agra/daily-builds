import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import free_addr
from undertow.socket_ import ESTABLISHED, MiniTCPSocket


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


if __name__ == "__main__":
    unittest.main()
