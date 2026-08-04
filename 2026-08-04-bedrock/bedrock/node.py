"""A Node ties a Chain and a Mempool together and knows how to mine a
candidate block from pending transactions."""

import time

from bedrock import pow as bpow
from bedrock.block import Block
from bedrock.chain import Chain, block_subsidy
from bedrock.mempool import Mempool
from bedrock.merkle import merkle_root
from bedrock.transaction import Transaction


class Node:
    def __init__(self, genesis_block: Block = None):
        self.chain = Chain(genesis_block)
        self.mempool = Mempool()

    # -- reads --------------------------------------------------------------

    def balance(self, address: str) -> int:
        return self.chain.utxo_set.balance(address)

    def _tx_fee(self, tx: Transaction) -> int:
        total_in = 0
        for tx_in in tx.inputs:
            prevout = self.chain.utxo_set.get(tx_in.prev_txid, tx_in.prev_index)
            if prevout is None:
                raise ValueError(f"mempool transaction {tx.txid} references a utxo no longer available")
            total_in += prevout.value
        return total_in - tx.total_output_value()

    # -- writes ---------------------------------------------------------------

    def submit_transaction(self, tx: Transaction) -> bool:
        return self.mempool.add_transaction(tx, self.chain)

    def submit_block(self, block: Block) -> str:
        status = self.chain.add_block(block)
        if status == "best_chain":
            self.mempool.rebase(self.chain)
        return status

    def mine_block(self, miner_address: str, max_tx: int = 200, max_nonce: int = None, deadline: float = None) -> tuple:
        """Assembles a candidate block from the mempool, mines it, and adds
        it to the chain. Returns (Block, status)."""
        selected = self.mempool.select_for_block(max_tx)
        total_fees = sum(self._tx_fee(tx) for tx in selected)
        height = self.chain.height + 1
        reward = block_subsidy(height) + total_fees
        coinbase = Transaction.new_coinbase(miner_address, reward, height)
        block_txs = [coinbase] + selected

        root = merkle_root([bytes.fromhex(tx.txid) for tx in block_txs]).hex()
        header = self.chain.build_candidate_header(root, timestamp=int(time.time()))
        if header.timestamp <= self.chain.tip.header.timestamp:
            header.timestamp = self.chain.tip.header.timestamp + 1

        bpow.mine(header, max_nonce=max_nonce, deadline=deadline)
        block = Block(header, block_txs)
        status = self.submit_block(block)
        return block, status
