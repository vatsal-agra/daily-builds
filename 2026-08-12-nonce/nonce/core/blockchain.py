"""Chain state: the block tree, the active-chain UTXO set, full
transaction/block validation, and fork resolution (Nakamoto consensus —
the chain with the most cumulative proof-of-work wins, and losing forks
are reorganized away from).

Design note on scale: this implementation caches a full UTXO-set
*snapshot* on every connected block (block_meta[hash]['utxo_snapshot'])
rather than maintaining a single mutable set plus an undo-log. That's the
right tradeoff at the block counts a same-day demo produces (tens to a
few hundred blocks, small UTXO sets) — it makes fork handling and
snapshot-at-any-height trivially correct by construction, at the cost of
an O(utxo set size) copy per block, which a production chain (with a
much bigger UTXO set) would not accept.
"""

import time

from .transaction import Transaction, pubkey_to_address
from .block import Block, genesis_block
from .difficulty import next_bits, work_for_bits, target_to_bits, MAX_TARGET, RETARGET_INTERVAL
from .miner import mine

SUBSIDY = 50_00000000          # 50 coins, in the smallest unit ("sats"), 8 decimal places
HALVING_INTERVAL = 150         # demo-scaled block reward halving
MAX_FUTURE_DRIFT_SECONDS = 7200
COIN = 100000000


def subsidy_at(height: int) -> int:
    halvings = height // HALVING_INTERVAL
    if halvings >= 32:
        return 0
    return SUBSIDY >> halvings


class ReorgInfo:
    def __init__(self, disconnected, connected, fork_height):
        self.disconnected = disconnected   # list[Block], old-tip-first
        self.connected = connected         # list[Block], fork-point-first
        self.fork_height = fork_height


class AddBlockResult:
    def __init__(self, status, block_hash=None, reason=None, reorg=None, resolved_orphans=None):
        self.status = status  # 'new_tip' | 'side_branch' | 'orphan' | 'duplicate' | 'invalid'
        self.block_hash = block_hash
        self.reason = reason
        self.reorg = reorg
        self.resolved_orphans = resolved_orphans or []

    def __repr__(self):
        return f"AddBlockResult({self.status!r}, reason={self.reason!r})"


def create_genesis(reward_address: str, timestamp=None) -> Block:
    """Build and mine the genesis block. Its target is intentionally the
    easiest allowed (MAX_TARGET) so it mines almost instantly."""
    bits = target_to_bits(MAX_TARGET)
    ts = timestamp if timestamp is not None else int(time.time())
    coinbase = Transaction.coinbase(reward_address, subsidy_at(0), extra_nonce=0)
    block = genesis_block(coinbase, bits, ts)
    mine(block)
    return block


