"""End-to-end scripted walkthrough of every LedgerLine feature, run by
`ledgerline demo` and by `demo.sh`. Each section prints what it's doing,
asserts the real outcome (not a mocked one), and the whole thing exits
non-zero the moment anything doesn't hold.
"""
from __future__ import annotations

import hashlib
import sys
import time

from . import ecdsa
from .network import apply_partition_groups, create_network, start_all, stop_all
from .wallet import Wallet

DEMO_BITS = 18  # ~262144 hashes/block average: at ~120k hashes/sec combined
                # (Python's GIL means concurrent miner threads share, not multiply,
                # hash throughput) this paces blocks at roughly one every 1-3s —
                # fast enough for a demo, slow enough that forks are occasional
                # events you can actually observe instead of constant noise.


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _wait_until(predicate, timeout: float, interval: float = 0.2, desc: str = "condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    print(f"  !! timed out waiting for: {desc}")
    return False


def section_wallets() -> None:
    _section("1. ECDSA (secp256k1) wallets — from-scratch key generation, signing, addresses")
    w1, w2 = Wallet(), Wallet()
    assert w1.address != w2.address, "two random wallets collided (impossible unless RNG is broken)"
    assert w1.address.startswith("L"), "address should use our Base58Check version byte"
    print(f"  wallet A: {w1.address}")
    print(f"  wallet B: {w2.address}")

    msg = b"the quick brown fox jumps over the lazy dog"
    digest = hashlib.sha256(msg).digest()
    sig = ecdsa.sign(digest, w1.privkey)
    assert ecdsa.verify(digest, sig, w1.pubkey), "valid signature failed to verify"
    tampered = bytearray(digest)
    tampered[0] ^= 0xFF
    assert not ecdsa.verify(bytes(tampered), sig, w1.pubkey), "tampered message incorrectly verified"
    forged = ecdsa.sign(digest, w2.privkey)
    assert not ecdsa.verify(digest, forged, w1.pubkey), "wrong-key signature incorrectly verified against w1"
    print("  signature verifies; tamper detection and cross-key forgery rejection both hold")


def section_mining_and_gossip():
    _section("2. Proof-of-work mining + P2P gossip across a real multi-node network")
    nodes, premine_wallet = create_network(3, base_port=19100, genesis_bits=DEMO_BITS, log=print)
    start_all(nodes)
    try:
        ok = _wait_until(lambda: all(n.status()["height"] >= 3 for n in nodes), timeout=60,
                          desc="all 3 nodes reach height >= 3")
        assert ok, "network failed to mine and propagate 3 blocks"
        tips = {n.chain.tip for n in nodes}
        ok2 = _wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=15,
                           desc="all nodes converge on one tip")
        assert ok2, f"nodes did not converge on a single chain tip: {tips}"
        heights = [n.status()["height"] for n in nodes]
        print(f"  converged at height {heights[0]} across {len(nodes)} nodes: heights={heights}")
        # one snapshot, not a loop re-reading `nodes[0].chain.tip` fresh on
        # every comparison — mining never pauses, so re-reading it each
        # iteration could compare against a tip that already moved on.
        tips_snapshot = {n.name: n.chain.tip for n in nodes}
        reference = tips_snapshot[nodes[0].name]
        assert all(t == reference for t in tips_snapshot.values()), \
            f"post-convergence tip mismatch: {tips_snapshot}"
        print("  every node agrees on the same tip hash")
        return nodes, premine_wallet
    except AssertionError:
        stop_all(nodes)
        raise


