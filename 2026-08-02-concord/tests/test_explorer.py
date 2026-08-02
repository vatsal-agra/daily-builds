import json
import unittest
import urllib.error
import urllib.request

from concord import pow as powmod
from concord._netutil import wait_until
from concord.block import Block
from concord.chain import Blockchain
from concord.explorer import ExplorerServer
from concord.mempool import Mempool
from concord.merkle import verify_proof
from concord.miner import Miner
from concord.node import Node
from concord.wallet import Wallet

FAST_TARGET = powmod.MAX_TARGET >> 12


def get(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestExplorerAPI(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()
        genesis = Block.genesis(self.alice.address, FAST_TARGET, amount=1000)
        self.chain = Blockchain(genesis)
        self.node = Node("127.0.0.1", 29001, self.chain, Mempool(), name="explorer-test")
        self.node.start()
        self.explorer = ExplorerServer(self.node, host="127.0.0.1", port=0)
        self.explorer.start()
        self.api = f"http://127.0.0.1:{self.explorer.port}"

    def tearDown(self):
        self.node.stop()
        self.explorer.stop()

    def test_index_html_served(self):
        with urllib.request.urlopen(self.api + "/", timeout=10) as resp:
            body = resp.read().decode()
        self.assertIn("Concord", body)
        self.assertEqual(resp.status, 200)

    def test_favicon_no_404(self):
        with urllib.request.urlopen(self.api + "/favicon.ico", timeout=10) as resp:
            self.assertEqual(resp.status, 204)

    def test_status_endpoint(self):
        status = get(self.api + "/api/status")
        self.assertEqual(status["height"], 0)
        self.assertEqual(status["name"], "explorer-test")
        self.assertEqual(status["mempool_size"], 0)

    def test_chain_endpoint_lists_genesis(self):
        chain_list = get(self.api + "/api/chain")
        self.assertEqual(len(chain_list), 1)
        self.assertEqual(chain_list[0]["height"], 0)

    def test_utxo_endpoint_reports_premine_balance(self):
        info = get(self.api + f"/api/utxo/{self.alice.address}")
        self.assertEqual(info["balance"], 1000)
        self.assertEqual(len(info["utxos"]), 1)

    def test_utxo_endpoint_zero_for_unknown_address(self):
        info = get(self.api + f"/api/utxo/{self.bob.address}")
        self.assertEqual(info["balance"], 0)
        self.assertEqual(info["utxos"], [])

    def test_submit_tx_endpoint_accepts_valid_transaction(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 42)
        status, body = post(self.api + "/api/submit_tx", tx.to_dict())
        self.assertEqual(status, 200)
        self.assertTrue(body["accepted"])
        self.assertEqual(body["txid"], tx.txid())
        mempool_list = get(self.api + "/api/mempool")
        self.assertEqual(len(mempool_list), 1)

    def test_submit_tx_endpoint_rejects_malformed_body(self):
        status, body = post(self.api + "/api/submit_tx", {"garbage": True})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_submit_tx_endpoint_rejects_double_spend(self):
        tx1 = self.alice.build_transaction(self.chain.utxo, self.bob.address, 100)
        status1, body1 = post(self.api + "/api/submit_tx", tx1.to_dict())
        self.assertTrue(body1["accepted"])
        conflict = self.alice.build_transaction(self.chain.utxo, self.bob.address, 50)
        status2, body2 = post(self.api + "/api/submit_tx", conflict.to_dict())
        self.assertEqual(status2, 400)
        self.assertFalse(body2["accepted"])

    def test_block_and_merkle_proof_endpoints_after_mining(self):
        miner = Miner(self.node, self.alice.address)
        miner.start()
        self.assertTrue(wait_until(lambda: self.chain.height() >= 1, timeout=20))
        miner.stop()

        chain_list = get(self.api + "/api/chain")
        block_hash = chain_list[-1]["hash"]
        detail = get(self.api + f"/api/block/{block_hash}")
        self.assertGreaterEqual(len(detail["transactions"]), 1)
        txid = detail["transactions"][0]["txid"]

        proof = get(self.api + f"/api/block/{block_hash}/proof/{txid}")
        leaf = bytes.fromhex(proof["leaf"])
        root = bytes.fromhex(proof["root"])
        steps = [(bytes.fromhex(s["sibling"]), s["is_right"]) for s in proof["steps"]]
        self.assertTrue(verify_proof(leaf, steps, root))

    def test_block_not_found_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.api + "/api/block/" + "00" * 32, timeout=10)
        self.assertEqual(ctx.exception.code, 404)

    def test_tx_endpoint_finds_pending_and_confirmed(self):
        tx = self.alice.build_transaction(self.chain.utxo, self.bob.address, 30)
        self.node.submit_transaction(tx)
        pending = get(self.api + f"/api/tx/{tx.txid()}")
        self.assertEqual(pending["location"], "mempool")

        miner = Miner(self.node, self.alice.address)
        miner.start()
        self.assertTrue(wait_until(lambda: self.bob.balance(self.chain.utxo) == 30, timeout=20))
        miner.stop()

        confirmed = get(self.api + f"/api/tx/{tx.txid()}")
        self.assertTrue(confirmed["location"].startswith("block"))


if __name__ == "__main__":
    unittest.main()
