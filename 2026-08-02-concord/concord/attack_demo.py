"""Double-spend attack simulation, in two parts:

Part A — a mempool-level race. The attacker builds two transactions that
spend the *same* input (one paying a merchant, one paying themself) and
broadcasts each to a different honest node "simultaneously". Every
honest node can only ever confirm one of the two — this is checked, not
assumed — and the loser is provably, permanently dropped.

Part B — a private-chain race, the classic double-spend attack: pay a
merchant, wait for one confirmation, then try to rewrite history with a
privately-mined fork that pays the attacker instead. The attacker races
alone against a 3-miner honest network (so a minority of the network's
hash power) for a bounded time budget, then reconnects. Nothing about
the outcome is hard-coded — the exact same add_block / fork-choice /
gossip-sync code path used everywhere else in Concord is what decides
who wins, and the result (confirmed heights, final balances) is measured
and printed, not asserted in the abstract.
"""

import time

from . import pow as powmod
from ._netutil import spin_up_network, tx_is_known, wait_until
from .block import Block
from .chain import Blockchain
from .mempool import Mempool
from .miner import Miner, build_candidate, mine_block
from .node import Node
from .wallet import Wallet

PRIVATE_RACE_BUDGET_SECONDS = 20


def run_attack_demo():
    print("=" * 70)
    print("CONCORD ATTACK SIMULATION — double-spend defenses under real gossip")
    print("=" * 70)

    alice = Wallet()           # the attacker
    merchant1 = Wallet()       # Part A's honest recipient
    attacker_payout1 = Wallet()  # Part A's fraudulent recipient
    merchant2 = Wallet()       # Part B's honest recipient
    attacker_payout2 = Wallet()  # Part B's fraudulent recipient

    genesis = Block.genesis(alice.address, powmod.GENESIS_TARGET, amount=2000)
    net = spin_up_network(genesis, count=3, base_port=22001)

    try:
        print(f"\nhonest network: {len(net.nodes)} nodes, all mining")
        miners = [Miner(n, alice.address) for n in net.nodes]
        for m in miners:
            m.start()

        ok = wait_until(lambda: net.nodes[0].chain.height() >= 2, timeout=30)
        assert ok, "honest network failed to mine a warm-up block"
        ok = wait_until(
            lambda: all(n.chain.tip_hash == net.nodes[0].chain.tip_hash for n in net.nodes), timeout=15
        )
        assert ok, "honest network failed to converge on one tip before the attack started"
        print(f"honest network warmed up at height {net.nodes[0].chain.height()}")

        # ------------------------------------------------------------------
        print("\n" + "-" * 70)
        print("PART A: mempool double-spend race (same input, two destinations)")
        print("-" * 70)

        utxo_snapshot = dict(net.nodes[0].chain.utxo)
        tx_honest = alice.build_transaction(utxo_snapshot, merchant1.address, 400)
        tx_evil = alice.build_transaction(utxo_snapshot, attacker_payout1.address, 400)
        shared_inputs = {(i.txid, i.index) for i in tx_honest.inputs}
        assert shared_inputs == {(i.txid, i.index) for i in tx_evil.inputs}, \
            "test setup bug: the two transactions must conflict to prove anything"
        print(f"tx_honest {tx_honest.txid()[:12]}... -> merchant1 (400)")
        print(f"tx_evil   {tx_evil.txid()[:12]}... -> attacker_payout1 (400)")
        print(f"both spend the identical input(s): {shared_inputs}")

        accepted_honest = net.nodes[0].submit_transaction(tx_honest)
        accepted_evil = net.nodes[1].submit_transaction(tx_evil)
        print(f"node0.submit(tx_honest) accepted locally: {accepted_honest}")
        print(f"node1.submit(tx_evil) accepted locally:   {accepted_evil}")

        # wait for the race to actually resolve on-chain — NOT just "one more
        # block mined": with 3 miners racing at well under a second per
        # block, it's entirely possible for a block to get mined before either
        # conflicting transaction has even propagated to that miner's mempool,
        # so the very next block can easily contain neither transaction.
        def race_resolved():
            u = net.nodes[0].chain.utxo
            return merchant1.balance(u) == 400 or attacker_payout1.balance(u) == 400

        ok = wait_until(race_resolved, timeout=45)
        assert ok, "neither side of the double-spend was ever confirmed"
        ok = wait_until(
            lambda: all(n.chain.tip_hash == net.nodes[0].chain.tip_hash for n in net.nodes), timeout=15
        )
        assert ok, "honest network failed to converge after Part A's race block"

        merchant1_paid = merchant1.balance(net.nodes[0].chain.utxo) == 400
        attacker1_paid = attacker_payout1.balance(net.nodes[0].chain.utxo) == 400
        assert merchant1_paid != attacker1_paid, "exactly one side of the double-spend must win, not both/neither"
        winner = "tx_honest (merchant1)" if merchant1_paid else "tx_evil (attacker_payout1)"
        print(f"\nwinner confirmed on-chain: {winner}")
        print(f"merchant1 balance:       {merchant1.balance(net.nodes[0].chain.utxo)}")
        print(f"attacker_payout1 balance: {attacker_payout1.balance(net.nodes[0].chain.utxo)}")

        ok = wait_until(
            lambda: all(
                tx_honest.txid() not in n.mempool and tx_evil.txid() not in n.mempool for n in net.nodes
            ),
            timeout=15,
        )
        assert ok, "the losing double-spend transaction was never purged from every mempool"
        print("the losing transaction was purged from every node's mempool (prune_conflicts). PASS.")

        # ------------------------------------------------------------------
        print("\n" + "-" * 70)
        print("PART B: private-chain race (pay -> 1 confirmation -> try to reverse it)")
        print("-" * 70)

        utxo_snapshot2 = dict(net.nodes[0].chain.utxo)
        tx_pay = alice.build_transaction(utxo_snapshot2, merchant2.address, 300)
        net.nodes[0].submit_transaction(tx_pay)
        ok = wait_until(lambda: all(tx_is_known(n, tx_pay.txid()) for n in net.nodes), timeout=15)
        assert ok, "payment transaction was never seen (pending or confirmed) by every node"

        # a miner can be partway through mining a candidate built *before*
        # tx_pay reached its mempool (candidates aren't rebuilt mid-search
        # just because the pool changed — only when the tip moves), so
        # "one more block" isn't guaranteed to be the confirming one; wait
        # for the actual payment to land, not just for height to advance.
        #
        # with 3 independent miners racing concurrently, short-lived forks
        # between them are a normal, expected event — the block that first
        # confirms tx_pay can itself be on a losing side of a 1-block fork
        # a moment later, transiently un-confirming the payment before it
        # gets re-mined. So: find the block that actually contains tx_pay
        # by searching the chain directly, re-search after convergence
        # (don't assume the search done *before* convergence still holds),
        # and don't assume it's positionally "one block before the current
        # tip" — more blocks may have been mined since it confirmed.
        def find_confirming_block(node):
            if merchant2.balance(node.chain.utxo) != 300:
                return None
            for h in node.chain.main_chain_hashes():
                if any(t.txid() == tx_pay.txid() for t in node.chain.blocks_by_hash[h].transactions):
                    return h
            return None

        ok = wait_until(lambda: find_confirming_block(net.nodes[0]) is not None, timeout=45)
        assert ok, "payment to merchant2 was never confirmed"
        ok = wait_until(
            lambda: all(n.chain.tip_hash == net.nodes[0].chain.tip_hash for n in net.nodes), timeout=15
        )
        assert ok, "honest network failed to converge after confirming the payment"
        confirming_hash = find_confirming_block(net.nodes[0])
        assert confirming_hash is not None, \
            "payment to merchant2 was reorganized away and never reconfirmed by convergence"
        fork_point_hash = net.nodes[0].chain.blocks_by_hash[confirming_hash].prev_hash
        print(f"payment confirmed in block {confirming_hash[:12]}... "
              f"(chain now at height {net.nodes[0].chain.height()}, merchant2 balance = 300) "
              f"— 'goods are shipped' at this point")
        print(f"attacker will fork one block earlier, at {fork_point_hash[:12]}...")

        # build the attacker's private chain: replay every real, honestly-
        # mined block up to (but not including) the confirming one, through
        # the exact same Blockchain.add_block validation everyone else uses
        private_chain = Blockchain(genesis)
        replay_hashes = net.nodes[0].chain.main_chain_hashes()
        fork_index = replay_hashes.index(fork_point_hash)
        for h in replay_hashes[1:fork_index + 1]:
            block = net.nodes[0].chain.get_block(h)
            ok, _, _, reason = private_chain.add_block(block)
            assert ok, f"replay of honest block {h[:10]} into the private chain failed: {reason}"

        private_pool = Mempool()
        tx_evil2 = alice.build_transaction(dict(private_chain.utxo), attacker_payout2.address, 300)
        private_pool.add_transaction(tx_evil2, private_chain.utxo)
        print(f"private tx_evil2 {tx_evil2.txid()[:12]}... -> attacker_payout2 (300), "
              f"spends the same input tx_pay did")

        print(f"\nracing: 1 attacker vs {len(net.nodes)} honest miners, "
              f"{PRIVATE_RACE_BUDGET_SECONDS}s budget...")
        deadline = time.time() + PRIVATE_RACE_BUDGET_SECONDS
        honest_start_height = net.nodes[0].chain.height()
        blocks_mined_privately = 0
        while time.time() < deadline:
            candidate = build_candidate(private_chain, private_pool, alice.address)
            solved = mine_block(candidate, stop_check=lambda: time.time() >= deadline)
            if solved is None:
                break
            ok, _, _, reason = private_chain.add_block(solved)
            if ok:
                blocks_mined_privately += 1
            else:
                break
        honest_end_height = net.nodes[0].chain.height()

        print(f"attacker privately mined {blocks_mined_privately} block(s), "
              f"reaching height {private_chain.height()} (work={private_chain.work_of[private_chain.tip_hash]})")
        print(f"meanwhile the honest network advanced from height {honest_start_height} "
              f"to {honest_end_height} (work={net.nodes[0].chain.work_of[net.nodes[0].chain.tip_hash]})")

        attacker_ahead = (
            private_chain.work_of[private_chain.tip_hash]
            > net.nodes[0].chain.work_of[net.nodes[0].chain.tip_hash]
        )
        print(f"attacker's private chain has more cumulative work than the honest chain: {attacker_ahead}")

        print("\nattacker reconnects and lets their node's own sync logic decide the outcome...")
        attacker_node = Node("127.0.0.1", 22099, private_chain, private_pool, name="attacker")
        attacker_node.start()
        attacker_node.connect("127.0.0.1", net.nodes[0].port)
        ok = wait_until(
            lambda: attacker_node.chain.tip_hash == net.nodes[0].chain.tip_hash
            or attacker_ahead,
            timeout=20,
        )

        final_tip_is_honest = attacker_node.chain.tip_hash == net.nodes[0].chain.tip_hash
        merchant2_final = merchant2.balance(attacker_node.chain.utxo)
        attacker2_final = attacker_payout2.balance(attacker_node.chain.utxo)
        print(f"\nattacker node's final tip == honest network's tip: {final_tip_is_honest}")
        print(f"merchant2 balance on the attacker's own (post-sync) view:        {merchant2_final}")
        print(f"attacker_payout2 balance on the attacker's own (post-sync) view: {attacker2_final}")

        attacker_node.stop()

        if attacker_ahead:
            print("\nRESULT: the attacker actually accumulated more work than the honest "
                  "network in this run (a real, if rare, possibility with these odds) — "
                  "the double-spend would have succeeded here. Nothing was hidden: this is "
                  "why merchants wait for multiple confirmations, not just one, in real systems.")
        else:
            assert final_tip_is_honest, "attacker did not out-work the honest chain, yet ended up on a different tip"
            assert merchant2_final == 300, "the confirmed payment to merchant2 was lost even though the honest chain won"
            assert attacker2_final == 0, "the attacker's double-spend paid out despite losing the fork race"
            print("\nRESULT: the honest network's greater cumulative work defeated the private "
                  "fork. The attacker's alternate history — including tx_evil2 — was discarded "
                  "the moment the attacker's own node resynced. merchant2's payment stands.")

        for m in miners:
            m.stop()

        print("\n" + "=" * 70)
        print("ATTACK SIMULATION COMPLETE")
        print("=" * 70)
        return True
    finally:
        net.stop()


if __name__ == "__main__":
    run_attack_demo()
