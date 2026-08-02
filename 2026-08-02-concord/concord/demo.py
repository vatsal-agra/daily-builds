"""End-to-end demo: three real P2P nodes on localhost, one mines, a
transaction propagates and gets confirmed, balances agree everywhere,
and a Merkle inclusion proof is independently verified client-side."""

import time

from . import pow as powmod
from ._netutil import spin_up_network, tx_is_known, wait_until
from .block import Block
from .merkle import verify_proof
from .miner import Miner
from .wallet import Wallet


def run_demo():
    print("=" * 70)
    print("CONCORD DEMO — a from-scratch blockchain + P2P network")
    print("=" * 70)

    alice = Wallet()
    bob = Wallet()
    print(f"\nalice address: {alice.address}")
    print(f"bob address:   {bob.address}")

    genesis = Block.genesis(alice.address, powmod.GENESIS_TARGET, amount=1000)
    print(f"\ngenesis hash: {genesis.hash()}  (premines 1000 to alice)")

    net = spin_up_network(genesis, count=3, base_port=21001)
    print(f"\nspun up {len(net.nodes)} nodes:")
    for i, (node, explorer) in enumerate(zip(net.nodes, net.explorers)):
        print(f"  node{i}: p2p=127.0.0.1:{node.port}  api=http://127.0.0.1:{explorer.port}")

    try:
        print("\n--- mining on node0 ---")
        miner = Miner(net.nodes[0], alice.address)
        miner.start()
        ok = wait_until(lambda: net.nodes[0].chain.height() >= 3, timeout=30)
        assert ok, "node0 failed to mine 3 blocks in time"
        print(f"node0 height: {net.nodes[0].chain.height()}")

        print("\n--- waiting for gossip sync to node1, node2 ---")
        ok = wait_until(
            lambda: all(n.chain.height() == net.nodes[0].chain.height() for n in net.nodes),
            timeout=20,
        )
        assert ok, "not all nodes synced to the same height"
        tip = net.nodes[0].chain.tip_hash
        assert all(n.chain.tip_hash == tip for n in net.nodes), "nodes disagree on tip hash"
        print(f"all {len(net.nodes)} nodes agree on tip {tip[:16]}... at height {net.nodes[0].chain.height()}")

        print("\n--- alice pays bob 150, submitted via node0 ---")
        tx = alice.build_transaction(net.nodes[0].chain.utxo, bob.address, 150)
        accepted = net.nodes[0].submit_transaction(tx)
        assert accepted, "node0 rejected alice's own transaction"
        ok = wait_until(lambda: all(tx_is_known(n, tx.txid()) for n in net.nodes), timeout=10)
        assert ok, "transaction was never seen (pending or confirmed) by every node"
        print(f"tx {tx.txid()[:16]}... has reached every node (pending or already confirmed)")

        print("\n--- mining continues, tx gets confirmed ---")
        # wait for the payment to actually confirm, not just for "one more
        # block" — a candidate block already being mined when the tx landed
        # in the pool won't include it, so the very next block isn't
        # guaranteed to be the confirming one
        ok = wait_until(lambda: bob.balance(net.nodes[0].chain.utxo) == 150, timeout=30)
        assert ok, "no block ever confirmed alice's payment to bob"
        ok = wait_until(
            lambda: all(n.chain.height() == net.nodes[0].chain.height() for n in net.nodes)
            and tx.txid() not in net.nodes[1].mempool,
            timeout=20,
        )
        assert ok, "confirmation did not propagate / mempool not pruned everywhere"
        miner.stop()

        print("\n--- balances agree across all 3 independent nodes ---")
        for i, node in enumerate(net.nodes):
            a_bal = alice.balance(node.chain.utxo)
            b_bal = bob.balance(node.chain.utxo)
            print(f"  node{i}: alice={a_bal}  bob={b_bal}")
            assert b_bal == 150, f"node{i} disagrees on bob's balance"
        print("balances agree.")

        print("\n--- verifying a Merkle inclusion proof against the explorer API ---")
        import urllib.request
        import json
        api = f"http://127.0.0.1:{net.explorers[0].port}"
        chain_summary = json.loads(urllib.request.urlopen(f"{api}/api/chain").read())
        proven = False
        for b in chain_summary:
            block_detail = json.loads(urllib.request.urlopen(f"{api}/api/block/{b['hash']}").read())
            for t in block_detail["transactions"]:
                if t["txid"] == tx.txid():
                    proof = json.loads(
                        urllib.request.urlopen(f"{api}/api/block/{b['hash']}/proof/{tx.txid()}").read()
                    )
                    leaf = bytes.fromhex(proof["leaf"])
                    root = bytes.fromhex(proof["root"])
                    steps = [(bytes.fromhex(s["sibling"]), s["is_right"]) for s in proof["steps"]]
                    assert verify_proof(leaf, steps, root), "merkle proof failed to verify"
                    proven = True
        assert proven, "could not find the confirmed tx to build a merkle proof for"
        print("merkle inclusion proof independently verified. OK.")

        print("\n" + "=" * 70)
        print("DEMO PASSED")
        print("=" * 70)
        return True
    finally:
        net.stop()


if __name__ == "__main__":
    run_demo()