def section_transactions(nodes, premine_wallet):
    _section("3. UTXO transactions + mempool (fee-prioritized) confirmed into a block")
    sender_node = nodes[0]
    receiver = nodes[1].wallet.address
    assert sender_node.wallet.address == premine_wallet.address
    starting_balance = sender_node.chain.balance_of(receiver)

    tx = sender_node.wallet.create_transaction(
        sender_node.chain, receiver, amount=250, fee=2, mempool=sender_node.mempool
    )
    ok, err = sender_node.submit_transaction(tx)
    assert ok, f"transaction rejected: {err}"

    def _tx_known(n) -> bool:
        # PoW timing is inherently random — a node can mine (and thus
        # confirm-and-drop-from-mempool) this tx before our poll ever
        # catches it sitting unconfirmed. "Known" means either: still
        # pending in the mempool, or already confirmed into that node's
        # chain — both prove the gossip reached it.
        return n.mempool.contains(tx.txid()) or n.chain.balance_of(receiver) >= starting_balance + 250

    seen = _wait_until(lambda: all(_tx_known(n) for n in nodes), timeout=15,
                        desc="tx reaches (mempool or confirmed on) every node")
    assert seen, "transaction did not propagate to all peers at all"
    print(f"  tx {tx.txid()[:12]}… reached every node (mempool or already confirmed)")

    # `receiver` (nodes[1]) is itself an active miner, earning its own
    # block rewards to its own address the whole time this section runs —
    # so its balance keeps climbing on its own, independent of our tx. An
    # exact "==" check here is a real bug, not just overcautious: the
    # instant our tx confirms, the balance may already have moved past
    # `starting_balance + 250` (another reward landed in the same window),
    # permanently missing an equality check and hanging forever even
    # though the transfer genuinely succeeded. ">=" is the only check that
    # can't be invalidated by the receiver's own concurrent income.
    mined = _wait_until(
        lambda: all(not n.mempool.contains(tx.txid()) and n.chain.balance_of(receiver) >= starting_balance + 250
                    for n in nodes),
        timeout=60, desc="tx gets mined and every node's balance view catches up",
    )
    assert mined, "transaction never got mined into a block"
    print(f"  transaction mined; every node confirms receiver balance is at least "
          f"{starting_balance + 250} (now {nodes[1].chain.balance_of(receiver)}, "
          f"node1 kept earning its own mining rewards meanwhile)")


def section_fork_resolution(nodes):
    _section("4. Network partition -> independent forks -> reconnect -> reorg to one chain")
    names = [n.name for n in nodes]
    group_a, group_b = [names[0]], names[1:]
    print(f"  partitioning network: {group_a} | {group_b}")
    apply_partition_groups(nodes, [group_a, group_b])

    a_start = nodes[0].status()["height"]
    b_start = nodes[1].status()["height"]
    grew = _wait_until(
        lambda: nodes[0].status()["height"] > a_start and nodes[1].status()["height"] > b_start,
        timeout=60, desc="both partitions mine at least one block independently",
    )
    assert grew, "partitions failed to mine independently"
    diverged = nodes[0].chain.tip != nodes[1].chain.tip
    assert diverged, "chains should have diverged during the partition"
    print(f"  partition A at height {nodes[0].status()['height']} (tip {nodes[0].chain.tip[:10]}…)")
    print(f"  partition B at height {nodes[1].status()['height']} (tip {nodes[1].chain.tip[:10]}…)")

    print("  healing the network...")
    apply_partition_groups(nodes, [names])
    converged = _wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=45,
                             desc="all nodes reconverge after reconnecting")
    assert converged, "network failed to reconverge after the partition healed"
    # mining never stops, so the tip can keep moving even after
    # `converged` was momentarily true — snapshot-then-assert here would
    # be racy the same way the balance check above was. Give it a short
    # window to settle on one agreed tip and re-check from there instead
    # of trusting a single instant.
    agreed = _wait_until(
        lambda: len({n.chain.tip for n in nodes}) == 1
        and len({n.chain.cum_work[n.chain.tip] for n in nodes}) == 1,
        timeout=10, desc="all nodes settle on one tip with matching cumulative work",
    )
    assert agreed, "nodes never stabilized on a single agreed tip"
    winner = nodes[0].chain.tip
    for n in nodes:
        assert n.chain.tip == winner, f"{n.name} did not adopt the winning chain"
    print(f"  reconverged on the highest-cumulative-work chain (tip {winner[:10]}…); "
          f"a real reorg happened on whichever side lost")


def run() -> int:
    try:
        section_wallets()
        nodes, premine_wallet = section_mining_and_gossip()
        try:
            section_transactions(nodes, premine_wallet)
            section_fork_resolution(nodes)
        finally:
            stop_all(nodes)
    except AssertionError as exc:
        print(f"\nDEMO FAILED: {exc}")
        return 1
    print("\nAll sections passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
