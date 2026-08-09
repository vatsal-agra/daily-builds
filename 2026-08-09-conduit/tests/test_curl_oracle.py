"""The sharpest oracle in this project: the box's real, unmodified `curl`
binary, fetching from a Conduit-backed HTTP server through a real
TCP<->Conduit bridge and — for the lossy cases — through NetworkSimulator
actively dropping/reordering/duplicating packets. curl shares no code
with Conduit; it doesn't know Conduit exists. If it gets byte-correct
HTML back while the simulator is actively misbehaving, the whole stack
(HTTP framing + reliable transport + congestion control) is proven
end-to-end by a genuinely independent program.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from conduit.api import Listener
from conduit.bridge import TcpToConduitBridge
from conduit.netsim import NetworkSimulator
from httpd.server import HttpServer
from httpd.static import StaticFileHandler

CURL = shutil.which("curl")


@unittest.skipUnless(CURL, "curl is not installed on this box")
class TestCurlOracle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.page = "<!doctype html><h1>Conduit says hi</h1>" + ("x" * 5000)
        with open(os.path.join(self.tmpdir, "index.html"), "w") as f:
            f.write(self.page)
        big = "".join(f"line {i}\n" for i in range(20_000))  # ~140KB, forces many segments
        self.big_content = big
        with open(os.path.join(self.tmpdir, "big.txt"), "w") as f:
            f.write(big)

        self.listener = Listener(("127.0.0.1", 0))
        self.server = HttpServer(self.listener, StaticFileHandler(self.tmpdir))
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.listener.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _curl_get(self, bridge_addr, path, max_time=25):
        url = f"http://{bridge_addr[0]}:{bridge_addr[1]}{path}"
        result = subprocess.run(
            [CURL, "-sS", "--max-time", str(max_time), url],
            capture_output=True, text=True,
        )
        return result

    def test_curl_direct_no_netsim(self):
        bridge = TcpToConduitBridge(("127.0.0.1", 0), self.listener.local_addr)
        try:
            result = self._curl_get(bridge.local_addr, "/")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, self.page)
        finally:
            bridge.close()

    def test_curl_through_lossy_network_small_page(self):
        sim = NetworkSimulator(
            ("127.0.0.1", 0), self.listener.local_addr,
            loss=0.10, dup_prob=0.03, reorder_prob=0.08, reorder_delay=0.02,
            delay=0.004, jitter=0.003, seed=11,
        )
        bridge = TcpToConduitBridge(("127.0.0.1", 0), sim.local_addr)
        try:
            result = self._curl_get(bridge.local_addr, "/", max_time=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, self.page)
            self.assertGreater(sim.stats["dropped"], 0, "loss injector never actually fired")
        finally:
            bridge.close()
            sim.close()

    def test_curl_through_lossy_network_large_file(self):
        sim = NetworkSimulator(
            ("127.0.0.1", 0), self.listener.local_addr,
            loss=0.06, dup_prob=0.02, reorder_prob=0.05, reorder_delay=0.02,
            delay=0.003, jitter=0.002, seed=12,
        )
        bridge = TcpToConduitBridge(("127.0.0.1", 0), sim.local_addr)
        try:
            result = self._curl_get(bridge.local_addr, "/big.txt", max_time=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, self.big_content)
            self.assertEqual(len(result.stdout), len(self.big_content))
        finally:
            bridge.close()
            sim.close()

    def test_curl_404_through_bridge(self):
        bridge = TcpToConduitBridge(("127.0.0.1", 0), self.listener.local_addr)
        try:
            url = f"http://{bridge.local_addr[0]}:{bridge.local_addr[1]}/nope"
            result = subprocess.run(
                [CURL, "-sS", "-o", os.devnull, "-w", "%{http_code}", "--max-time", "10", url],
                capture_output=True, text=True,
            )
            self.assertEqual(result.stdout.strip(), "404")
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
