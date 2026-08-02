"""Proof-of-work mining: build a candidate block from the current chain tip
and mempool, then search nonces until the block hash meets the target.
Runs as a stoppable background thread so a node can keep mining while
also serving the network."""

import threading
import time

from .block import Block
from .chain import BASE_REWARD
from .pow import meets_target
from .transaction import Transaction

NONCE_CHECK_BATCH = 2000  # how many nonces to try before re-checking for a new tip / stop


def build_candidate(chain, mempool, reward_address):
    # a *working* copy that gets debited as transactions are selected, so
    # two mempool transactions that conflict (spend the same outpoint —
    # e.g. a double-spend race where both landed in this node's pool
    # before propagation caught up) can never both be selected into the
    # same candidate: whichever is considered second finds its input
    # already gone here and is skipped, instead of building a block that
    # _apply_block will only reject later, wasting the mined proof-of-work.
    working_utxo = dict(chain.utxo)
    included = []
    total_fees = 0
    for tx in mempool.select_for_block():
        keys = [(i.txid, i.index) for i in tx.inputs]
        if any(k not in working_utxo for k in keys):
            continue
        total_in = sum(working_utxo[k].amount for k in keys)
        fee = total_in - tx.total_output()
        if fee < 0:
            continue
        for k in keys:
            del working_utxo[k]
        for idx, out in enumerate(tx.outputs):
            working_utxo[(tx.txid(), idx)] = out
        included.append(tx)
        total_fees += fee

    coinbase = Transaction.new_coinbase(
        reward_address, BASE_REWARD + total_fees, height=chain.height() + 1,
        extra=str(time.time()),
    )
    target = chain.next_block_target()
    return Block(chain.height() + 1, chain.tip_hash, [coinbase] + included, target)


def mine_block(block: Block, stop_check=None):
    """Searches nonces in place on `block`, returns it once solved, or None
    if stop_check() becomes true first."""
    while True:
        for _ in range(NONCE_CHECK_BATCH):
            if meets_target(bytes.fromhex(block.hash()), block.target):
                return block
            block.nonce += 1
        if stop_check and stop_check():
            return None


class Miner:
    def __init__(self, node, reward_address):
        self.node = node
        self.reward_address = reward_address
        self._stop = threading.Event()
        self._thread = None
        self.blocks_mined = 0

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            with self.node.lock:
                start_tip = self.node.chain.tip_hash
                candidate = build_candidate(self.node.chain, self.node.mempool, self.reward_address)

            def tip_changed_or_stopped():
                if self._stop.is_set():
                    return True
                with self.node.lock:
                    return self.node.chain.tip_hash != start_tip

            solved = mine_block(candidate, stop_check=tip_changed_or_stopped)
            if solved is None:
                continue  # tip moved or stop requested; rebuild against new tip
            with self.node.lock:
                if self.node.chain.tip_hash != start_tip:
                    continue  # someone beat us to it; discard and retry
            ok, became_tip = self.node.submit_block(solved)
            if ok and became_tip:
                self.blocks_mined += 1
