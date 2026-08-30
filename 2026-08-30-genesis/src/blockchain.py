"""The chain: UTXO-set validation, difficulty retargeting, and fork choice.

Consensus rule: the canonical chain is whichever known chain has the
greatest cumulative proof-of-work (not simply the tallest — a short chain
of very hard blocks can outweigh a long chain of easy ones, exactly as in
real Bitcoin). When a competing branch overtakes the current tip, this
module performs a real reorg: it re-derives the UTXO set for the new tip
from genesis along the winning branch and swaps it in, so every
transaction the losing fork applied is provably undone and every
transaction the winning fork applied is provably re-applied.

Scope trade-off, stated plainly: UTXO snapshots for a candidate block are
rebuilt by replaying that branch's transactions from genesis rather than
maintaining incremental per-block undo diffs (what a production node does
for O(1)-ish reorgs). At the chain lengths this project deals with
(demo-scale: tens to low hundreds of blocks) that's a few hundred
milliseconds, and it buys a large simplicity/correctness win: there is
exactly one code path (`_apply_txs`) that both accepts new blocks and
reconstructs historical state, so there's no separate undo-log logic that
could disagree with the forward-apply logic.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from block import Block, BlockHeader, MAX_TARGET
from transaction import Transaction, TxOut

RETARGET_INTERVAL = 10          # blocks between difficulty adjustments
TARGET_BLOCK_TIME = 2           # seconds; a demo-scale block time
MAX_RETARGET_FACTOR = 4.0
MIN_RETARGET_FACTOR = 0.25
MEDIAN_TIME_WINDOW = 5          # blocks used for median-time-past
MAX_FUTURE_DRIFT = 2 * 60 * 60  # seconds a block timestamp may be ahead of "now"
INITIAL_SUBSIDY = 50_00000000   # 50 coins, in the smallest unit ("sats")
HALVING_INTERVAL = 20           # blocks; small so a demo run can show a halving
GENESIS_TARGET_DEFAULT = MAX_TARGET >> 8  # a comfortably fast-to-mine starting difficulty

Outpoint = Tuple[bytes, int]


def subsidy_at(height: int) -> int:
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return INITIAL_SUBSIDY >> halvings


def block_work(target: int) -> int:
    """Expected number of hashes to find a valid nonce: (max+1)/(target+1)."""
    return (MAX_TARGET + 1) // (target + 1)


class ChainError(Exception):
    pass


@dataclass
class AcceptResult:
    accepted: bool
    reason: str
    reorged: bool = False
    new_tip: Optional[bytes] = None


class Blockchain:
    def __init__(self, genesis_block: Block):
        gh = genesis_block.block_hash()
        self.genesis_hash = gh
        self.blocks: Dict[bytes, Block] = {gh: genesis_block}
        self.heights: Dict[bytes, int] = {gh: 0}
        self.work: Dict[bytes, int] = {gh: block_work(genesis_block.header.target)}
        self.children: Dict[bytes, List[bytes]] = defaultdict(list)
        self.orphans: Dict[bytes, List[Block]] = defaultdict(list)
        self.tip = gh
        # The genesis block gets no free pass: it must satisfy the same
        # merkle-root and proof-of-work invariants as any other block, or
        # the entire chain's security model is broken starting from block
        # zero (a caller that "forgot" to actually mine it would otherwise
        # go unnoticed until much later, if ever).
        if genesis_block.compute_merkle_root() != genesis_block.header.merkle_root:
            raise ChainError("invalid genesis block: merkle root mismatch")
        if not genesis_block.header.meets_target():
            raise ChainError("invalid genesis block: hash does not meet its declared target")
        genesis_utxo: Dict[Outpoint, TxOut] = {}
        ok, reason = self._apply_txs(genesis_block, genesis_utxo, 0)
        if not ok:
            raise ChainError(f"invalid genesis block: {reason}")
        self._utxo_cache: Tuple[bytes, Dict[Outpoint, TxOut]] = (gh, genesis_utxo)

    # -- public queries --------------------------------------------------
    def height(self) -> int:
        return self.heights[self.tip]

    def tip_block(self) -> Block:
        return self.blocks[self.tip]

    def get_utxo(self, txid: bytes, index: int) -> Optional[TxOut]:
        return self.utxo_set().get((txid, index))

    def utxo_set(self) -> Dict[Outpoint, TxOut]:
        if self._utxo_cache[0] != self.tip:
            snap, ok = self._utxo_snapshot_at(self.tip)
            if not ok:
                raise ChainError("could not reconstruct UTXO set for current tip")
            self._utxo_cache = (self.tip, snap)
        return self._utxo_cache[1]

    def main_chain_hashes(self) -> List[bytes]:
        out = []
        h = self.tip
        while True:
            out.append(h)
            if h == self.genesis_hash:
                break
            h = self.blocks[h].header.prev_hash
        out.reverse()
        return out

    def next_expected_target(self) -> int:
        return self._expected_target(self.tip)

    # -- accepting a new block --------------------------------------------
    def accept_block(self, block: Block, now: Optional[float] = None) -> AcceptResult:
        now = time.time() if now is None else now
        bh = block.block_hash()
        if bh in self.blocks:
            return AcceptResult(False, "duplicate block")
        prev = block.header.prev_hash
        if prev not in self.blocks:
            self.orphans[prev].append(block)
            return AcceptResult(False, "orphan: parent unknown (buffered)")

        ok, reason = self._context_free_checks(block, prev, now)
        if not ok:
            return AcceptResult(False, reason)

        height = self.heights[prev] + 1
        if prev == self.tip:
            # Fast path: extending the current tip directly means the UTXO
            # cache (if fresh) already *is* the base state — no need to
            # replay the whole chain from genesis just to rediscover state
            # we're already holding.
            base_utxo = self.utxo_set()
            ok = True
        else:
            base_utxo, ok = self._utxo_snapshot_at(prev)
        if not ok:
            return AcceptResult(False, "internal error reconstructing parent state")
        scratch = dict(base_utxo)
        valid, reason = self._apply_txs(block, scratch, height)
        if not valid:
            return AcceptResult(False, reason)

        self.blocks[bh] = block
        self.heights[bh] = height
        self.work[bh] = self.work[prev] + block_work(block.header.target)
        self.children[prev].append(bh)

        reorged = False
        if self.work[bh] > self.work[self.tip]:
            old_tip = self.tip
            reorged = prev != old_tip
            self.tip = bh
            self._utxo_cache = (bh, scratch)

        self._try_attach_orphans(bh, now)
        return AcceptResult(True, "accepted", reorged=reorged, new_tip=self.tip if reorged else None)

    def _context_free_checks(self, block: Block, prev: bytes, now: float) -> Tuple[bool, str]:
        if block.compute_merkle_root() != block.header.merkle_root:
            return False, "merkle root mismatch"
        if not block.header.meets_target():
            return False, "block hash does not meet its declared target"
        expected_t = self._expected_target(prev)
        if block.header.target != expected_t:
            return False, f"wrong difficulty target (expected {expected_t}, got {block.header.target})"
        if block.header.timestamp > now + MAX_FUTURE_DRIFT:
            return False, "timestamp too far in the future"
        mtp = self._median_time_past(prev)
        if block.header.timestamp <= mtp:
            return False, "timestamp not after median-time-past of ancestors"
        if not block.transactions or not block.transactions[0].is_coinbase():
            return False, "first transaction must be coinbase"
        if any(t.is_coinbase() for t in block.transactions[1:]):
            return False, "only the first transaction may be a coinbase"
        txids = [t.txid() for t in block.transactions]
        if len(set(txids)) != len(txids):
            return False, "duplicate transaction within block"
        return True, "ok"

    def _try_attach_orphans(self, parent_hash: bytes, now: float) -> None:
        pending = self.orphans.pop(parent_hash, [])
        for orphan in pending:
            self.accept_block(orphan, now)  # may itself unlock further orphans, recursively

    # -- difficulty retargeting -------------------------------------------
    def _expected_target(self, prev_hash: bytes) -> int:
        height = self.heights[prev_hash] + 1
        parent = self.blocks[prev_hash]
        if height % RETARGET_INTERVAL != 0:
            return parent.header.target
        # Window is [height - RETARGET_INTERVAL, height - 1] (RETARGET_INTERVAL
        # blocks). prev_hash is already the block at height-1, so we walk back
        # RETARGET_INTERVAL - 1 more steps to reach the window's first block
        # (same convention real Bitcoin uses for its 2016-block windows).
        window_start = self._ancestor_n_back(prev_hash, RETARGET_INTERVAL - 1)
        if window_start is None:
            return parent.header.target  # not enough history yet
        first_ts = self.blocks[window_start].header.timestamp
        last_ts = parent.header.timestamp
        actual = max(last_ts - first_ts, 1)
        expected = RETARGET_INTERVAL * TARGET_BLOCK_TIME
        ratio = actual / expected
        ratio = max(MIN_RETARGET_FACTOR, min(MAX_RETARGET_FACTOR, ratio))
        new_target = int(parent.header.target * ratio)
        return max(1, min(MAX_TARGET, new_target))

    def _ancestor_n_back(self, block_hash: bytes, n: int) -> Optional[bytes]:
        h = block_hash
        for _ in range(n):
            if h == self.genesis_hash:
                return None
            h = self.blocks[h].header.prev_hash
            if h not in self.blocks:
                return None
        return h

    def _median_time_past(self, prev_hash: bytes) -> int:
        timestamps = []
        h = prev_hash
        for _ in range(MEDIAN_TIME_WINDOW):
            timestamps.append(self.blocks[h].header.timestamp)
            if h == self.genesis_hash:
                break
            h = self.blocks[h].header.prev_hash
        timestamps.sort()
        return timestamps[len(timestamps) // 2]

    # -- UTXO application ---------------------------------------------------
    def _apply_txs(self, block: Block, utxo: Dict[Outpoint, TxOut], height: int) -> Tuple[bool, str]:
        total_fees = 0
        for i, t in enumerate(block.transactions[1:], start=1):
            lookup = (lambda txid, idx, _u=utxo: _u.get((txid, idx)))
            ok, reason = t.verify(lookup)
            if not ok:
                return False, f"tx {i} ({t.txid_hex()[:10]}) invalid: {reason}"
            fee = t.fee(lookup)
            if fee < 0:
                return False, f"tx {i} has negative fee"
            total_fees += fee
            for txin in t.inputs:
                del utxo[(txin.prev_txid, txin.prev_index)]
            txid = t.txid()
            for idx, txout in enumerate(t.outputs):
                utxo[(txid, idx)] = txout

        cb = block.transactions[0]
        cb_ok, cb_reason = cb.verify(lambda a, b: None)
        if not cb_ok:
            return False, f"coinbase invalid: {cb_reason}"
        max_allowed = subsidy_at(height) + total_fees
        if cb.total_output() > max_allowed:
            return False, f"coinbase claims {cb.total_output()} but max allowed is {max_allowed}"
        cb_txid = cb.txid()
        for idx, txout in enumerate(cb.outputs):
            utxo[(cb_txid, idx)] = txout
        return True, "ok"

    def _utxo_snapshot_at(self, block_hash: bytes) -> Tuple[Optional[Dict[Outpoint, TxOut]], bool]:
        # Walk from block_hash back to genesis to build the replay path.
        path = []
        h = block_hash
        while True:
            path.append(h)
            if h == self.genesis_hash:
                break
            h = self.blocks[h].header.prev_hash
            if h not in self.blocks:
                return None, False
        path.reverse()
        utxo: Dict[Outpoint, TxOut] = {}
        for i, hh in enumerate(path):
            ok, reason = self._apply_txs(self.blocks[hh], utxo, i)
            if not ok:
                return None, False
        return utxo, True
