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
from .chain import RETARGET_INTERVAL
from .network import apply_partition_groups, create_network, join_network, start_all, stop_all
from .transaction import build_transaction
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


def section_double_spend_reorg():
    _section("5. Double-spend across a partition -> reorg resolves it (stretch)")
    nodes, premine_wallet = create_network(3, base_port=19200, genesis_bits=DEMO_BITS, log=print)
    start_all(nodes)
    try:
        ok = _wait_until(lambda: all(n.status()["height"] >= 2 for n in nodes), timeout=60,
                          desc="network mines a couple of blocks")
        assert ok, "network failed to get off the ground"
        ok2 = _wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=15,
                           desc="converge before partitioning")
        assert ok2, "network failed to converge before the partition"

        sender = nodes[0]
        assert sender.wallet.address == premine_wallet.address
        # dedicated, never-mining wallets — REVIEW.md's finding #5 is the
        # reason: nodes[1]/nodes[2] are themselves active miners earning
        # their own block rewards the entire time this section runs, so
        # their balance keeps climbing regardless of the double-spend
        # outcome. A merchant wallet that receives *only* the disputed
        # transfer is the only way an exact-equality check here is safe.
        merchant_a, merchant_b = Wallet(), Wallet()
        recipient_a, recipient_b = merchant_a.address, merchant_b.address
        starting_a = sender.chain.balance_of(recipient_a)
        starting_b = sender.chain.balance_of(recipient_b)

        # the exact same UTXO, spent two conflicting ways — a real
        # double-spend attempt, not a simulated one
        utxos = sender.chain.utxos_for(sender.wallet.address)
        tx_a = build_transaction(utxos, sender.wallet.privkey, recipient_a, 1000, 2, sender.wallet.address)
        tx_b = build_transaction(utxos, sender.wallet.privkey, recipient_b, 1000, 2, sender.wallet.address)
        assert tx_a.txid() != tx_b.txid()
        assert {i.prev_txid for i in tx_a.inputs} & {i.prev_txid for i in tx_b.inputs}, \
            "tx_a and tx_b must conflict on at least one input for this to be a real double-spend"

        names = [n.name for n in nodes]
        group_a, group_b = names[:2], names[2:]
        print(f"  partitioning network: {group_a} | {group_b}")
        apply_partition_groups(nodes, [group_a, group_b])

        ok3, err3 = nodes[0].submit_transaction(tx_a)
        assert ok3, f"tx_a rejected: {err3}"
        print(f"  submitted tx_a (-> {recipient_a[:10]}…) into partition {group_a}")
        ok4, err4 = nodes[2].submit_transaction(tx_b)
        assert ok4, f"tx_b rejected: {err4}"
        print(f"  submitted tx_b (-> {recipient_b[:10]}…) into partition {group_b}")

        confirmed_a = _wait_until(lambda: nodes[0].chain.balance_of(recipient_a) >= starting_a + 1000,
                                   timeout=45, desc="tx_a confirms inside its own partition")
        assert confirmed_a, "tx_a never confirmed inside its own partition"
        confirmed_b = _wait_until(lambda: nodes[2].chain.balance_of(recipient_b) >= starting_b + 1000,
                                   timeout=45, desc="tx_b confirms inside its own partition")
        assert confirmed_b, "tx_b never confirmed inside its own partition"
        print("  both partitions independently confirmed their own conflicting spend of the same coins")

        print("  healing the network...")
        apply_partition_groups(nodes, [names])
        converged = _wait_until(lambda: len({n.chain.tip for n in nodes}) == 1, timeout=45,
                                 desc="network reconverges on one winner")
        assert converged, "network never reconverged after healing"
        settled = _wait_until(
            lambda: len({n.chain.balance_of(recipient_a) for n in nodes}) == 1
            and len({n.chain.balance_of(recipient_b) for n in nodes}) == 1,
            timeout=15, desc="every node agrees on both recipients' final balances",
        )
        assert settled, "nodes disagree on the outcome after reconvergence"

        final_a = nodes[0].chain.balance_of(recipient_a)
        final_b = nodes[0].chain.balance_of(recipient_b)
        a_won = final_a >= starting_a + 1000
        b_won = final_b >= starting_b + 1000
        assert a_won != b_won, (
            f"exactly one side of a double-spend must win, got a_won={a_won} b_won={b_won} "
            f"(final_a={final_a}, final_b={final_b})"
        )
        loser_recipient = recipient_b if a_won else recipient_a
        loser_starting = starting_b if a_won else starting_a
        loser_tx = tx_b if a_won else tx_a
        print(f"  reorg resolved the double-spend: {'tx_a' if a_won else 'tx_b'} won; the loser's "
              f"recipient balance reverted to {loser_starting} on every node")
        for n in nodes:
            assert n.chain.balance_of(loser_recipient) == loser_starting, \
                f"{n.name} still shows the losing transfer as applied"
            assert not n.mempool.contains(loser_tx.txid()), \
                f"{n.name} still has the permanently-invalid losing tx sitting in its mempool"
        print("  the losing transaction correctly evaporated — never confirmed, never stuck "
              "pending forever — exactly why a merchant should wait for confirmations")
    finally:
        stop_all(nodes)


def section_difficulty_retarget():
    _section("6. Difficulty retargeting responds to a real hashrate change (stretch)")
    nodes, _ = create_network(1, base_port=19300, genesis_bits=DEMO_BITS, premine=0,
                               retarget_enabled=True, log=print)
    extra = []
    start_all(nodes)
    try:
        ok = _wait_until(lambda: nodes[0].status()["height"] >= RETARGET_INTERVAL, timeout=90,
                          desc=f"solo miner completes the first {RETARGET_INTERVAL}-block retarget window")
        assert ok, "solo miner never completed the first retarget window"
        bits_before = nodes[0].status()["bits"]
        print(f"  after {RETARGET_INTERVAL} blocks with 1 miner: bits={bits_before}")

        print("  adding 3 more mining nodes (~4x the real hash power)...")
        for i in range(1, 4):
            n = join_network(nodes, f"rnode{i}", 19300 + i, wallet=Wallet(), mine=True,
                              retarget_enabled=True, log=print)
            extra.append(n)
            n.start()

        target_height = RETARGET_INTERVAL * 2
        ok2 = _wait_until(lambda: nodes[0].status()["height"] >= target_height, timeout=90,
                           desc="second retarget window completes with more hash power")
        assert ok2, "network never completed the second retarget window"
        bits_after = nodes[0].status()["bits"]
        print(f"  after {RETARGET_INTERVAL} more blocks with 4 miners: bits={bits_after}")
        assert bits_after > bits_before, (
            f"difficulty should have increased once real hash power roughly quadrupled "
            f"(before={bits_before}, after={bits_after})"
        )
        print(f"  difficulty responded correctly: {bits_before} -> {bits_after} bits "
              f"as real mining power increased")
    finally:
        stop_all(nodes + extra)


def run() -> int:
    try:
        section_wallets()
        nodes, premine_wallet = section_mining_and_gossip()
        try:
            section_transactions(nodes, premine_wallet)
            section_fork_resolution(nodes)
        finally:
            stop_all(nodes)
        section_double_spend_reorg()
        section_difficulty_retarget()
    except AssertionError as exc:
        print(f"\nDEMO FAILED: {exc}")
        return 1
    print("\nAll sections passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
