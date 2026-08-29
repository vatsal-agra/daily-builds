"""End-to-end tests for the reverse proxy / load balancer against two real
backend Anvil servers -- round-robin distribution, raw byte forwarding
(headers, body, and all), and failover when a backend goes down."""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil import Router, Server, Response  # noqa: E402
from anvil.client import HttpClient  # noqa: E402
from anvil.proxy import LoadBalancer  # noqa: E402


def make_backend(tag):
    router = Router()

    @router.route("GET", "/")
    def health(req):
        return Response.text("ok")

    @router.route("GET", "/whoami")
    def whoami(req):
        return Response.text(tag)

    @router.route("POST", "/echo")
    def echo(req):
        return Response(200, headers=[("X-Backend", tag)], body=req.body)

    server = Server(host="127.0.0.1", port=0, router=router)
    server.bind()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_timeout": 0.05}, daemon=True)
    thread.start()
    return server, thread


class TestLoadBalancer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend_a, cls.thread_a = make_backend("A")
        cls.backend_b, cls.thread_b = make_backend("B")
        cls.lb = LoadBalancer(
            "127.0.0.1", 0,
            [("127.0.0.1", cls.backend_a.port), ("127.0.0.1", cls.backend_b.port)],
            health_interval=0.1, health_timeout=0.5, unhealthy_threshold=2,
        )
        cls.lb.start()
        cls.lb_thread = threading.Thread(target=cls.lb.serve_forever, daemon=True)
        cls.lb_thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.lb.stop()
        cls.backend_a.stop()
        cls.backend_b.stop()
        cls.thread_a.join(timeout=5)
        cls.thread_b.join(timeout=5)

    def test_round_robin_distribution(self):
        seen = set()
        for _ in range(10):
            c = HttpClient("127.0.0.1", self.lb.port, timeout=5)
            resp = c.get("/whoami", keep_alive=False)
            self.assertEqual(resp.status, 200)
            seen.add(resp.body)
            c.close()
        self.assertEqual(seen, {b"A", b"B"})

    def test_body_forwarded_raw(self):
        c = HttpClient("127.0.0.1", self.lb.port, timeout=5)
        resp = c.post("/echo", body=b"proxied bytes, unchanged", keep_alive=False)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"proxied bytes, unchanged")
        self.assertIn(resp.headers.get("X-Backend"), ("A", "B"))
        c.close()


class TestLoadBalancerFailover(unittest.TestCase):
    """Isolated from TestLoadBalancer -- this test deliberately kills a
    backend, so it needs its own pair rather than sharing (and
    permanently damaging) another test's fixture."""

    @classmethod
    def setUpClass(cls):
        cls.backend_a, cls.thread_a = make_backend("A")
        cls.backend_b, cls.thread_b = make_backend("B")
        cls.lb = LoadBalancer(
            "127.0.0.1", 0,
            [("127.0.0.1", cls.backend_a.port), ("127.0.0.1", cls.backend_b.port)],
            health_interval=0.1, health_timeout=0.5, unhealthy_threshold=2,
        )
        cls.lb.start()
        cls.lb_thread = threading.Thread(target=cls.lb.serve_forever, daemon=True)
        cls.lb_thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.lb.stop()
        cls.backend_a.stop()
        cls.backend_b.stop()
        cls.thread_a.join(timeout=5)
        cls.thread_b.join(timeout=5)

    def test_failover_when_backend_dies(self):
        # Kill backend B; the health checker should pull it out of
        # rotation within a couple of intervals, and every subsequent
        # request should land on A.
        self.backend_b.stop()
        deadline = time.time() + 5
        while time.time() < deadline:
            healthy = [b for b in self.lb.backends if b.healthy]
            if len(healthy) == 1 and healthy[0].port == self.backend_a.port:
                break
            time.sleep(0.1)
        else:
            self.fail("load balancer never marked the dead backend unhealthy")

        for _ in range(5):
            c = HttpClient("127.0.0.1", self.lb.port, timeout=5)
            resp = c.get("/whoami", keep_alive=False)
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.body, b"A")
            c.close()


if __name__ == "__main__":
    unittest.main()
