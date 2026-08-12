"""The scripted end-to-end scenario exercising every required feature in
one run: proof-of-work mining, signed UTXO transactions, merkle-committed
blocks, and a multi-node network reaching consensus through a fork,
double-spend attempt, and tamper attempt. Used by both `nonce demo` and
the test suite (so the test suite is asserting on the exact same run a
human sees, not a separate toy path).
"""

import copy

from .wallet import Wallet
from .core.blockchain import Blockchain, create_genesis, subsidy_at
from .core.transaction import Transaction, TxIn, TxOut
from .core.difficulty import bits_to_target, RETARGET_INTERVAL
from .network.bus import Bus
from .network.node import Node


def _p(verbose, *args):
    if verbose:
        print(*args)


def run_demo(verbose=False, seed=1):
    stats = {}

    alice, bob, carol = Wallet(), Wallet(), Wallet()
    _p(verbose, "=== Wallets ===")
    _p(verbose, f"alice: {alice.address}")
    _p(verbose, f"bob:   {bob.address}")
    _p(verbose, f"carol: {carol.address}")

    genesis = create_genesis(alice.address)
    bus = Bus(seed=seed)
    nodes = {
        "N1": Node("N1", Blockchain(copy.deepcopy(genesis)), bus, wallet=alice),
        "N2": Node("N2", Blockchain(copy.deepcopy(genesis)), bus, wallet=bob),
        "N3": Node("N3", Blockchain(copy.deepcopy(genesis)), bus, wallet=carol),
    }
    n1, n2, n3 = nodes["N1"], nodes["N2"], nodes["N3"]

    _p(verbose, "\n=== Phase A: mining + gossip convergence ===")
    for _ in range(3):
        n1.mine_block()
    assert n1.chain.tip_hash == n2.chain.tip_hash == n3.chain.tip_hash, "nodes failed to converge on mined blocks"
    _p(verbose, f"all 3 nodes converged at height {n1.chain.height()}, tip {n1.chain.tip_hash.hex()[:12]}")
    stats["converged_after_mining"] = True

    _p(verbose, "\n=== Phase B: signed payment propagates and gets mined ===")
    bob_before = n1.chain.balance(bob.address)
    payment = alice.build_transaction(n1.chain, bob.address, amount=5_00000000, fee=1000)
    n1.submit_transaction(payment)
    assert payment.txid() in n2.mempool and payment.txid() in n3.mempool, "tx did not propagate to all peers"
    n2.mine_block()
    assert n1.chain.balance(bob.address) == n2.chain.balance(bob.address) == n3.chain.balance(bob.address)
    assert n1.chain.balance(bob.address) - bob_before >= 5_00000000
    assert payment.txid() not in n1.mempool, "confirmed tx should have left the mempool"
    _p(verbose, f"payment confirmed network-wide; bob balance now {n1.chain.balance(bob.address) / 1e8} NCE")
    stats["payment_confirmed"] = True

    _p(verbose, "\n=== Phase C: double-spend rejection ===")
    spent_input = payment.inputs[0]
    double_spend = Transaction([TxIn(spent_input.prev_txid, spent_input.prev_index)], [TxOut(1, bob.address)])
    double_spend.sign_input(0, alice.privkey)
    n1.submit_transaction(double_spend)
    assert double_spend.txid() not in n1.mempool, "double spend should have been rejected from the mempool"
    _p(verbose, f"double-spend tx {double_spend.txid().hex()[:12]} correctly rejected: "
                f"{n1.log[-1]}")
    stats["double_spend_rejected"] = True

    _p(verbose, "\n=== Phase D: tamper detection ===")
    # Mine a brand-new, never-submitted candidate honestly (valid POW, merkle root
    # matching its real transactions), then have an "attacker" swap a payout amount
    # afterward *without* recomputing the merkle root — exactly what a relay that
    # tries to rewrite a block in flight would do. Since this exact block hash has
    # never been submitted to the chain before, this exercises real re-validation
    # (not the harmless "already-known-hash" duplicate path).
    honest_candidate = n1.chain.mine_new_block([], alice.address, extra_nonce=999999)
    tampered = copy.deepcopy(honest_candidate)
    tampered.transactions[0].outputs[0].amount += 1  # inflate the coinbase reward post-hoc
    assert tampered.hash() == honest_candidate.hash(), "tamper must not touch the header, only the payload"
    tamper_result = n1.chain.add_block(tampered)
    assert tamper_result.status == "invalid", tamper_result
    assert "merkle" in tamper_result.reason.lower(), tamper_result.reason
    _p(verbose, f"tampered block correctly rejected: {tamper_result.reason}")
    stats["tamper_rejected"] = True

    # also verify a signature-forging attempt is caught: someone without alice's private key
    # tries to claim one of alice's UTXOs
    mallory = Wallet()
    utxo_key, utxo_val = next(iter(n1.chain.utxos_for(alice.address).items()))
    forged = Transaction([TxIn(*utxo_key)], [TxOut(utxo_val.amount, mallory.address)])
    forged.sign_input(0, mallory.privkey)  # wrong key — mallory doesn't own this output
    n1.submit_transaction(forged)
    assert forged.txid() not in n1.mempool, "forged signature should have been rejected"
    stats["forged_signature_rejected"] = True
    _p(verbose, f"forged-signature tx correctly rejected: {n1.log[-1]}")

    _p(verbose, "\n=== Phase E: network partition, competing forks, heal, reorg ===")
    pre_fork_tip = n1.chain.tip_hash
    bus.partition([{"N1"}, {"N2", "N3"}])
    _p(verbose, "partitioned: N1 alone vs N2+N3")

    n1.mine_block()  # N1's lone fork: +1 block
    n2.mine_block()
    n2.mine_block()  # N2/N3's fork: +2 blocks -> strictly more work
    assert n1.chain.tip_hash != n2.chain.tip_hash, "forks should have diverged under partition"
    assert n2.chain.tip_hash == n3.chain.tip_hash
    _p(verbose, f"N1 forked to height {n1.chain.height()}; N2/N3 forked to height {n2.chain.height()}")

    bus.heal()
    bus.resync_all()
    assert n1.chain.tip_hash == n2.chain.tip_hash == n3.chain.tip_hash, "network failed to reconverge after heal"
    assert n1.chain.tip_hash != pre_fork_tip
    _p(verbose, f"healed and reconverged on the heavier fork: {n1.chain.tip_hash.hex()[:12]} "
                f"(height {n1.chain.height()})")
    stats["reorg_converged"] = True

    _p(verbose, "\n=== Phase F: difficulty retarget ===")
    bits_seen = []
    for i in range(RETARGET_INTERVAL * 2 + 2):
        b = n1.mine_block()
        bits_seen.append(b.header.bits)
    bus.resync_all()
    assert n1.chain.tip_hash == n2.chain.tip_hash == n3.chain.tip_hash
    retargeted = len(set(bits_seen)) > 1
    stats["retarget_observed"] = retargeted
    _p(verbose, f"bits over {len(bits_seen)} blocks: "
                f"{bits_seen[0]:#010x} -> {bits_seen[-1]:#010x} (changed: {retargeted})")

    _p(verbose, "\n=== Final state ===")
    for name, n in nodes.items():
        _p(verbose, f"{name}: height {n.chain.height()}, tip {n.chain.tip_hash.hex()[:12]}, "
                    f"mempool {len(n.mempool)} tx")
    assert n1.chain.tip_hash == n2.chain.tip_hash == n3.chain.tip_hash
    assert n1.chain.utxo_set.keys() == n2.chain.utxo_set.keys() == n3.chain.utxo_set.keys(), \
        "UTXO sets diverged despite matching tips"
    total_supply = sum(o.amount for o in n1.chain.utxo_set.values())
    expected_supply = sum(subsidy_at(h) for h in range(n1.chain.height() + 1))
    assert total_supply == expected_supply, (total_supply, expected_supply)
    stats["final_height"] = n1.chain.height()
    stats["total_supply"] = total_supply
    stats["all_nodes_converged"] = True

    _p(verbose, "\nALL DEMO PHASES PASSED")
    return stats, nodes
