"""Node-level tests for mempool hygiene that don't need a real network —
regression coverage for bugs found in the Phase 3 adversarial review (see
REVIEW.md): a losing double-spend, or a self-built block that gets
rejected, must not leave a permanently-poisoned transaction sitting in the
mempool forever."""
import time
import unittest

from ledgerline.block import Block, BlockHeader, mine_block
from ledgerline.chain import BLOCK_REWARD
from ledgerline.node import Node
from ledgerline.transaction import build_transaction, make_coinbase
from ledgerline.wallet import Wallet

BITS = 10


def mined(prev_hash, height, txs, bits=BITS):
    header = BlockHeader(1, prev_hash, "", time.time(), bits, 0, height)
    block = Block(header, txs)
    header.merkle_root_hex = block.compute_merkle_root()
    mine_block(block, stop_flag=lambda: False)
    return block


class TestMempoolHygiene(unittest.TestCase):
    def setUp(self):
        self.alice = Wallet()
        self.bob = Wallet()
        self.carol = Wallet()
        from ledgerline.block import make_genesis_block
        self.cb = make_coinbase(self.alice.address, 1000, height=0)
        self.genesis = make_genesis_block(self.cb, bits=BITS)
        self.node = Node(
            "test", "127.0.0.1", 0, self.genesis, BITS, wallet=Wallet(), mine=False,
        )

    def test_confirming_a_double_spend_prunes_the_loser_from_mempool(self):
        utxos = self.node.chain.utxos_for(self.alice.address)
        tx_loser = build_transaction(utxos, self.alice.privkey, self.bob.address, 500, 1, self.alice.address)
        tx_winner = build_transaction(utxos, self.alice.privkey, self.carol.address, 500, 1, self.alice.address)
        self.assertNotEqual(tx_loser.txid(), tx_winner.txid())

        # tx_loser is sitting in our mempool (we heard about it before
        # anyone confirmed anything)
        ok, fee, err = self.node._check_tx_against_utxo(tx_loser)
        self.assertTrue(ok, err)
        self.node.mempool.add(tx_loser, fee)
        self.assertTrue(self.node.mempool.contains(tx_loser.txid()))

        # ...but someone else's block confirms tx_winner first, spending
        # the exact same input tx_loser needs
        cb1 = make_coinbase(self.carol.address, BLOCK_REWARD, height=1)
        block1 = mined(self.genesis.hash_hex(), 1, [cb1, tx_winner])
        accepted = self.node._accept_block(block1, source=None, rebroadcast=False)
        self.assertTrue(accepted)

        # the loser must be gone — not sitting there forever waiting to
        # poison every future block this node tries to mine
        self.assertFalse(self.node.mempool.contains(tx_loser.txid()))

    def test_rejected_self_built_block_prunes_its_own_bad_tx(self):
        utxos = self.node.chain.utxos_for(self.alice.address)
        tx_a = build_transaction(utxos, self.alice.privkey, self.bob.address, 500, 1, self.alice.address)
        tx_b = build_transaction(utxos, self.alice.privkey, self.carol.address, 500, 1, self.alice.address)

        # confirm tx_a first (simulating a peer's block landing first)
        cb1 = make_coinbase(self.bob.address, BLOCK_REWARD, height=1)
        block1 = mined(self.genesis.hash_hex(), 1, [cb1, tx_a])
        self.assertTrue(self.node._accept_block(block1, source=None, rebroadcast=False))

        # now we (still unaware tx_a already won) try to accept a block WE
        # built earlier around tx_b, which conflicts with the now-confirmed
        # tx_a -> this must be rejected outright...
        self.node.mempool.add(tx_b, 1)  # pretend it was still in our mempool
        cb2 = make_coinbase(self.carol.address, BLOCK_REWARD, height=2, extra_nonce=1)
        block2 = mined(block1.hash_hex(), 2, [cb2, tx_b])
        accepted = self.node._accept_block(block2, source=None, rebroadcast=False)
        self.assertFalse(accepted, "a block double-spending a confirmed input must be rejected")

        # ...and must not leave tx_b sitting in the mempool to poison every
        # future block this node tries to build
        self.assertFalse(self.node.mempool.contains(tx_b.txid()))


class TestMalformedMessageHandling(unittest.TestCase):
    """A malformed/malicious peer message must never crash the reader
    thread processing it — that would silently kill the whole connection
    over one bad line instead of just rejecting that message. See
    REVIEW.md."""

    def setUp(self):
        from ledgerline.block import make_genesis_block
        cb = make_coinbase(Wallet().address, 50, height=0)
        genesis = make_genesis_block(cb, bits=BITS)
        self.node = Node("test", "127.0.0.1", 0, genesis, BITS, wallet=Wallet(), mine=False)

    def test_malformed_tx_does_not_raise(self):
        self.node._dispatch_message({"type": "tx", "data": {"inputs": [], "outputs": "not-a-list"}}, sock=None)

    def test_tx_with_bad_hex_pubkey_does_not_raise(self):
        bad = {
            "type": "tx",
            "data": {
                "version": 1, "timestamp": time.time(), "coinbase_data": None,
                "inputs": [{"prev_txid": "f" * 64, "prev_index": 0, "pubkey": "not-hex!!", "signature": "ab"}],
                "outputs": [{"address": "Labc", "amount": 10}],
            },
        }
        self.node._dispatch_message(bad, sock=None)

    def test_unknown_message_type_does_not_raise(self):
        self.node._dispatch_message({"type": "totally-unknown-type", "data": {}}, sock=None)

    def test_missing_data_field_does_not_raise(self):
        self.node._dispatch_message({"type": "block"}, sock=None)


if __name__ == "__main__":
    unittest.main()
