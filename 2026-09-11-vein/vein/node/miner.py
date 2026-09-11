"""The proof-of-work mining loop: build a block template from the mempool
against the current tip, search the nonce space, and submit whatever is
found back through the node (which validates it exactly like a block
received from the network — mining gets no special trust).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..core.block import Block, BlockHeader
from ..core.chain import Blockchain, make_coinbase
from ..core.mempool import Mempool
from ..core.transaction import merkle_root


@dataclass
class MinerStats:
    blocks_found: int = 0
    hashes_tried: int = 0
    last_hashrate: float = 0.0


class Miner:
    def __init__(self, chain: Blockchain, mempool: Mempool, pubkey_hash: bytes,
                 submit_fn, node_name: str = "miner"):
        self.chain = chain
        self.mempool = mempool
        self.pubkey_hash = pubkey_hash
        self.submit_fn = submit_fn  # callable(Block) -> bool, e.g. P2PNode.submit_block
        self.node_name = node_name

        self.stats = MinerStats()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._restart = threading.Event()
        self._extra_nonce = 0

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._restart.set()
        if self._thread:
            self._thread.join(timeout=2)

    def notify_new_work(self) -> None:
        """Called when the tip changes or the mempool gets an interesting
        new transaction, so the miner rebuilds its template promptly
        instead of wasting time extending a now-stale parent."""
        self._restart.set()

    def _build_template(self) -> Block:
        tip = self.chain.tip_hash
        height = self.chain.height + 1
        txs = self.mempool.select_for_block()
        confirmed_ids = [t.txid() for t in txs]
        fees = self.mempool.total_fees(confirmed_ids)
        from ..core.chain import subsidy_at_height
        reward = subsidy_at_height(height, self.chain.params) + fees
        self._extra_nonce += 1
        coinbase = make_coinbase(height, reward, self.pubkey_hash, extra_nonce=self._extra_nonce)
        all_txs = [coinbase] + txs
        bits = self.chain.expected_bits_after(tip)
        # Timestamps must strictly increase block-to-block (see
        # chain.add_block), but wall-clock time has only 1-second
        # resolution here — at these (deliberately low, demo-friendly)
        # difficulties a miner can easily find two blocks inside the same
        # second. Falling back to parent_time + 1 instead of just
        # int(time.time()) keeps every block acceptable to its own miner.
        parent_time = self.chain.meta[tip].header.timestamp
        timestamp = max(int(time.time()), parent_time + 1)
        header = BlockHeader(
            version=1,
            prev_hash=tip,
            merkle_root=merkle_root([t.txid() for t in all_txs]),
            timestamp=timestamp,
            bits=bits,
            nonce=0,
        )
        return Block(header, all_txs)

    def _run(self) -> None:
        while self._running.is_set():
            self._restart.clear()
            block = self._build_template()
            target = block.header.target()
            nonce = 0
            attempts_at_start = self.stats.hashes_tried
            t0 = time.time()

            found = False
            while self._running.is_set() and not self._restart.is_set():
                block.header.nonce = nonce & 0xFFFFFFFF
                self.stats.hashes_tried += 1
                if int.from_bytes(block.header.hash(), "big") <= target:
                    found = True
                    break
                nonce += 1
                if nonce & 0xFFFFFFFF == 0:
                    # Exhausted the 32-bit nonce space (astronomically
                    # unlikely at these difficulties, but handled for
                    # real): roll the extra-nonce, which changes the
                    # coinbase and therefore the merkle root, giving a
                    # fresh search space, exactly like real miners do.
                    block = self._build_template()
                    target = block.header.target()

            elapsed = max(time.time() - t0, 1e-6)
            self.stats.last_hashrate = (self.stats.hashes_tried - attempts_at_start) / elapsed

            if found:
                self.stats.blocks_found += 1
                self.submit_fn(block)
                # After finding one, loop back and rebuild against the
                # new tip (submit_fn -> chain.add_block updates it).
