"""The blockchain itself: a tree of blocks, a UTXO set, full transaction/
block validation, and reorg (fork-switch) logic driven by cumulative work
— Nakamoto consensus, not height, decides the winning chain, exactly like
real Bitcoin (a longer-but-lower-work chain must never win).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .block import Block, GENESIS_PREV_HASH, target_from_bits, validate_block_shape
from .crypto import pubkey_to_address
from .transaction import Transaction

BLOCK_REWARD = 50
RETARGET_INTERVAL = 10          # blocks between difficulty adjustments
RETARGET_TIMESPAN_SECONDS = 20  # target: 10 blocks every 20s (~2s/block)
MAX_RETARGET_FACTOR = 4.0       # clamp any single adjustment to 4x/0.25x


@dataclass
class UndoRecord:
    spent: List[Tuple[str, int, dict]]   # (txid, index, {"address":..,"amount":..}) restored on disconnect
    created: List[Tuple[str, int]]        # (txid, index) removed on disconnect


class ValidationError(Exception):
    pass


class Blockchain:
    def __init__(self, retarget_enabled: bool = False):
        self.blocks: Dict[str, Block] = {}
        self.parents: Dict[str, str] = {}
        self.heights: Dict[str, int] = {}
        self.cum_work: Dict[str, int] = {}
        self.children: Dict[str, List[str]] = {}
        self.utxo_set: Dict[Tuple[str, int], dict] = {}
        self.undo_log: Dict[str, UndoRecord] = {}
        self.tip: Optional[str] = None
        self.invalid: set = set()
        self.retarget_enabled = retarget_enabled  # flipped on in Phase 4 (stretch feature)
        self._last_reorg_info: Optional[dict] = None

    # --- read-only views -------------------------------------------------
    def height(self) -> int:
        return self.heights.get(self.tip, -1) if self.tip else -1

    def get_block(self, h: str) -> Optional[Block]:
        return self.blocks.get(h)

    def active_chain_hashes(self) -> List[str]:
        """Genesis-first list of block hashes on the current best chain."""
        out = []
        h = self.tip
        while h is not None:
            out.append(h)
            h = self.parents.get(h)
            if h == GENESIS_PREV_HASH:
                break
        return list(reversed(out))

    def balance_of(self, address: str) -> int:
        return sum(u["amount"] for u in self.utxo_set.values() if u["address"] == address)

    def utxos_for(self, address: str) -> List[Tuple[str, int, int]]:
        return [
            (txid, idx, u["amount"])
            for (txid, idx), u in self.utxo_set.items()
            if u["address"] == address
        ]

    # --- difficulty --------------------------------------------------
    def calc_next_bits(self, parent_hash: str, genesis_bits: int) -> int:
        """Bitcoin-style retarget: every RETARGET_INTERVAL blocks, compare
        actual vs. expected elapsed time and adjust, clamped. Disabled
        (fixed difficulty) until Phase 4 turns it on — see REVIEW.md."""
        if not self.retarget_enabled or parent_hash == GENESIS_PREV_HASH:
            return genesis_bits
        parent_height = self.heights[parent_hash]
        next_height = parent_height + 1
        if next_height % RETARGET_INTERVAL != 0:
            return self.blocks[parent_hash].header.bits
        # walk back RETARGET_INTERVAL blocks along the parent's chain
        h = parent_hash
        for _ in range(RETARGET_INTERVAL - 1):
            h = self.parents[h]
        period_start_ts = self.blocks[h].header.timestamp
        period_end_ts = self.blocks[parent_hash].header.timestamp
        actual = max(period_end_ts - period_start_ts, 1.0)
        ratio = RETARGET_TIMESPAN_SECONDS / actual
        ratio = max(1.0 / MAX_RETARGET_FACTOR, min(MAX_RETARGET_FACTOR, ratio))
        old_bits = self.blocks[parent_hash].header.bits
        # bits is log2(target-shrink), so scaling target by `ratio` means
        # shifting bits by log2(ratio)
        new_bits = old_bits + round(math.log2(ratio))
        return max(1, min(63, new_bits))

    # --- validation --------------------------------------------------
    def _validate_and_compute_effect(
        self, block: Block, utxo_view: Dict[Tuple[str, int], dict]
    ) -> Tuple[bool, str, Optional[UndoRecord]]:
        """Pure function: checks `block`'s transactions against `utxo_view`
        WITHOUT mutating it. Returns the undo record to apply if valid."""
        spent_in_block: set = set()
        spent_undo: List[Tuple[str, int, dict]] = []
        created: List[Tuple[str, int]] = []
        total_fees = 0
        working_removed: set = set()

        for tx in block.transactions:
            if tx.is_coinbase:
                continue
            total_in = 0
            for txin in tx.inputs:
                key = (txin.prev_txid, txin.prev_index)
                if key in working_removed or key in spent_in_block:
                    return False, f"double-spend of {key} within block", None
                utxo = utxo_view.get(key)
                if utxo is None:
                    return False, f"input references unknown/spent utxo {key}", None
                owner_addr = pubkey_to_address(bytes.fromhex(txin.pubkey))
                if owner_addr != utxo["address"]:
                    return False, f"input pubkey does not own utxo {key} (owner={utxo['address']})", None
                total_in += utxo["amount"]
                spent_in_block.add(key)
                working_removed.add(key)
                spent_undo.append((key[0], key[1], utxo))
            total_out = tx.total_output()
            if total_in < total_out:
                return False, f"transaction {tx.txid()[:8]} spends more than its inputs provide", None
            total_fees += total_in - total_out

        coinbase = block.transactions[0]
        if block.header.height == 0:
            # the genesis block's coinbase is a one-time allocation (this
            # project's "premine"), not a mining reward — exempt from the
            # reward+fees cap that applies to every other block.
            pass
        else:
            max_coinbase = BLOCK_REWARD + total_fees
            if coinbase.total_output() > max_coinbase:
                return False, f"coinbase claims {coinbase.total_output()}, max allowed is {max_coinbase}", None

        for tx in block.transactions:
            txid = tx.txid()
            for idx, out in enumerate(tx.outputs):
                created.append((txid, idx))

        return True, "", UndoRecord(spent=spent_undo, created=created)

    # --- mutation helpers ----------------------------------------------
    def _apply(self, block: Block, utxo_view: Dict[Tuple[str, int], dict], undo: UndoRecord) -> None:
        for txid, idx, _old in undo.spent:
            del utxo_view[(txid, idx)]
        for tx in block.transactions:
            txid = tx.txid()
            for idx, out in enumerate(tx.outputs):
                utxo_view[(txid, idx)] = {"address": out.address, "amount": out.amount}

    def _disconnect(self, block_hash: str, utxo_view: Dict[Tuple[str, int], dict]) -> List[Transaction]:
        undo = self.undo_log[block_hash]
        for txid, idx in undo.created:
            utxo_view.pop((txid, idx), None)
        for txid, idx, old in undo.spent:
            utxo_view[(txid, idx)] = old
        block = self.blocks[block_hash]
        return [tx for tx in block.transactions if not tx.is_coinbase]

    # --- registration --------------------------------------------------
    def _register_block(self, block: Block, h: str, parent_hash: str) -> None:
        self.blocks[h] = block
        self.parents[h] = parent_hash
        height = 0 if parent_hash == GENESIS_PREV_HASH else self.heights[parent_hash] + 1
        self.heights[h] = height
        parent_work = 0 if parent_hash == GENESIS_PREV_HASH else self.cum_work[parent_hash]
        self.cum_work[h] = parent_work + block.cumulative_work_contribution()
        self.children.setdefault(parent_hash, []).append(h)

    def _deregister_subtree(self, h: str) -> None:
        for child in list(self.children.get(h, [])):
            self._deregister_subtree(child)
        self.blocks.pop(h, None)
        self.parents.pop(h, None)
        self.heights.pop(h, None)
        self.cum_work.pop(h, None)
        self.children.pop(h, None)
        self.invalid.add(h)

    def _find_fork_point(self, a: str, b: str) -> str:
        while self.heights[a] > self.heights[b]:
            a = self.parents[a]
        while self.heights[b] > self.heights[a]:
            b = self.parents[b]
        while a != b:
            a = self.parents[a]
            b = self.parents[b]
        return a

    # --- the public entry point ------------------------------------------
    def add_block(self, block: Block, genesis_bits: int) -> Tuple[bool, str, Optional[dict]]:
        """Try to accept `block`. Returns (accepted, message, reorg_info).
        reorg_info, when present, is {"disconnected_txs": [...], "connected_txids": set()}."""
        h = block.hash_hex()
        if h in self.blocks or h in self.invalid:
            return False, "already known", None

        shape_err = validate_block_shape(block)
        if shape_err:
            self.invalid.add(h)
            return False, shape_err, None

        parent_hash = block.header.prev_hash
        if parent_hash != GENESIS_PREV_HASH and parent_hash not in self.blocks:
            return False, "orphan: unknown parent (request the chain from a peer)", None

        expected_height = 0 if parent_hash == GENESIS_PREV_HASH else self.heights[parent_hash] + 1
        if block.header.height != expected_height:
            self.invalid.add(h)
            return False, f"bad height: expected {expected_height}, got {block.header.height}", None

        expected_bits = self.calc_next_bits(parent_hash, genesis_bits) if self.tip is not None else genesis_bits
        if block.header.bits != expected_bits:
            self.invalid.add(h)
            return False, f"bad difficulty bits: expected {expected_bits}, got {block.header.bits}", None

        self._register_block(block, h, parent_hash)

        if self.tip is None:
            ok, err, undo = self._validate_and_compute_effect(block, self.utxo_set)
            if not ok:
                self._deregister_subtree(h)
                return False, err, None
            self._apply(block, self.utxo_set, undo)
            self.undo_log[h] = undo
            self.tip = h
            return True, "genesis accepted", None

        if parent_hash == self.tip:
            ok, err, undo = self._validate_and_compute_effect(block, self.utxo_set)
            if not ok:
                self._deregister_subtree(h)
                return False, err, None
            self._apply(block, self.utxo_set, undo)
            self.undo_log[h] = undo
            self.tip = h
            return True, "extended tip", {"disconnected_txs": [], "connected_txids": {t.txid() for t in block.transactions}}

        if self.cum_work[h] <= self.cum_work[self.tip]:
            return True, "stored as side branch (insufficient work to reorg)", None

        ok, err = self._reorganize_to(h, genesis_bits)
        if not ok:
            self._deregister_subtree(h)
            return False, err, None
        return True, "reorg", self._last_reorg_info

    def _reorganize_to(self, new_tip: str, genesis_bits: int) -> Tuple[bool, str]:
        fork = self._find_fork_point(self.tip, new_tip)
        working = dict(self.utxo_set)

        disconnect_chain = []
        h = self.tip
        while h != fork:
            disconnect_chain.append(h)
            h = self.parents[h]

        connect_chain = []
        h = new_tip
        while h != fork:
            connect_chain.append(h)
            h = self.parents[h]
        connect_chain.reverse()

        disconnected_txs: List[Transaction] = []
        for bh in disconnect_chain:
            disconnected_txs.extend(self._disconnect(bh, working))

        new_undo: Dict[str, UndoRecord] = {}
        connected_txids: set = set()
        for bh in connect_chain:
            block = self.blocks[bh]
            ok, err, undo = self._validate_and_compute_effect(block, working)
            if not ok:
                # abort: discard the bad tip and everything under it, keep old tip
                self._deregister_subtree(bh)
                return False, f"reorg aborted: {err}"
            self._apply(block, working, undo)
            new_undo[bh] = undo
            connected_txids |= {t.txid() for t in block.transactions}

        # commit
        self.utxo_set = working
        for bh in disconnect_chain:
            del self.undo_log[bh]
        self.undo_log.update(new_undo)
        self.tip = new_tip

        # transactions that were disconnected but also got re-connected
        # (present in both branches) shouldn't bounce back into the mempool
        surviving = [tx for tx in disconnected_txs if tx.txid() not in connected_txids]
        self._last_reorg_info = {"disconnected_txs": surviving, "connected_txids": connected_txids}
        return True, "ok"
