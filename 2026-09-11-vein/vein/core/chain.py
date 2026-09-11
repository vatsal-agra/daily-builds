"""The blockchain: full block/transaction validation, a live UTXO set for
the active chain, and fork resolution by greatest cumulative proof of work
(with a real reorg that rolls back and replays UTXO-set changes).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .block import Block, BlockHeader, bits_to_target, target_to_bits, MAX_TARGET
from .transaction import Transaction, TxOut, merkle_root
from .script import Script, execute, ScriptError

UTXOKey = Tuple[bytes, int]

GENESIS_UNSPENDABLE_PKH = b"\x00" * 20
MAX_FUTURE_DRIFT_SECONDS = 2 * 60 * 60


class ValidationError(Exception):
    """A block or transaction is invalid. Carries a short machine-checkable reason."""


@dataclass
class ChainParams:
    initial_bits: int
    retarget_interval: int = 10
    target_block_time: float = 2.0
    max_adjustment_factor: float = 4.0
    initial_subsidy: int = 50_00000000  # 50.00000000 VEIN, 8 decimal places
    halving_interval: int = 64
    genesis_timestamp: int = 1_700_000_000

    def target_at_genesis(self) -> int:
        return bits_to_target(self.initial_bits)


def subsidy_at_height(height: int, params: ChainParams) -> int:
    halvings = height // params.halving_interval
    if halvings >= 64:
        return 0
    return params.initial_subsidy >> halvings


@dataclass
class BlockMeta:
    header: BlockHeader
    height: int
    work: int
    prev_hash: bytes


@dataclass
class UndoRecord:
    """Everything needed to roll back one applied block's UTXO effects."""
    removed: Dict[UTXOKey, TxOut]  # coins this block spent -> restore them
    added: List[UTXOKey]  # coins this block created -> delete them


class UTXOSet:
    def __init__(self) -> None:
        self.coins: Dict[UTXOKey, TxOut] = {}

    def get(self, txid: bytes, index: int) -> Optional[TxOut]:
        return self.coins.get((txid, index))

    def snapshot_dict(self) -> Dict[UTXOKey, TxOut]:
        return dict(self.coins)


def block_work(bits: int) -> int:
    target = bits_to_target(bits)
    if target <= 0:
        return 0
    return (1 << 256) // (target + 1)