class Blockchain:
    def __init__(self, genesis: Block):
        h = genesis.hash()
        genesis.height = 0
        cb = genesis.transactions[0]
        utxo = {(cb.txid(), 0): cb.outputs[0]}
        work = work_for_bits(genesis.header.bits)

        self.blocks = {h: genesis}
        self.block_meta = {h: {"height": 0, "work": work, "prev_hash": None, "utxo_snapshot": utxo}}
        self.tip_hash = h
        self.genesis_hash = h
        self.utxo_set = dict(utxo)
        self.orphans = {}  # prev_hash (bytes) -> list[Block] waiting on that parent

    # ------------------------------------------------------------------
    # queries

    def height(self) -> int:
        return self.block_meta[self.tip_hash]["height"]

    def tip(self) -> Block:
        return self.blocks[self.tip_hash]

    def get_ancestor(self, block_hash: bytes, generations_back: int) -> bytes:
        h = block_hash
        for _ in range(generations_back):
            prev = self.block_meta[h]["prev_hash"]
            if prev is None:
                return h
            h = prev
        return h

    def balance(self, address: str) -> int:
        return sum(o.amount for o in self.utxo_set.values() if o.to_address == address)

    def utxos_for(self, address: str):
        return {k: v for k, v in self.utxo_set.items() if v.to_address == address}

    def chain_to_genesis(self, block_hash=None):
        """List of block hashes from genesis to block_hash (inclusive), oldest first."""
        h = block_hash if block_hash is not None else self.tip_hash
        chain = []
        while h is not None:
            chain.append(h)
            h = self.block_meta[h]["prev_hash"]
        return list(reversed(chain))

    # ------------------------------------------------------------------
    # difficulty

    def expected_bits(self, prev_hash: bytes) -> int:
        parent_meta = self.block_meta[prev_hash]
        parent_block = self.blocks[prev_hash]
        next_height = parent_meta["height"] + 1
        actual_timespan = 0
        if next_height % RETARGET_INTERVAL == 0:
            window_start_hash = self.get_ancestor(prev_hash, RETARGET_INTERVAL - 1)
            window_start_block = self.blocks[window_start_hash]
            actual_timespan = parent_block.header.timestamp - window_start_block.header.timestamp
        return next_bits(parent_block.header.bits, parent_meta["height"], actual_timespan)

    # ------------------------------------------------------------------
    # validation

    def _apply_transactions(self, block: Block, utxo: dict, height: int):
        """Validates and applies block.transactions to utxo (mutated in
        place). Returns (ok, reason, total_fees)."""
        if not block.transactions or not block.transactions[0].is_coinbase():
            return False, "block missing coinbase as first transaction", 0
        for tx in block.transactions[1:]:
            if tx.is_coinbase():
                return False, "more than one coinbase transaction", 0

        total_fees = 0
        seen_txids = set()
        for tx in block.transactions[1:]:
            txid = tx.txid()
            if txid in seen_txids:
                return False, f"duplicate transaction {txid.hex()} in block", 0
            seen_txids.add(txid)

            if not tx.inputs:
                return False, "transaction has no inputs", 0
            if not tx.verify_signatures():
                return False, f"invalid signature on transaction {txid.hex()}", 0

            input_sum = 0
            consumed = []
            for txin in tx.inputs:
                key = (txin.prev_txid, txin.prev_index)
                utxo_entry = utxo.get(key)
                if utxo_entry is None:
                    return False, f"transaction {txid.hex()} spends an unknown or already-spent output", 0
                if pubkey_to_address(txin.pubkey) != utxo_entry.to_address:
                    return False, f"transaction {txid.hex()} signature does not match the UTXO owner", 0
                consumed.append(key)
                input_sum += utxo_entry.amount

            output_sum = tx.total_output()
            if output_sum > input_sum:
                return False, f"transaction {txid.hex()} spends more than its inputs provide", 0

            total_fees += input_sum - output_sum
            for key in consumed:
                del utxo[key]
            for idx, txout in enumerate(tx.outputs):
                utxo[(txid, idx)] = txout

        coinbase_tx = block.transactions[0]
        if len(coinbase_tx.outputs) != 1:
            return False, "coinbase must have exactly one output", 0
        expected_reward = subsidy_at(height) + total_fees
        if coinbase_tx.outputs[0].amount != expected_reward:
            return False, (f"bad coinbase reward: paid {coinbase_tx.outputs[0].amount}, "
                            f"expected {expected_reward} (subsidy {subsidy_at(height)} + fees {total_fees})"), 0
        utxo[(coinbase_tx.txid(), 0)] = coinbase_tx.outputs[0]
        return True, None, total_fees

    def _validate_and_connect(self, block: Block, prev_hash: bytes):
        """Full validation of `block` extending prev_hash. Returns
        (ok, reason, utxo_snapshot, work)."""
        parent_meta = self.block_meta[prev_hash]
        parent_block = self.blocks[prev_hash]

        expected_bits = self.expected_bits(prev_hash)
        if block.header.bits != expected_bits:
            return False, f"bad difficulty bits: got {block.header.bits:#x}, expected {expected_bits:#x}", None, None
        if not block.header.meets_target():
            return False, "block hash does not meet the proof-of-work target", None, None
        if block.header.timestamp < parent_block.header.timestamp:
            return False, "block timestamp is not after its parent's", None, None
        if block.header.timestamp > int(time.time()) + MAX_FUTURE_DRIFT_SECONDS:
            return False, "block timestamp too far in the future", None, None

        from .merkle import merkle_root as compute_merkle_root
        recomputed_root = compute_merkle_root([tx.txid() for tx in block.transactions])
        if recomputed_root != block.header.merkle_root:
            return False, "merkle root does not match the block's transactions", None, None

        utxo_snapshot = dict(parent_meta["utxo_snapshot"])
        height = parent_meta["height"] + 1
        ok, reason, _fees = self._apply_transactions(block, utxo_snapshot, height)
        if not ok:
            return False, reason, None, None

        work = parent_meta["work"] + work_for_bits(block.header.bits)
        return True, None, utxo_snapshot, work

    # ------------------------------------------------------------------
    # mutation

    def add_block(self, block: Block) -> AddBlockResult:
        h = block.hash()
        if h in self.blocks:
            return AddBlockResult("duplicate", block_hash=h)

        prev_hash = block.header.prev_hash
        if prev_hash not in self.block_meta:
            self.orphans.setdefault(prev_hash, []).append(block)
            return AddBlockResult("orphan", block_hash=h, reason=f"unknown parent {prev_hash.hex()[:12]}")

        ok, reason, utxo_snapshot, work = self._validate_and_connect(block, prev_hash)
        if not ok:
            return AddBlockResult("invalid", block_hash=h, reason=reason)

        block.height = self.block_meta[prev_hash]["height"] + 1
        self.blocks[h] = block
        self.block_meta[h] = {"height": block.height, "work": work, "prev_hash": prev_hash,
                               "utxo_snapshot": utxo_snapshot}

        reorg = None
        tip_work = self.block_meta[self.tip_hash]["work"]
        # Tie-break equal-work forks by hash (lower wins) rather than only
        # "first seen": two independent miners finding a block at nearly
        # the same time is a routine, expected event (not an attack), and
        # with a pure first-seen rule, different nodes can each keep a
        # different tip forever — whichever one THEY happened to see
        # first — with no guarantee resync ever reconciles them, since
        # neither side's work is ever *strictly* greater than the
        # other's. Comparing hashes is deterministic and every node
        # computes the exact same comparison over the exact same two
        # blocks, so once all nodes have seen both sides of a tie, they
        # all converge on the identical tip immediately — no need to wait
        # for a third block to break the tie.
        if work > tip_work or (work == tip_work and h < self.tip_hash):
            reorg = self._reorg_to(h)
            self.tip_hash = h
            self.utxo_set = utxo_snapshot
            status = "new_tip"
        else:
            status = "side_branch"

        result = AddBlockResult(status, block_hash=h, reorg=reorg)

        for orphan in self.orphans.pop(h, []):
            sub_result = self.add_block(orphan)
            result.resolved_orphans.append(sub_result)

        return result

    def _reorg_to(self, new_tip_hash: bytes) -> ReorgInfo:
        old_tip_hash = self.tip_hash
        a, b = old_tip_hash, new_tip_hash
        # walk both hashes up to equal height
        while self.block_meta[a]["height"] > self.block_meta[b]["height"]:
            a = self.block_meta[a]["prev_hash"]
        while self.block_meta[b]["height"] > self.block_meta[a]["height"]:
            b = self.block_meta[b]["prev_hash"]
        while a != b:
            a = self.block_meta[a]["prev_hash"]
            b = self.block_meta[b]["prev_hash"]
        fork_hash = a
        fork_height = self.block_meta[fork_hash]["height"]

        disconnected = []
        h = old_tip_hash
        while h != fork_hash:
            disconnected.append(self.blocks[h])
            h = self.block_meta[h]["prev_hash"]

        connected = []
        h = new_tip_hash
        while h != fork_hash:
            connected.append(self.blocks[h])
            h = self.block_meta[h]["prev_hash"]
        connected.reverse()

        return ReorgInfo(disconnected, connected, fork_height)

    def mine_new_block(self, mempool_txs, reward_address: str, extra_nonce=0, should_abort=None) -> Block:
        """Assemble a candidate block from mempool_txs on top of the
        current tip, mine it (blocking), and return the mined block. Does
        NOT call add_block — caller decides when/whether to submit it.

        Selection walks a local UTXO copy and applies each accepted tx to
        it immediately (mirroring _apply_transactions' own rules — same
        UTXO-existence, signature, ownership, and balance checks — right
        down to using the same local-copy-and-apply structure) rather
        than checking every tx against the static confirmed UTXO set.
        That matters for real cases a naive "check against self.utxo_set"
        selection gets wrong: two mempool transactions that both spend
        the same confirmed output, or a signature that doesn't actually
        match the UTXO it claims to spend, would each look fine in
        isolation and only be caught later at full block validation —
        wasting the entire mining effort on a block that's DOA. A
        legitimate *chain* of unconfirmed transactions (tx2 spending
        tx1's own not-yet-confirmed output) is the mirror-image case this
        same local-copy approach gets right instead of wrongly excluding."""
        from .block import build_candidate
        prev_hash = self.tip_hash
        height = self.height() + 1
        bits = self.expected_bits(prev_hash)

        fees = 0
        utxo = dict(self.utxo_set)  # local scratch copy; never mutates self.utxo_set
        included = []
        for tx in mempool_txs:
            if tx.is_coinbase() or not tx.inputs or not tx.verify_signatures():
                continue
            input_sum = 0
            ok = True
            consumed = []
            for txin in tx.inputs:
                key = (txin.prev_txid, txin.prev_index)
                entry = utxo.get(key)
                if entry is None or pubkey_to_address(txin.pubkey) != entry.to_address:
                    ok = False
                    break
                consumed.append(key)
                input_sum += entry.amount
            output_sum = tx.total_output()
            if not ok or output_sum > input_sum:
                continue
            for key in consumed:
                del utxo[key]
            txid = tx.txid()
            for idx, txout in enumerate(tx.outputs):
                utxo[(txid, idx)] = txout
            fees += input_sum - output_sum
            included.append(tx)

        coinbase = Transaction.coinbase(reward_address, subsidy_at(height) + fees, extra_nonce=extra_nonce)
        candidate = build_candidate(prev_hash, bits, [coinbase] + included)
        return mine(candidate, should_abort=should_abort)
