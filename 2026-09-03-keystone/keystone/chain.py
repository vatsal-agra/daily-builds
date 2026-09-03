"""The Blockchain: block validation, best-chain selection by cumulative
proof-of-work (not block count), reorgs, and an orphan pool for blocks that
arrive before their parent is known."""
from __future__ import annotations

import time
from collections import defaultdict

from . import pow as pow_module
from .block import Block
from .transaction import make_coinbase
from .utxo import UTXOSet, ValidationError
from .wallet import Wallet

BASE_BLOCK_REWARD = 5_000_000_000  # in the smallest unit ("keystones")
HALVING_INTERVAL = 64  # blocks — compressed a la Bitcoin's 210,000
MAX_FUTURE_DRIFT = 300  # seconds a block's timestamp may be ahead of wall clock


class ChainError(ValueError):
    pass


class Blockchain:
    def __init__(self, genesis_block: Block, base_reward: int = BASE_BLOCK_REWARD,
                 halving_interval: int = HALVING_INTERVAL):
        self.base_reward = base_reward
        self.halving_interval = halving_interval

        genesis_hash = genesis_block.hash()
        if not pow_module.meets_target(bytes.fromhex(genesis_hash), genesis_block.header.bits):
            raise ChainError("genesis block does not satisfy its own proof-of-work target")

        self.blocks = {genesis_hash: genesis_block}
        self.heights = {genesis_hash: 0}
        self.children = defaultdict(list)
        self.utxo_set = UTXOSet()
        self.total_reorgs = 0  # authoritative counter: incremented in add_block
        # itself so a reorg triggered recursively (via orphan resolution,
        # which calls add_block directly rather than through the network
        # layer) is still counted. A caller-side counter that only watches
        # its own direct add_block() return value misses exactly this case
        # — a real bug this build's own network smoke-testing caught, see
        # REVIEW.md.
        self.undo_log = {}
        self.orphans = {}
        self.orphans_by_parent = defaultdict(list)

        removed = self.utxo_set.validate_and_apply_block(genesis_block, self.block_reward_at(0))
        self.undo_log[genesis_hash] = removed
        self.cum_work = {genesis_hash: pow_module.block_work(genesis_block.header.bits)}
        self.tip_hash = genesis_hash

    # ------------------------------------------------------------------
    def block_reward_at(self, height: int) -> int:
        halvings = height // self.halving_interval
        if halvings >= 64:
            return 0
        return self.base_reward >> halvings

    def get_block(self, block_hash: str):
        return self.blocks.get(block_hash)

    def height(self) -> int:
        return self.heights[self.tip_hash]

    def tip(self) -> Block:
        return self.blocks[self.tip_hash]

    def active_chain(self) -> list:
        """Genesis-to-tip, in order."""
        chain = []
        h = self.tip_hash
        while True:
            chain.append(self.blocks[h])
            if self.blocks[h].header.prev_hash == "0" * 64:
                break
            h = self.blocks[h].header.prev_hash
        chain.reverse()
        return chain

    def compute_next_bits(self, parent_hash: str) -> int:
        parent = self.blocks[parent_hash]
        next_height = self.heights[parent_hash] + 1
        if next_height % pow_module.RETARGET_INTERVAL != 0:
            return parent.header.bits
        first_hash = parent_hash
        for _ in range(pow_module.RETARGET_INTERVAL - 1):
            first_hash = self.blocks[first_hash].header.prev_hash
        first_time = self.blocks[first_hash].header.timestamp
        last_time = parent.header.timestamp
        return pow_module.next_bits(parent.header.bits, first_time, last_time, pow_module.RETARGET_INTERVAL)

    def _find_fork_point(self, hash_a: str, hash_b: str) -> str:
        ha, hb = hash_a, hash_b
        while self.heights[ha] > self.heights[hb]:
            ha = self.blocks[ha].header.prev_hash
        while self.heights[hb] > self.heights[ha]:
            hb = self.blocks[hb].header.prev_hash
        while ha != hb:
            ha = self.blocks[ha].header.prev_hash
            hb = self.blocks[hb].header.prev_hash
        return ha

    def _simulate_branch(self, new_tip_hash: str):
        """Validate the full chain of blocks from the current fork point up
        to `new_tip_hash` against a throwaway copy of the UTXO set. Never
        touches self.utxo_set. Raises ValidationError if any block in the
        branch is invalid. Returns (fork_point, undo_chain, branch,
        branch_undo, resulting_utxo_set)."""
        fork_point = self._find_fork_point(new_tip_hash, self.tip_hash)

        branch = []
        h = new_tip_hash
        while h != fork_point:
            branch.append(h)
            h = self.blocks[h].header.prev_hash
        branch.reverse()

        undo_chain = []
        h = self.tip_hash
        while h != fork_point:
            undo_chain.append(h)
            h = self.blocks[h].header.prev_hash

        temp = UTXOSet()
        temp.utxos = dict(self.utxo_set.utxos)
        for bh in undo_chain:
            temp.undo_block(self.blocks[bh], self.undo_log[bh])

        branch_undo = {}
        for bh in branch:
            blk = self.blocks[bh]
            removed = temp.validate_and_apply_block(blk, self.block_reward_at(self.heights[bh]))
            branch_undo[bh] = removed

        return fork_point, undo_chain, branch, branch_undo, temp

    def add_block(self, block: Block, mempool=None):
        """Returns a dict {accepted, reason, reorged, orphan}. Fully
        idempotent: re-adding a block already known is a harmless no-op."""
        block_hash = block.hash()
        if block_hash in self.blocks:
            return {"accepted": True, "reason": "already known", "reorged": False, "orphan": False}

        if not pow_module.meets_target(bytes.fromhex(block_hash), block.header.bits):
            return {"accepted": False, "reason": "hash does not meet target", "reorged": False, "orphan": False}

        if block.compute_merkle_root() != block.header.merkle_root:
            return {"accepted": False, "reason": "merkle root mismatch", "reorged": False, "orphan": False}

        parent_hash = block.header.prev_hash
        if parent_hash not in self.blocks:
            self.orphans[block_hash] = block
            self.orphans_by_parent[parent_hash].append(block_hash)
            return {"accepted": False, "reason": "orphan: parent unknown", "reorged": False, "orphan": True}

        height = self.heights[parent_hash] + 1
        parent = self.blocks[parent_hash]

        expected_bits = self.compute_next_bits(parent_hash)
        if block.header.bits != expected_bits:
            return {"accepted": False, "reason": "incorrect difficulty bits", "reorged": False, "orphan": False}

        if block.header.timestamp <= parent.header.timestamp:
            return {"accepted": False, "reason": "timestamp does not advance", "reorged": False, "orphan": False}
        if block.header.timestamp > time.time() + MAX_FUTURE_DRIFT:
            return {"accepted": False, "reason": "timestamp too far in the future", "reorged": False, "orphan": False}

        block.height = height
        work = self.cum_work[parent_hash] + pow_module.block_work(block.header.bits)

        # Index the block *before* simulating: _simulate_branch walks
        # parent pointers starting from this block's own hash, so it needs
        # self.blocks/self.heights to already know about it. Rolled back
        # below if it turns out to be invalid.
        self.blocks[block_hash] = block
        self.heights[block_hash] = height
        self.cum_work[block_hash] = work

        try:
            fork_point, undo_chain, branch, branch_undo, resulting_utxo = self._simulate_branch(block_hash)
        except ValidationError as e:
            del self.blocks[block_hash]
            del self.heights[block_hash]
            del self.cum_work[block_hash]
            return {"accepted": False, "reason": f"invalid transaction: {e}", "reorged": False, "orphan": False}

        self.children[parent_hash].append(block_hash)

        reorged = False
        if work > self.cum_work[self.tip_hash]:
            reorged = fork_point != self.tip_hash
            if reorged:
                self.total_reorgs += 1
            # Undo the losing side of the active chain, apply the winning branch.
            self.utxo_set.utxos = resulting_utxo.utxos
            for bh in branch:
                self.undo_log[bh] = branch_undo[bh]
            old_tip = self.tip_hash
            self.tip_hash = block_hash

            if mempool is not None:
                for bh in undo_chain:
                    for tx in self.blocks[bh].transactions:
                        if not tx.is_coinbase:
                            mempool.readd_if_valid(tx, self.utxo_set, self.height())
                for bh in branch:
                    mempool.remove_confirmed(self.blocks[bh])
            _ = old_tip  # kept for clarity/debuggability

        self._process_orphans(block_hash, mempool)
        return {"accepted": True, "reason": "ok", "reorged": reorged, "orphan": False}

    def _process_orphans(self, parent_hash: str, mempool) -> None:
        pending = self.orphans_by_parent.pop(parent_hash, [])
        for orphan_hash in pending:
            orphan_block = self.orphans.pop(orphan_hash, None)
            if orphan_block is not None:
                self.add_block(orphan_block, mempool)


def create_genesis_chain(miner_wallet: Wallet, bits: int, base_reward: int = BASE_BLOCK_REWARD,
                          halving_interval: int = HALVING_INTERVAL, timestamp: float = None) -> Blockchain:
    """Mine a real genesis block (it must satisfy its own PoW target just
    like any other block — no hardcoded-valid special case) and construct
    the chain around it."""
    from .block import make_genesis_block
    from .crypto import sha256

    ts = timestamp if timestamp is not None else time.time()
    coinbase = make_coinbase(miner_wallet.lock_script_for_self(), base_reward, height=0, extra_nonce=0)
    genesis = make_genesis_block(coinbase, bits, timestamp=ts)

    def prefix_fn(nonce):
        genesis.header.nonce = nonce
        return genesis.header.bytes_for_hash()

    result = pow_module.mine(prefix_fn, bits)
    if result is None:
        raise ChainError("failed to mine genesis block (bits too high for max_nonce)")
    nonce, _h = result
    genesis.header.nonce = nonce
    return Blockchain(genesis, base_reward=base_reward, halving_interval=halving_interval)
