"""The Blockchain: full block validation, UTXO-set maintenance, and fork
choice by cumulative proof-of-work (not chain length — a longer chain of
easy blocks loses to a shorter chain of harder ones)."""

import time

from . import curve, pow as powmod
from .block import Block

BASE_REWARD = 50
MAX_FUTURE_DRIFT_SECONDS = 3600


class InvalidBlock(Exception):
    pass


class Blockchain:
    def __init__(self, genesis_block: Block):
        gh = genesis_block.hash()
        self.blocks_by_hash = {gh: genesis_block}
        self.height_of = {gh: 0}
        self.parent_of = {gh: None}
        self.children = {gh: []}
        self.work_of = {gh: self._block_work(genesis_block.target)}
        self.utxo_at = {gh: self._apply_block(genesis_block, {}, is_genesis=True)}
        self.genesis_hash = gh
        self.tip_hash = gh

    # -- basic queries --------------------------------------------------

    @staticmethod
    def _block_work(target: int) -> int:
        return (powmod.MAX_TARGET // target) if target else 0

    def height(self) -> int:
        return self.height_of[self.tip_hash]

    @property
    def utxo(self) -> dict:
        return self.utxo_at[self.tip_hash]

    def get_block(self, block_hash):
        return self.blocks_by_hash.get(block_hash)

    def has_block(self, block_hash):
        return block_hash in self.blocks_by_hash

    def main_chain_hashes(self):
        """Genesis -> tip, in order."""
        out = []
        h = self.tip_hash
        while h is not None:
            out.append(h)
            h = self.parent_of[h]
        return list(reversed(out))

    def main_chain_txids(self):
        ids = set()
        for h in self.main_chain_hashes():
            for tx in self.blocks_by_hash[h].transactions:
                ids.add(tx.txid())
        return ids

    def _ancestor(self, block_hash, n):
        for _ in range(n):
            block_hash = self.parent_of[block_hash]
            if block_hash is None:
                return None
        return block_hash

    def expected_target(self, parent_hash) -> int:
        parent = self.blocks_by_hash[parent_hash]
        height = self.height_of[parent_hash] + 1
        if height % powmod.RETARGET_INTERVAL != 0:
            return parent.target
        back = self._ancestor(parent_hash, powmod.RETARGET_INTERVAL - 1)
        if back is None:
            return parent.target
        window_start = self.blocks_by_hash[back]
        actual_seconds = parent.timestamp - window_start.timestamp
        return powmod.next_target(parent.target, actual_seconds, powmod.RETARGET_INTERVAL)

    # -- validation + application ----------------------------------------

    def _apply_block(self, block: Block, parent_utxo: dict, is_genesis=False) -> dict:
        """Validates `block` against `parent_utxo` and returns the resulting
        UTXO dict. Raises InvalidBlock on any rule violation. Does not
        mutate parent_utxo."""
        utxo = dict(parent_utxo)

        if not block.transactions:
            raise InvalidBlock("block has no transactions")
        coinbase = block.transactions[0]
        if not coinbase.is_coinbase:
            raise InvalidBlock("first transaction must be coinbase")
        for tx in block.transactions[1:]:
            if tx.is_coinbase:
                raise InvalidBlock("only the first transaction may be coinbase")

        seen_in_block = set()
        total_fees = 0
        for tx in block.transactions[1:]:
            if not tx.inputs:
                raise InvalidBlock("non-coinbase transaction has no inputs")
            total_in = 0
            for i, inp in enumerate(tx.inputs):
                key = (inp.txid, inp.index)
                if key in seen_in_block:
                    raise InvalidBlock(f"double-spend within block: {key}")
                seen_in_block.add(key)
                utxo_entry = utxo.get(key)
                if utxo_entry is None:
                    raise InvalidBlock(f"input {key} spends an unknown or already-spent output")
                if not tx.verify_input_signature(i):
                    raise InvalidBlock(f"invalid signature on tx {tx.txid()} input {i}")
                point = curve.decompress_pubkey(inp.pubkey)
                if curve.pubkey_to_address(point) != utxo_entry.address:
                    raise InvalidBlock("input pubkey does not match the UTXO's owning address")
                total_in += utxo_entry.amount
                del utxo[key]
            total_out = tx.total_output()
            if total_out > total_in:
                raise InvalidBlock(f"tx {tx.txid()} outputs exceed inputs")
            total_fees += total_in - total_out
            txid = tx.txid()
            for idx, out in enumerate(tx.outputs):
                utxo[(txid, idx)] = out

        if not is_genesis:
            max_coinbase = BASE_REWARD + total_fees
            if coinbase.total_output() > max_coinbase:
                raise InvalidBlock(
                    f"coinbase pays {coinbase.total_output()}, max allowed is {max_coinbase}"
                )
        if len(coinbase.outputs) != 1:
            raise InvalidBlock("coinbase must have exactly one output")
        cb_txid = coinbase.txid()
        utxo[(cb_txid, 0)] = coinbase.outputs[0]

        # NOTE: there is deliberately no separate "claimed vs. actual merkle
        # root" check here. Block.merkle_root_hex is always computed live
        # from block.transactions (never trusted from an incoming wire
        # value — Block.from_dict discards the header's merkle_root field
        # entirely), so block.hash() already binds the PoW-checked header
        # to whatever transaction list is actually attached: tampering
        # with block.transactions after construction changes merkle_root_hex,
        # which changes hash(), which (overwhelmingly likely) breaks the
        # proof-of-work the block was mined for. An earlier version of this
        # method compared merkle_root([...block.transactions]) against
        # block.merkle_root_hex — both computed from the same live list, so
        # it could never fail. That tautological check gave false confidence
        # (see REVIEW.md) and has been removed rather than kept as theater.

        return utxo

    def add_block(self, block: Block):
        """Returns (accepted: bool, became_tip: bool, orphaned_txs: list[Transaction], reason: str|None)."""
        h = block.hash()
        if h in self.blocks_by_hash:
            return True, False, [], "already known"

        if block.prev_hash not in self.blocks_by_hash:
            return False, False, [], "unknown parent"

        parent_hash = block.prev_hash
        expected = self.expected_target(parent_hash)
        if block.target != expected:
            return False, False, [], f"wrong difficulty target: got {block.target}, expected {expected}"
        if not powmod.meets_target(bytes.fromhex(h), block.target):
            return False, False, [], "proof-of-work does not meet target"
        if block.height != self.height_of[parent_hash] + 1:
            return False, False, [], "wrong height"
        if block.timestamp < self.blocks_by_hash[parent_hash].timestamp:
            return False, False, [], "timestamp before parent"
        if block.timestamp > time.time() + MAX_FUTURE_DRIFT_SECONDS:
            # without this, a miner could stamp an inflated timestamp with no
            # upper bound; since the retarget window (expected_target) reads
            # real ancestor timestamps to compute elapsed time, an unbounded
            # future timestamp lets a single miner manufacture an artificially
            # long "elapsed" window and skew the next difficulty retarget
            return False, False, [], "timestamp too far in the future"

        try:
            new_utxo = self._apply_block(block, self.utxo_at[parent_hash])
        except InvalidBlock as e:
            return False, False, [], str(e)

        self.blocks_by_hash[h] = block
        self.height_of[h] = self.height_of[parent_hash] + 1
        self.parent_of[h] = parent_hash
        self.children.setdefault(parent_hash, []).append(h)
        self.children.setdefault(h, [])
        self.work_of[h] = self.work_of[parent_hash] + self._block_work(block.target)
        self.utxo_at[h] = new_utxo

        became_tip = False
        orphaned_txs = []
        old_tip = self.tip_hash
        if self._is_better_chain(h, old_tip):
            orphaned_txs = self._orphaned_transactions(old_tip, h)
            self.tip_hash = h
            became_tip = True

        return True, became_tip, orphaned_txs, None

    def _is_better_chain(self, candidate_hash, current_hash):
        cw, ch = self.work_of[candidate_hash], self.work_of[current_hash]
        if cw != ch:
            return cw > ch
        return candidate_hash < current_hash  # deterministic tie-break

    def _common_ancestor(self, a_hash, b_hash):
        a_chain = set()
        h = a_hash
        while h is not None:
            a_chain.add(h)
            h = self.parent_of[h]
        h = b_hash
        while h not in a_chain:
            h = self.parent_of[h]
        return h

    def _orphaned_transactions(self, old_tip, new_tip):
        """Non-coinbase transactions present on the losing branch (from the
        fork point to old_tip) that are NOT present on the winning branch
        (from the fork point to new_tip) — candidates to restore to the
        mempool since they're no longer confirmed."""
        ancestor = self._common_ancestor(old_tip, new_tip)

        def branch_txids(tip):
            ids, h = {}, tip
            while h != ancestor:
                for tx in self.blocks_by_hash[h].transactions:
                    if not tx.is_coinbase:
                        ids[tx.txid()] = tx
                h = self.parent_of[h]
            return ids

        old_branch = branch_txids(old_tip)
        new_branch = branch_txids(new_tip)
        return [tx for txid, tx in old_branch.items() if txid not in new_branch]

    def next_block_target(self):
        return self.expected_target(self.tip_hash)
