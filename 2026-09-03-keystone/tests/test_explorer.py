"""In-process HTTP tests for the block explorer -- covers the SyntaxError
regression (REVIEW.md finding #9) by actually importing and running it,
plus every route's happy and error paths."""
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone import explorer, pow as pow_module
from keystone.chain import Blockchain, create_genesis_chain
from keystone.mempool import Mempool
from keystone.node import FullNode
from keystone.wallet import Wallet

EASY_BITS = pow_module.target_to_bits(pow_module.MAX_TARGET)


class _FakeNet:
    def __init__(self):
        self.name = "test-node"

    def peer_count(self):
        return 0

    reorg_count = 0


class _FakeNode:
    """A minimal stand-in with just the attributes explorer.py reads, so
    these tests don't need real sockets/threads."""
    def __init__(self, chain, mempool):
        self.chain = chain
        self.mempool = mempool
        self.net = _FakeNet()


class TestExplorerImports(unittest.TestCase):
    def test_module_imports_cleanly(self):
        """Regression test for REVIEW.md finding #9: explorer.py had a
        SyntaxError and had never actually been imported before."""
        import importlib
        importlib.reload(explorer)  # would raise SyntaxError if it regressed


class TestExplorerRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wallet = Wallet.generate()
        seed = create_genesis_chain(wallet, bits=EASY_BITS)
        genesis = seed.blocks[seed.tip_hash]
        chain = Blockchain(genesis)
        mempool = Mempool()
        cls.node = _FakeNode(chain, mempool)
        cls.wallet = wallet
        cls.server, cls.thread = explorer.run_explorer_in_thread(cls.node, "127.0.0.1", 0)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as resp:
            return resp.status, resp.read().decode()

    def test_index_renders(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("Keystone", body)
        self.assertIn("height", body)

    def test_mempool_renders(self):
        status, body = self._get("/mempool")
        self.assertEqual(status, 200)
        self.assertIn("Mempool", body)

    def test_known_block_renders(self):
        genesis_hash = self.node.chain.tip_hash
        status, body = self._get(f"/block?hash={genesis_hash}")
        self.assertEqual(status, 200)
        self.assertIn(genesis_hash, body)

    def test_unknown_block_renders_message_not_500(self):
        status, body = self._get("/block?hash=deadbeef")
        self.assertEqual(status, 200)
        self.assertIn("Unknown block", body)

    def test_valid_address_renders_balance(self):
        status, body = self._get(f"/address?addr={self.wallet.address}")
        self.assertEqual(status, 200)
        self.assertIn("balance", body)

    def test_malformed_address_renders_message_not_500(self):
        status, body = self._get("/address?addr=not-a-real-address!!!")
        self.assertEqual(status, 200)
        self.assertIn("Bad address", body)

    def test_favicon_does_not_404(self):
        # a bare 404 here shows up as a spurious console error in a real
        # browser (browsers request /favicon.ico automatically)
        status, _ = self._get("/favicon.ico")
        self.assertEqual(status, 204)

    def test_unknown_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/totally/not/a/route")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
