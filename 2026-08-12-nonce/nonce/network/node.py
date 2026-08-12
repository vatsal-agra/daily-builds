"""A full P2P node: its own chain, its own mempool, its own validation —
nothing about correctness here trusts any other node. Consensus is an
*emergent* property of every node independently applying the same rules,
not a shared oracle deciding what's valid.
"""

from ..core.transaction import Transaction, pubkey_to_address
from ..core.block import Block


class Node:
    def __init__(self, node_id, blockchain, bus, wallet=None):
        self.id = node_id
        self.chain = blockchain
        self.bus = bus
        self.wallet = wallet
        self.mempool = {}          # txid -> Transaction
        self._mempool_spends = {}  # (prev_txid, prev_index) -> txid, to catch mempool-internal double spends
        self.seen_tx = set()
        self.seen_block = set()
        self.log = []
        self._extra_nonce = 0
        bus.register(self)

    def _note(self, message: str):
        self.log.append(message)

    # ------------------------------------------------------------------
    # transactions

    def submit_transaction(self, tx: Transaction):
        """Entry point for a transaction originating locally (e.g. built
        by this node's own wallet), as opposed to one arriving from a peer."""
        self._process_tx(tx, from_peer=None)

    def _validate_mempool_tx(self, tx: Transaction):
        if tx.is_coinbase():
            return False, "coinbase transactions don't belong in the mempool"
        if not tx.inputs:
            return False, "transaction has no inputs"
        if not tx.verify_signatures():
            return False, "invalid signature"
        utxo = self.chain.utxo_set
        input_sum = 0
        for txin in tx.inputs:
            key = (txin.prev_txid, txin.prev_index)
            if key in self._mempool_spends:
                return False, "conflicts with a transaction already in the mempool"
            entry = utxo.get(key)
            if entry is None:
                return False, "spends an unknown or already-spent output"
            if pubkey_to_address(txin.pubkey) != entry.to_address:
                return False, "signature does not match the UTXO owner"
            input_sum += entry.amount
        if tx.total_output() > input_sum:
            return False, "outputs exceed inputs"
        return True, None

    def _process_tx(self, tx: Transaction, from_peer):
        txid = tx.txid()
        if txid in self.seen_tx:
            return
        self.seen_tx.add(txid)

        ok, reason = self._validate_mempool_tx(tx)
        if not ok:
            self._note(f"rejected tx {txid.hex()[:8]} ({'wallet' if from_peer is None else from_peer}): {reason}")
            return

        self.mempool[txid] = tx
        for txin in tx.inputs:
            self._mempool_spends[(txin.prev_txid, txin.prev_index)] = txid
        self._note(f"mempool += tx {txid.hex()[:8]} (from {'own wallet' if from_peer is None else from_peer})")
        self.bus.broadcast(self.id, "tx", tx.to_dict())

    def _drop_from_mempool(self, txid):
        tx = self.mempool.pop(txid, None)
        if tx is None:
            return
        for txin in tx.inputs:
            key = (txin.prev_txid, txin.prev_index)
            if self._mempool_spends.get(key) == txid:
                del self._mempool_spends[key]

    # ------------------------------------------------------------------
    # blocks / mining

    def mine_block(self, max_txs=50, should_abort=None):
        if self.wallet is None:
            raise ValueError(f"node {self.id} has no wallet to receive the mining reward")
        txs = list(self.mempool.values())[:max_txs]
        self._extra_nonce += 1
        block = self.chain.mine_new_block(txs, self.wallet.address,
                                           extra_nonce=self._extra_nonce, should_abort=should_abort)
        self._process_block(block, from_peer=None)
        return block

    def _process_block(self, block: Block, from_peer):
        h = block.hash()
        if h in self.seen_block:
            return
        self.seen_block.add(h)

        result = self.chain.add_block(block)

        if result.status in ("new_tip", "side_branch"):
            kind = "new tip" if result.status == "new_tip" else "side branch"
            self._note(f"block {h.hex()[:8]} (height {block.height}) accepted as {kind}"
                       f"{' [from ' + from_peer + ']' if from_peer else ' [mined locally]'}")
            self._reconcile_mempool(result)
            self.bus.broadcast(self.id, "block", block.to_dict())
            for sub_result in result.resolved_orphans:
                if sub_result.status in ("new_tip", "side_branch"):
                    self._reconcile_mempool(sub_result)
        elif result.status == "orphan":
            self._note(f"buffered block {h.hex()[:8]} as an orphan ({result.reason})")
        elif result.status == "invalid":
            self._note(f"REJECTED invalid block {h.hex()[:8]} from {from_peer}: {result.reason}")
        # duplicate: silently ignored, already seen

    def _reconcile_mempool(self, result):
        if result.status != "new_tip":
            return  # side branches don't touch the active mempool
        block = self.chain.blocks[result.block_hash]
        for tx in block.transactions:
            if not tx.is_coinbase():
                self._drop_from_mempool(tx.txid())

        if result.reorg is not None:
            reconnected_ids = {tx.txid() for b in result.reorg.connected
                                for tx in b.transactions if not tx.is_coinbase()}
            for b in result.reorg.disconnected:
                for tx in b.transactions:
                    if tx.is_coinbase():
                        continue
                    txid = tx.txid()
                    if txid in reconnected_ids:
                        continue  # this tx made it into the winning fork too
                    ok, _reason = self._validate_mempool_tx(tx)
                    if ok:
                        self.mempool[txid] = tx
                        for txin in tx.inputs:
                            self._mempool_spends[(txin.prev_txid, txin.prev_index)] = txid
                        self._note(f"reorg restored tx {txid.hex()[:8]} to mempool")

    def request_sync(self, peer_id):
        """Pull-based resync with one peer: ask for its chain and feed in
        anything this node is missing. Real nodes negotiate this with
        INV/GETHEADERS/GETDATA message round trips; this simulation
        collapses that to a direct read of the peer's block store, but the
        receiving side still runs every block through the exact same
        independent `_process_block` validation as gossip traffic — nothing
        is trusted just because it came from a "resync". This is what lets
        two nodes reconverge after a network partition heals, since gossip
        messages broadcast *during* a partition are simply dropped, not
        queued for later delivery."""
        peer = self.bus.nodes[peer_id]
        for h in peer.chain.chain_to_genesis(peer.chain.tip_hash):
            if h not in self.chain.blocks:
                self._process_block(peer.chain.blocks[h], from_peer=f"sync:{peer_id}")

    # ------------------------------------------------------------------
    # wire protocol

    def handle_message(self, sender_id, msg_type: str, payload):
        if msg_type == "tx":
            self._process_tx(Transaction.from_dict(payload), from_peer=sender_id)
        elif msg_type == "block":
            self._process_block(Block.from_dict(payload), from_peer=sender_id)
        else:
            raise ValueError(f"unknown message type {msg_type!r}")
