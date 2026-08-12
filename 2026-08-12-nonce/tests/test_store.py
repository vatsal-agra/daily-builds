import json
import os
import shutil
import tempfile
import unittest

from nonce import store
from nonce.wallet import Wallet
from nonce.core.blockchain import Blockchain, create_genesis


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nonce-store-test-")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_save_then_load_round_trip(self):
        wallet = Wallet()
        chain = Blockchain(create_genesis(wallet.address))
        for i in range(3):
            chain.add_block(chain.mine_new_block([], wallet.address, extra_nonce=i + 1))

        store.save(self.tmpdir, wallet, chain)
        loaded_wallet, loaded_chain = store.load(self.tmpdir)

        self.assertEqual(loaded_wallet.address, wallet.address)
        self.assertEqual(loaded_wallet.privkey, wallet.privkey)
        self.assertEqual(loaded_chain.tip_hash, chain.tip_hash)
        self.assertEqual(loaded_chain.height(), chain.height())
        self.assertEqual(loaded_chain.balance(wallet.address), chain.balance(wallet.address))

    def test_exists_false_before_save(self):
        self.assertFalse(store.exists(self.tmpdir))

    def test_exists_true_after_save(self):
        wallet = Wallet()
        chain = Blockchain(create_genesis(wallet.address))
        store.save(self.tmpdir, wallet, chain)
        self.assertTrue(store.exists(self.tmpdir))

    def test_load_missing_returns_none(self):
        self.assertIsNone(store.load(self.tmpdir))

    def test_tampered_chain_file_rejected_on_load(self):
        wallet = Wallet()
        chain = Blockchain(create_genesis(wallet.address))
        chain.add_block(chain.mine_new_block([], wallet.address, extra_nonce=1))
        store.save(self.tmpdir, wallet, chain)

        chain_path = os.path.join(self.tmpdir, store.CHAIN_FILE)
        with open(chain_path) as f:
            blocks = json.load(f)
        blocks[-1]["transactions"][0]["outputs"][0]["amount"] += 1  # tamper the saved coinbase amount
        with open(chain_path, "w") as f:
            json.dump(blocks, f)

        with self.assertRaises(ValueError):
            store.load(self.tmpdir)


if __name__ == "__main__":
    unittest.main()
