"""The blockchain itself: a multi-branch block index, the UTXO ledger,
full block/transaction validation, and fork-choice-by-cumulative-work
(re)organization.
"""

import time
from dataclasses import dataclass, field

from bedrock import pow as bpow
from bedrock.block import Block, BlockHeader, GENESIS_PREV_HASH
from bedrock.transaction import Transaction, TxOutput

COIN = 100_000_000
INITIAL_SUBSIDY = 50 * COIN
HALVING_INTERVAL = 50          # blocks; demo-scale, not Bitcoin's 210,000
MAX_FUTURE_DRIFT = 15 * 60      # seconds a block timestamp may be ahead of "now"
GENESIS_TIMESTAMP = 1_700_000_000
GENESIS_MESSAGE = b"Bedrock genesis 2026-08-04 - a from-scratch PoW chain"


class ChainError(ValueError):
    """A block or transaction failed a consensus rule."""


def block_subsidy(height: int) -> int:
    halvings = height // HALVING_INTERVAL
    if halvings >= 64:
        return 0
    return INITIAL_SUBSIDY >> halvings


def create_genesis_block() -> Block:
    """Fully deterministic: same content every time, so every independently
    started node mines/derives the identical genesis block and hash."""
    coinbase = Transaction.new_coinbase(
        # Not derived from any known keypair: spending it would require
        # finding a private key whose address happens to base58check-decode
        # to this exact literal, i.e. a hash preimage. Practically unspendable.
        reward_address="1111111111111111111111111",
        value=INITIAL_SUBSIDY,
        height=0,
        extra=GENESIS_MESSAGE,
    )
    header = BlockHeader(
        version=1,
        prev_hash=GENESIS_PREV_HASH,
        merkle_root="0" * 64,
        timestamp=GENESIS_TIMESTAMP,
        target=bpow.INITIAL_TARGET,
        nonce=0,
    )
    block = Block(header, [coinbase])
    header.merkle_root = block.compute_merkle_root()
    bpow.mine(header)
    return block


class UTXOSet:
    def __init__(self):
        self._utxos = {}          # (txid, index) -> TxOutput
        self._by_address = {}     # address -> set of (txid, index)

    def copy(self) -> "UTXOSet":
        clone = UTXOSet()
        clone._utxos = dict(self._utxos)
        clone._by_address = {addr: set(keys) for addr, keys in self._by_address.items()}
        return clone

    def add(self, txid: str, index: int, output: TxOutput) -> None:
        key = (txid, index)
        self._utxos[key] = output
        self._by_address.setdefault(output.address, set()).add(key)

    def remove(self, txid: str, index: int) -> None:
        key = (txid, index)
        output = self._utxos.pop(key, None)
        if output is not None:
            addr_set = self._by_address.get(output.address)
            if addr_set is not None:
                addr_set.discard(key)
                if not addr_set:
                    del self._by_address[output.address]

    def get(self, txid: str, index: int):
        return self._utxos.get((txid, index))

    def utxos_for_address(self, address: str):
        return [(key, self._utxos[key]) for key in self._by_address.get(address, ())]

    def balance(self, address: str) -> int:
        return sum(o.value for _, o in self.utxos_for_address(address))

    def __len__(self):
        return len(self._utxos)


@dataclass
class BlockIndexEntry:
    block: Block
    height: int
    cumulative_work: int


