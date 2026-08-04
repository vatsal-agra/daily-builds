import json
import threading
import unittest
import urllib.error
import urllib.request

from bedrock.chain import COIN, block_subsidy
from bedrock.explorer import serve
from bedrock.node import Node


class TestExplorerAPI(unittest.TestCase):
    def setUp(self):
        self.httpd = serve(Node(), port=0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=2)
        self.httpd.server_close()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return json.loads(r.read())

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_index_serves_html(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as r:
            html = r.read().decode()
        self.assertIn("Bedrock Explorer", html)

    def test_status_reports_genesis(self):
        status = self._get("/api/status")
        self.assertEqual(status["height"], 0)
        self.assertEqual(status["mempool_size"], 0)

    def test_wallet_create_and_balance(self):
        w = self._post("/api/wallet/new", {})
        self.assertTrue(w["address"])
        bal = self._get(f"/api/wallet/{w['address']}/balance")
        self.assertEqual(bal["balance"], 0)

    def test_mine_credits_reward(self):
        w = self._post("/api/wallet/new", {})
        result = self._post("/api/mine", {"miner_address": w["address"]})
        self.assertEqual(result["status"], "best_chain")
        bal = self._get(f"/api/wallet/{w['address']}/balance")
        self.assertEqual(bal["balance"], block_subsidy(1))

    def test_send_and_mempool(self):
        w1 = self._post("/api/wallet/new", {})
        w2 = self._post("/api/wallet/new", {})
        self._post("/api/mine", {"miner_address": w1["address"]})
        self._post("/api/tx/send", {"from_address": w1["address"], "to_address": w2["address"], "amount": 1 * COIN, "fee": 500})
        mempool = self._get("/api/mempool")
        self.assertEqual(len(mempool["transactions"]), 1)

    def test_block_listing_and_detail(self):
        w = self._post("/api/wallet/new", {})
        self._post("/api/mine", {"miner_address": w["address"]})
        blocks = self._get("/api/blocks?limit=10")
        self.assertEqual(len(blocks["blocks"]), 2)  # genesis + mined
        detail = self._get("/api/block/" + blocks["blocks"][0]["hash"])
        self.assertIn("transactions", detail)

    def test_send_from_unknown_wallet_returns_400(self):
        w2 = self._post("/api/wallet/new", {})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/tx/send", {"from_address": "bogus", "to_address": w2["address"], "amount": 1, "fee": 0})
        self.assertEqual(ctx.exception.code, 400)

    def test_mine_with_invalid_address_returns_400_not_500(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/mine", {"miner_address": "not-a-real-address"})
        self.assertEqual(ctx.exception.code, 400)

    def test_malformed_json_body_returns_400(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/tx/send",
            data=b"{not valid json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_unknown_route_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/nonexistent")
        self.assertEqual(ctx.exception.code, 404)

    def test_block_detail_for_unknown_hash_returns_400_not_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/block/" + "00" * 32)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