class Blockchain:
    def __init__(self, params: ChainParams):
        self.params = params
        self.blocks: Dict[bytes, Block] = {}
        self.meta: Dict[bytes, BlockMeta] = {}
        self.children: Dict[bytes, List[bytes]] = {}
        self.utxo = UTXOSet()
        self.undo_log: Dict[bytes, UndoRecord] = {}
        self.active_chain: List[bytes] = []  # genesis..tip, by hash
        self._orphans: Dict[bytes, List[Block]] = {}  # missing_parent -> [blocks]
        self._build_genesis()

    # -- genesis --------------------------------------------------------

    def _build_genesis(self) -> None:
        coinbase = Transaction(
            inputs=[_coinbase_input(b"vein genesis")],
            outputs=[TxOut(self.params.initial_subsidy, Script.p2pkh_lock(GENESIS_UNSPENDABLE_PKH))],
        )
        header = BlockHeader(
            version=1,
            prev_hash=b"\x00" * 32,
            merkle_root=merkle_root([coinbase.txid()]),
            timestamp=self.params.genesis_timestamp,
            bits=self.params.initial_bits,
            nonce=0,
        )
        # Mine the real genesis nonce rather than special-casing it —
        # genesis has to satisfy the same PoW rule as every other block.
        target = header.target()
        nonce = 0
        while int.from_bytes(header.hash(), "big") > target:
            nonce += 1
            header.nonce = nonce & 0xFFFFFFFF
            if nonce > 5_000_000:
                raise RuntimeError("genesis mining did not converge; initial_bits too hard")
        block = Block(header, [coinbase])
        h = block.hash()
        self.blocks[h] = block
        self.meta[h] = BlockMeta(header, height=0, work=block_work(header.bits), prev_hash=header.prev_hash)
        self.active_chain = [h]
        self.utxo.coins[(coinbase.txid(), 0)] = coinbase.outputs[0]
        self.undo_log[h] = UndoRecord(removed={}, added=[(coinbase.txid(), 0)])

    @property
    def tip_hash(self) -> bytes:
        return self.active_chain[-1]

    @property
    def height(self) -> int:
        return self.meta[self.tip_hash].height

    def get_block(self, h: bytes) -> Optional[Block]:
        return self.blocks.get(h)

    def has_block(self, h: bytes) -> bool:
        return h in self.blocks

    # -- difficulty -------------------------------------------------------

    def expected_bits_after(self, prev_hash: bytes) -> int:
        parent_meta = self.meta[prev_hash]
        height = parent_meta.height + 1
        interval = self.params.retarget_interval
        if height % interval != 0:
            return parent_meta.header.bits

        # Walk back `interval` blocks along this branch to measure real
        # elapsed time, then retarget exactly like Bitcoin's rule.
        h = prev_hash
        for _ in range(interval - 1):
            h = self.meta[h].prev_hash
        period_start = self.meta[h].header.timestamp
        period_end = parent_meta.header.timestamp
        actual = max(period_end - period_start, 1)
        expected = self.params.target_block_time * interval

        ratio = actual / expected
        ratio = max(1 / self.params.max_adjustment_factor, min(self.params.max_adjustment_factor, ratio))

        old_target = bits_to_target(parent_meta.header.bits)
        new_target = int(old_target * ratio)
        new_target = min(new_target, MAX_TARGET)
        new_target = max(new_target, 1)
        return target_to_bits(new_target)

    # -- validation ---------------------------------------------------------

    def _validate_block_context_free(self, block: Block) -> None:
        header = block.header
        if not block.transactions:
            raise ValidationError("block has no transactions")
        if not block.transactions[0].is_coinbase():
            raise ValidationError("first transaction must be coinbase")
        for tx in block.transactions[1:]:
            if tx.is_coinbase():
                raise ValidationError("only the first transaction may be coinbase")
        computed_root = block.compute_merkle_root()
        if computed_root != header.merkle_root:
            raise ValidationError("merkle root mismatch")
        if not header.meets_target():
            raise ValidationError("proof of work does not meet target")
        txids = [tx.txid() for tx in block.transactions]
        if len(set(txids)) != len(txids):
            raise ValidationError("duplicate transaction ids in block")

    def _apply_block_to_utxo(self, block: Block, utxo: Dict[UTXOKey, TxOut], height: int,
                              check_only: bool) -> UndoRecord:
        """Validate `block`'s transactions against `utxo` (a plain dict used
        as either the live UTXO set or a scratch replay dict) and mutate it
        in place. Returns the UndoRecord needed to reverse these changes.
        """
        removed: Dict[UTXOKey, TxOut] = {}
        added: List[UTXOKey] = []
        total_fees = 0
        spent_this_block: set[UTXOKey] = set()

        for tx in block.transactions[1:]:
            if not tx.inputs or not tx.outputs:
                raise ValidationError(f"tx {tx.txid().hex()[:12]} has no inputs or no outputs")
            fee_in = 0
            for i, txin in enumerate(tx.inputs):
                key = (txin.prev_txid, txin.prev_index)
                if key in spent_this_block:
                    raise ValidationError(f"double spend within block: {key}")
                prevout = utxo.get(key)
                if prevout is None:
                    raise ValidationError(f"tx {tx.txid().hex()[:12]} spends unknown/spent output {key}")
                checker = tx.make_sig_checker(i, prevout.script_pubkey)
                try:
                    ok = execute(txin.script_sig, prevout.script_pubkey, checker)
                except ScriptError as e:
                    raise ValidationError(f"script error: {e}")
                if not ok:
                    raise ValidationError(f"tx {tx.txid().hex()[:12]} input {i} script did not validate")
                fee_in += prevout.value
                spent_this_block.add(key)
                removed[key] = prevout
                del utxo[key]

            out_total = tx.total_output_value()
            if out_total > fee_in:
                raise ValidationError(f"tx {tx.txid().hex()[:12]} spends more than its inputs provide")
            total_fees += fee_in - out_total

            txid = tx.txid()
            for idx, txout in enumerate(tx.outputs):
                key = (txid, idx)
                utxo[key] = txout
                added.append(key)

        coinbase = block.transactions[0]
        max_reward = subsidy_at_height(height, self.params) + total_fees
        coinbase_total = coinbase.total_output_value()
        if coinbase_total > max_reward:
            raise ValidationError(
                f"coinbase claims {coinbase_total}, max allowed is {max_reward} "
                f"(subsidy + fees)"
            )
        coinbase_txid = coinbase.txid()
        for idx, txout in enumerate(coinbase.outputs):
            key = (coinbase_txid, idx)
            utxo[key] = txout
            added.append(key)

        return UndoRecord(removed=removed, added=added)

    def _replay_utxo_at(self, block_hash: bytes) -> Dict[UTXOKey, TxOut]:
        """Reconstruct the UTXO set as of `block_hash` by replaying that
        block's whole ancestry from genesis. O(chain length); fine at the
        block counts a demo/test chain reaches, and keeps reorg logic
        simple and obviously correct rather than fast.
        """
        chain: List[bytes] = []
        h = block_hash
        while h in self.meta:
            chain.append(h)
            if h == self.meta[h].prev_hash:
                break
            parent = self.meta[h].prev_hash
            if parent == b"\x00" * 32:
                break
            h = parent
        chain.reverse()

        utxo: Dict[UTXOKey, TxOut] = {}
        for i, bh in enumerate(chain):
            blk = self.blocks[bh]
            self._apply_block_to_utxo(blk, utxo, height=i, check_only=True)
        return utxo

    # -- adding blocks --------------------------------------------------------

    def add_block(self, block: Block, now: Optional[float] = None, _skip_orphan_drain: bool = False) -> bool:
        """Validate and accept a block. Returns True if the active tip changed.

        Handles three cases: (1) a simple extension of the active tip,
        (2) a block on a side branch that doesn't (yet) beat the active
        chain's cumulative work, stored but not applied, and (3) a block
        that makes some branch overtake the active chain, triggering a
        real reorg (rollback + replay).
        """
        now = time.time() if now is None else now
        h = block.hash()
        if h in self.blocks:
            return False  # already known

        self._validate_block_context_free(block)
        header = block.header

        if header.prev_hash not in self.meta:
            self._orphans.setdefault(header.prev_hash, []).append(block)
            return False

        parent_meta = self.meta[header.prev_hash]
        height = parent_meta.height + 1

        if header.timestamp <= parent_meta.header.timestamp:
            raise ValidationError("timestamp does not advance")
        if header.timestamp > now + MAX_FUTURE_DRIFT_SECONDS:
            raise ValidationError("timestamp too far in the future")

        expected_bits = self.expected_bits_after(header.prev_hash)
        if header.bits != expected_bits:
            raise ValidationError(
                f"bad difficulty bits: got {header.bits:#x}, expected {expected_bits:#x}"
            )

        work = parent_meta.work + block_work(header.bits)
        self.blocks[h] = block
        self.meta[h] = BlockMeta(header, height, work, header.prev_hash)
        self.children.setdefault(header.prev_hash, []).append(h)

        changed = False
        if header.prev_hash == self.tip_hash:
            # Fast path: direct extension of the active chain.
            undo = self._apply_block_to_utxo(block, self.utxo.coins, height, check_only=False)
            self.undo_log[h] = undo
            self.active_chain.append(h)
            changed = True
        elif work > self.meta[self.tip_hash].work:
            self._reorganize_to(h)
            changed = True
        else:
            # Side branch: validate it in isolation (without touching the
            # live UTXO set) so a later block on it can still be checked
            # incrementally, and so a bad side branch is rejected now
            # rather than only when it might have overtaken the tip.
            scratch = self._replay_utxo_at(header.prev_hash)
            self._apply_block_to_utxo(block, scratch, height, check_only=True)

        if not _skip_orphan_drain:
            self._accept_orphans_of(h)
        return changed

    def _reorganize_to(self, new_tip: bytes) -> None:
        # Find the fork point between the current active chain and the
        # ancestry of new_tip.
        new_chain: List[bytes] = []
        h = new_tip
        while h not in set(self.active_chain):
            new_chain.append(h)
            h = self.meta[h].prev_hash
        fork_point = h
        new_chain.reverse()

        fork_index = self.active_chain.index(fork_point)
        old_tail = self.active_chain[fork_index + 1:]

        # Roll back the losing tail, most recent block first.
        for bh in reversed(old_tail):
            undo = self.undo_log.pop(bh)
            for key in undo.added:
                self.utxo.coins.pop(key, None)
            for key, txout in undo.removed.items():
                self.utxo.coins[key] = txout

        # Replay the winning branch forward, from just after the fork
        # point through the new tip, mutating the *real* UTXO set now.
        active = self.active_chain[:fork_index + 1]
        for bh in new_chain:
            blk = self.blocks[bh]
            height = self.meta[bh].height
            undo = self._apply_block_to_utxo(blk, self.utxo.coins, height, check_only=False)
            self.undo_log[bh] = undo
            active.append(bh)

        self.active_chain = active

    def _accept_orphans_of(self, parent_hash: bytes) -> None:
        # Iterative, not recursive: add_block() itself calls this method
        # at the end of every successful application, so a naive
        # recursive "pop this parent's orphans, call add_block on each"
        # re-enters _accept_orphans_of through add_block for every block
        # in the chain — a hostile peer relaying a few thousand blocks in
        # reverse order would blow Python's recursion limit. A plain
        # queue drains the same cascade without growing the call stack.
        queue = list(self._orphans.pop(parent_hash, []))
        while queue:
            blk = queue.pop()
            h = blk.hash()
            self._apply_or_buffer(blk)
            queue.extend(self._orphans.pop(h, []))

    def _apply_or_buffer(self, block: "Block") -> bool:
        """Like add_block(), but never itself recurses into
        _accept_orphans_of — the caller (either add_block's own top-level
        call, or the iterative drain above) is responsible for that."""
        return self.add_block(block, _skip_orphan_drain=True)

    # -- queries ----------------------------------------------------------

    def balance_of(self, pubkey_hash: bytes) -> int:
        total = 0
        for txout in self.utxo.coins.values():
            if txout.script_pubkey.is_p2pkh() and txout.script_pubkey.ops[2] == pubkey_hash:
                total += txout.value
        return total

    def utxos_for(self, pubkey_hash: bytes) -> List[Tuple[UTXOKey, TxOut]]:
        out = []
        for key, txout in self.utxo.coins.items():
            if txout.script_pubkey.is_p2pkh() and txout.script_pubkey.ops[2] == pubkey_hash:
                out.append((key, txout))
        return out

    def all_tips(self) -> List[Tuple[bytes, int, int]]:
        """(hash, height, cumulative work) for every known chain tip."""
        parents = set(self.meta[h].prev_hash for h in self.meta)
        tips = [h for h in self.meta if h not in parents]
        return [(h, self.meta[h].height, self.meta[h].work) for h in tips]


def _coinbase_input(extra: bytes):
    from .transaction import TxIn, NULL_TXID, NULL_INDEX
    return TxIn(NULL_TXID, NULL_INDEX, Script([extra[:75]]))


def make_coinbase(height: int, reward: int, pubkey_hash: bytes, extra_nonce: int = 0) -> Transaction:
    from .transaction import TxIn, TxOut, NULL_TXID, NULL_INDEX
    tag = f"height={height},en={extra_nonce}".encode()
    return Transaction(
        inputs=[TxIn(NULL_TXID, NULL_INDEX, Script([tag[:75]]))],
        outputs=[TxOut(reward, Script.p2pkh_lock(pubkey_hash))],
    )