class Chain:
    def __init__(self, genesis_block: Block = None):
        self.blocks_by_hash = {}
        self.orphans = {}          # missing_parent_hash -> [Block, ...]
        self.tip_hash = None
        self.utxo_set = UTXOSet()
        self.height_index = {}     # height (best chain only) -> hash
        genesis_block = genesis_block or create_genesis_block()
        self._accept_genesis(genesis_block)

    # -- basic queries ----------------------------------------------------

    @property
    def height(self) -> int:
        return self.blocks_by_hash[self.tip_hash].height

    @property
    def tip(self) -> Block:
        return self.blocks_by_hash[self.tip_hash].block

    def get_block(self, block_hash: str) -> Block:
        entry = self.blocks_by_hash.get(block_hash)
        return entry.block if entry else None

    def get_entry(self, block_hash: str) -> BlockIndexEntry:
        return self.blocks_by_hash.get(block_hash)

    def block_at_height(self, height: int) -> Block:
        h = self.height_index.get(height)
        return self.blocks_by_hash[h].block if h is not None else None

    def cumulative_work(self, block_hash: str = None) -> int:
        h = block_hash or self.tip_hash
        return self.blocks_by_hash[h].cumulative_work

    # -- genesis ------------------------------------------------------------

    def _accept_genesis(self, block: Block) -> None:
        if not bpow.meets_target(block.hash, block.header.target):
            raise ChainError("genesis block does not satisfy its own PoW target")
        entry = BlockIndexEntry(block, height=0, cumulative_work=bpow.work_for_target(block.header.target))
        self.blocks_by_hash[block.hash] = entry
        utxo = UTXOSet()
        self._apply_block_transactions(block, 0, utxo)
        self.utxo_set = utxo
        self.height_index = {0: block.hash}
        self.tip_hash = block.hash

    # -- adding blocks --------------------------------------------------------

    def add_block(self, block: Block) -> str:
        """Returns one of "duplicate", "orphan", "side_chain", "best_chain".
        Raises ChainError for a structurally/consensus-invalid block whose
        parent IS known (an orphan's validity can't be checked yet, so it is
        simply queued, not rejected)."""
        h = block.hash
        if h in self.blocks_by_hash:
            return "duplicate"

        prev_hash = block.header.prev_hash
        if prev_hash not in self.blocks_by_hash:
            self.orphans.setdefault(prev_hash, []).append(block)
            return "orphan"

        parent_entry = self.blocks_by_hash[prev_hash]
        height = parent_entry.height + 1
        self._validate_block_structure(block, height, parent_entry)

        work = bpow.work_for_target(block.header.target)
        cumulative_work = parent_entry.cumulative_work + work
        self.blocks_by_hash[h] = BlockIndexEntry(block, height, cumulative_work)

        result = "side_chain"
        if cumulative_work > self.blocks_by_hash[self.tip_hash].cumulative_work:
            self._reorganize_to(h)
            result = "best_chain"

        self._process_orphans(h)
        return result

    def _process_orphans(self, parent_hash: str) -> None:
        pending = self.orphans.pop(parent_hash, [])
        for orphan in pending:
            try:
                self.add_block(orphan)
            except ChainError:
                pass  # an invalid orphan just never gets connected

    # -- structural validation (doesn't require a full UTXO replay) ---------

    def _ancestor_header(self, entry: BlockIndexEntry, height: int) -> BlockHeader:
        cur = entry
        while cur.height > height:
            cur = self.blocks_by_hash[cur.block.header.prev_hash]
        return cur.block.header

    def _validate_block_structure(self, block: Block, height: int, parent_entry: BlockIndexEntry) -> None:
        header = block.header
        if header.prev_hash != parent_entry.block.hash:
            raise ChainError("prev_hash does not match parent")

        expected_target = bpow.target_for_height(
            lambda h: self._ancestor_header(parent_entry, h),
            height,
            parent_entry.block.header.target,
        )
        if header.target != expected_target:
            raise ChainError(f"wrong difficulty target: got {header.target}, expected {expected_target}")
        if not bpow.meets_target(block.hash, header.target):
            raise ChainError("block hash does not satisfy its target (invalid proof-of-work)")

        if header.timestamp <= parent_entry.block.header.timestamp:
            raise ChainError("block timestamp must be strictly greater than its parent's")
        if header.timestamp > time.time() + MAX_FUTURE_DRIFT:
            raise ChainError("block timestamp too far in the future")

        if not block.transactions:
            raise ChainError("block must contain at least a coinbase transaction")
        if not block.transactions[0].is_coinbase:
            raise ChainError("first transaction must be coinbase")
        for tx in block.transactions[1:]:
            if tx.is_coinbase:
                raise ChainError("only the first transaction may be coinbase")

        if header.merkle_root != block.compute_merkle_root():
            raise ChainError("merkle root does not match transactions")

        txids = [tx.txid for tx in block.transactions]
        if len(txids) != len(set(txids)):
            raise ChainError("duplicate transaction id within block")

    # -- transaction / UTXO application --------------------------------------

    def apply_transaction(self, tx: Transaction, utxo_set: UTXOSet) -> int:
        """Validates `tx` against `utxo_set` and, only if fully valid,
        mutates `utxo_set` to reflect it. Returns the fee. Raises ChainError
        on any violation, leaving `utxo_set` untouched."""
        if tx.is_coinbase:
            raise ChainError("apply_transaction does not handle coinbase transactions")
        if not tx.inputs:
            raise ChainError("non-coinbase transaction must have at least one input")

        seen_keys = set()
        prevouts = []
        input_sum = 0
        for idx, tx_in in enumerate(tx.inputs):
            key = (tx_in.prev_txid, tx_in.prev_index)
            if key in seen_keys:
                raise ChainError("double-spend: same utxo referenced twice in one transaction")
            seen_keys.add(key)
            prevout = utxo_set.get(*key)
            if prevout is None:
                raise ChainError(f"input references an unknown or already-spent utxo {key}")
            try:
                owner = tx.input_owner_address(idx)
            except Exception as exc:
                raise ChainError(f"malformed input pubkey: {exc}") from exc
            if owner != prevout.address:
                raise ChainError("input pubkey does not match the address that owns this utxo")
            if not tx.verify_input_signature(idx):
                raise ChainError("invalid input signature")
            prevouts.append(key)
            input_sum += prevout.value

        if any(o.value <= 0 for o in tx.outputs):
            raise ChainError("output value must be positive")
        output_sum = tx.total_output_value()
        if output_sum > input_sum:
            raise ChainError("transaction outputs exceed inputs")

        for key in prevouts:
            utxo_set.remove(*key)
        for i, out in enumerate(tx.outputs):
            utxo_set.add(tx.txid, i, out)
        return input_sum - output_sum

    def _apply_block_transactions(self, block: Block, height: int, utxo_set: UTXOSet) -> None:
        coinbase = block.transactions[0]
        total_fees = 0
        for tx in block.transactions[1:]:
            total_fees += self.apply_transaction(tx, utxo_set)

        expected_reward = block_subsidy(height) + total_fees
        actual_reward = coinbase.total_output_value()
        if actual_reward != expected_reward:
            raise ChainError(
                f"coinbase reward mismatch at height {height}: "
                f"got {actual_reward}, expected {expected_reward}"
            )
        for i, out in enumerate(coinbase.outputs):
            utxo_set.add(coinbase.txid, i, out)

    # -- reorg ----------------------------------------------------------------

    def path_from_genesis(self, tip_hash: str) -> list:
        path = []
        cur_hash = tip_hash
        while True:
            path.append(cur_hash)
            entry = self.blocks_by_hash[cur_hash]
            if entry.block.header.prev_hash == GENESIS_PREV_HASH:
                break
            cur_hash = entry.block.header.prev_hash
        path.reverse()
        return path

    def _reorganize_to(self, new_tip_hash: str) -> None:
        path = self.path_from_genesis(new_tip_hash)
        new_utxo = UTXOSet()
        new_height_index = {}
        for block_hash in path:
            entry = self.blocks_by_hash[block_hash]
            self._apply_block_transactions(entry.block, entry.height, new_utxo)
            new_height_index[entry.height] = block_hash
        # only commit once the *entire* candidate chain has validated
        self.utxo_set = new_utxo
        self.height_index = new_height_index
        self.tip_hash = new_tip_hash

    # -- mining support ---------------------------------------------------

    def next_target(self) -> int:
        tip_entry = self.blocks_by_hash[self.tip_hash]
        return bpow.target_for_height(
            lambda h: self._ancestor_header(tip_entry, h),
            self.height + 1,
            tip_entry.block.header.target,
        )

    def build_candidate_header(self, merkle_root_hex: str, timestamp: int = None) -> BlockHeader:
        return BlockHeader(
            version=1,
            prev_hash=self.tip_hash,
            merkle_root=merkle_root_hex,
            timestamp=timestamp if timestamp is not None else int(time.time()),
            target=self.next_target(),
            nonce=0,
        )
