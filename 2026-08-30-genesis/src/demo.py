"""A full, narrated, end-to-end demonstration of every feature.

Run via `python3 cli.py demo` (from the project root) or directly as
`python3 src/demo.py`. Exercises, in order: mining + difficulty
retargeting (both directions), a real signed spend, a rejected double-
spend, a rejected wrong-key signature, a Merkle inclusion proof (and a
forged one failing), a multi-node network reaching consensus, a genuine
fork + reorg with byte-identical UTXO state across nodes afterward, and
the wallet CLI's own persistence layer. Exits non-zero (and prints which
step failed) if any assertion fails, so it doubles as Phase 5's
verification script.
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import block as blk
import blockchain as bc
import crypto as c
import merkle as mk
import transaction as tx
from mempool import Mempool
from network import SimNetwork
from node import Node
from wallet import InsufficientFunds, Wallet

PASS = "\033[92mPASS\033[0m" if sys.stdout.isatty() else "PASS"
FAIL = "\033[91mFAIL\033[0m" if sys.stdout.isatty() else "FAIL"
_step_count = 0
_fail_count = 0


def step(name: str) -> None:
    global _step_count
    _step_count += 1
    print(f"\n=== [{_step_count}] {name} " + "=" * max(1, 60 - len(name)))


def check(condition: bool, description: str) -> None:
    global _fail_count
    if condition:
        print(f"  {PASS}  {description}")
    else:
        _fail_count += 1
        print(f"  {FAIL}  {description}")


def make_genesis(ts=1_700_000_000, target=None):
    burn = b"\x00" * 20
    cb = tx.Transaction.coinbase(burn, reward=bc.subsidy_at(0), height=0)
    g = blk.Block.new(prev_hash=b"\x00" * 32, transactions=[cb],
                       target=target or bc.GENESIS_TARGET_DEFAULT, timestamp=ts)
    g.mine()
    return g


def mine_next(chain, prev, txs, ts, target=None):
    t = target if target is not None else chain._expected_target(prev)
    b = blk.Block.new(prev_hash=prev, transactions=txs, target=t, timestamp=ts)
    b.mine()
    return b


def demo_mining_and_difficulty():
    step("Mining + difficulty retargeting")
    genesis = make_genesis()
    chain = bc.Blockchain(genesis)
    miner = Wallet()
    prev = chain.genesis_hash
    ts = 1_700_000_000
    targets = [chain.blocks[prev].header.target]
    for i in range(1, 11):
        ts += 1  # far faster than TARGET_BLOCK_TIME=2s
        cb = tx.Transaction.coinbase(miner.pubkey_hash, bc.subsidy_at(i), i)
        b = mine_next(chain, prev, [cb], ts)
        res = chain.accept_block(b)
        check(res.accepted, f"block {i} accepted (reason: {res.reason})")
        targets.append(b.header.target)
        prev = b.block_hash()
    print(f"  target before window: {targets[0]:#x}")
    print(f"  target after 10 fast blocks: {targets[10]:#x}")
    check(targets[10] < targets[0], "fast blocks made the next difficulty HARDER (lower target)")

    # now go slow for a window and confirm it eases back off
    genesis2 = make_genesis()
    chain2 = bc.Blockchain(genesis2)
    prev2 = chain2.genesis_hash
    ts2 = 1_700_000_000
    for i in range(1, 11):
        ts2 += 100  # far slower than TARGET_BLOCK_TIME
        cb = tx.Transaction.coinbase(miner.pubkey_hash, bc.subsidy_at(i), i)
        b = mine_next(chain2, prev2, [cb], ts2)
        chain2.accept_block(b)
        prev2 = b.block_hash()
    target_after_slow = chain2.blocks[prev2].header.target
    print(f"  target after 10 slow blocks: {target_after_slow:#x}")
    check(target_after_slow > targets[0], "slow blocks made the next difficulty EASIER (higher target)")
    return chain, miner


def demo_spend_and_double_spend(chain, alice):
    step("UTXO ledger + from-scratch secp256k1 ECDSA authorization")
    bob = Wallet()
    mallory = Wallet()
    prev = chain.tip
    ts = chain.blocks[prev].header.timestamp + 1
    height = chain.height() + 1
    cb = tx.Transaction.coinbase(alice.pubkey_hash, bc.subsidy_at(height), height)
    b = mine_next(chain, prev, [cb], ts)
    chain.accept_block(b)
    alice_outpoint = (cb.txid(), 0)
    alice_amount = cb.total_output()
    print(f"  alice mined a block, earned {alice_amount/1e8:.2f} coins")

    # wrong-key signature attempt -- tested against the still-unspent output,
    # so a "missing output" rejection can't masquerade as a signature check
    forged = tx.Transaction(
        inputs=[tx.TxIn(alice_outpoint[0], 0, alice.keypair.pubkey_bytes())],
        outputs=[tx.TxOut(1, mallory.pubkey_hash)],
    )
    forged.sign_input(0, mallory.keypair.private_key)  # mallory signs, claiming alice's pubkey
    ok, reason = forged.verify(lambda txid, idx: chain.utxo_set().get((txid, idx)))
    check(not ok and "signature" in reason,
          f"mallory forging a spend of alice's still-unspent output with her own key is rejected ({reason})")

    spend = tx.Transaction(
        inputs=[tx.TxIn(alice_outpoint[0], 0, alice.keypair.pubkey_bytes())],
        outputs=[tx.TxOut(10_00000000, bob.pubkey_hash),
                 tx.TxOut(alice_amount - 10_00000000 - 1000, alice.pubkey_hash)],
    )
    spend.sign_input(0, alice.keypair.private_key)
    height2 = chain.height() + 1
    cb2 = tx.Transaction.coinbase(alice.pubkey_hash, bc.subsidy_at(height2) + 1000, height2)
    ts = chain.blocks[chain.tip].header.timestamp + 1
    b2 = mine_next(chain, chain.tip, [cb2, spend], ts)
    res = chain.accept_block(b2)
    check(res.accepted, f"real signed spend (alice -> bob, 10 coins) confirmed: {res.reason}")
    check(bob.balance(chain.utxo_set()) == 10_00000000, "bob's balance reflects the spend")

    # double-spend: try to spend the SAME already-confirmed output again
    respend = tx.Transaction(
        inputs=[tx.TxIn(alice_outpoint[0], 0, alice.keypair.pubkey_bytes())],
        outputs=[tx.TxOut(1, mallory.pubkey_hash)],
    )
    respend.sign_input(0, alice.keypair.private_key)  # validly signed by alice...
    height3 = chain.height() + 1
    cb3 = tx.Transaction.coinbase(alice.pubkey_hash, bc.subsidy_at(height3), height3)
    ts = chain.blocks[chain.tip].header.timestamp + 1
    b3 = mine_next(chain, chain.tip, [cb3, respend], ts)
    res3 = chain.accept_block(b3)
    check(not res3.accepted, f"...but re-spending an already-spent output is rejected ({res3.reason})")
    return chain, alice, bob


def demo_merkle_proofs(chain):
    step("Merkle tree commitment + inclusion proofs")
    tip_block = chain.tip_block()
    leaves = [t.txid() for t in tip_block.transactions]
    for i, t in enumerate(tip_block.transactions):
        proof = mk.build_proof(leaves, i)
        ok = proof.verify(tip_block.header.merkle_root)
        check(ok, f"tx {i} ({t.txid_hex()[:12]}...) merkle proof verifies against the block's real root")
    forged_proof = mk.build_proof(leaves, 0)
    forged_proof.leaf = c.hash256(b"forged transaction")
    check(not forged_proof.verify(tip_block.header.merkle_root), "a forged leaf's proof correctly fails")


def demo_network_consensus_and_reorg():
    step("Multi-node P2P consensus: independent mining, gossip, fork + reorg")
    genesis = make_genesis()
    net = SimNetwork(seed=42, latency_range=(0.01, 0.2))
    names = ["Node-A", "Node-B", "Node-C"]
    nodes = {n: Node(n, bc.Blockchain(genesis), net, Wallet()) for n in names}
    rng = random.Random(7)
    ts = 1_700_000_000
    for _ in range(80):
        ts += 1
        order = list(names)
        rng.shuffle(order)
        for n in order:
            nodes[n].attempt_mine(300, ts)
        net.advance_to(ts)
    net.drain()

    extra = 0
    while len({nodes[n].chain.tip for n in names}) != 1 and extra < 400:
        ts += 1
        order = list(names)
        rng.shuffle(order)
        for n in order:
            nodes[n].attempt_mine(300, ts)
        net.advance_to(ts)
        extra += 1
    net.drain()

    tips = {n: nodes[n].chain.tip.hex()[:12] for n in names}
    print(f"  final tips: {tips}")
    check(len(set(tips.values())) == 1, "all 3 independently-mining nodes converged on one chain")

    total_mined = sum(nodes[n].stats.blocks_mined for n in names)
    total_reorgs = sum(nodes[n].stats.reorgs_seen for n in names)
    height = nodes[names[0]].chain.height()
    print(f"  height {height}, {total_mined} blocks mined in total across all nodes, {total_reorgs} reorg(s) observed")
    check(total_mined > height, "more blocks were mined than made it into the final chain (a real fork happened)")

    snapshots = set()
    for n in names:
        u = nodes[n].chain.utxo_set()
        key = tuple(sorted((k, v.amount, v.pubkey_hash) for k, v in u.items()))
        snapshots.add(key)
    check(len(snapshots) == 1, "every node's UTXO set is byte-identical after convergence")


def demo_wallet_cli():
    step("Wallet CLI persistence (isolated temp data dir)")
    tmp = tempfile.mkdtemp(prefix="genesis-demo-")
    try:
        import persistence as ps
        chain = ps.load_or_init_chain(tmp)
        alice = ps.load_or_init_wallet(tmp)
        check(chain.height() == 0, "fresh data dir starts at height 0")
        check(alice.address.startswith("1"), f"wallet address derived: {alice.address}")

        # a second load must reconstruct the exact same wallet (persistence roundtrip)
        alice2 = ps.load_or_init_wallet(tmp)
        check(alice.address == alice2.address, "reloading the wallet gives back the same address/key")

        # mine a block via the persisted chain file, reload, and confirm balance survives
        from block import Block
        height = 1
        cb = tx.Transaction.coinbase(alice.pubkey_hash, bc.subsidy_at(height), height)
        b = Block.new(prev_hash=chain.genesis_hash, transactions=[cb], target=chain.next_expected_target(),
                       timestamp=ps.FIXED_GENESIS_TIMESTAMP + 1)
        b.mine()
        res = chain.accept_block(b)
        check(res.accepted, "mined block accepted onto the persisted chain")
        ps.append_block(tmp, b)

        chain_reloaded = ps.load_or_init_chain(tmp)
        check(chain_reloaded.height() == 1, "reloading the chain file replays the appended block")
        check(alice.balance(chain_reloaded.utxo_set()) == bc.subsidy_at(1),
              "reloaded chain shows the correct mined balance")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run() -> int:
    print("Genesis -- end-to-end demonstration")
    print("=" * 70)
    chain, alice = demo_mining_and_difficulty()
    chain, alice, bob = demo_spend_and_double_spend(chain, alice)
    demo_merkle_proofs(chain)
    demo_network_consensus_and_reorg()
    demo_wallet_cli()

    print("\n" + "=" * 70)
    if _fail_count == 0:
        print(f"ALL {_step_count} DEMONSTRATION SECTIONS PASSED")
        return 0
    else:
        print(f"{_fail_count} CHECK(S) FAILED across {_step_count} sections")
        return 1


if __name__ == "__main__":
    sys.exit(run())
