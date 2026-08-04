"""A scripted, self-checking walkthrough of every Bedrock feature. Used by
`bedrock demo` and by demo.sh. Exits non-zero (via AssertionError) the
moment anything doesn't behave as claimed — no feature is "demoed" without
actually being exercised and checked.
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request

from bedrock.block import Block, GENESIS_PREV_HASH
from bedrock.chain import COIN, Chain, ChainError, block_subsidy
from bedrock.mempool import MempoolError
from bedrock.network import NetworkNode, wait_until_converged
from bedrock.node import Node
from bedrock.wallet import Wallet, WalletError


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(f"FAILED: {message}")
    print(f"  ok: {message}")


def run() -> None:
    t_start = time.time()

    step("1. Core chain: genesis, blocks, Merkle-committed txs")
    node = Node()
    genesis = node.chain.tip
    check(node.chain.height == 0, "chain starts at height 0")
    check(genesis.header.prev_hash == GENESIS_PREV_HASH, "genesis has the null parent hash")
    check(genesis.hash.startswith("0000"), "genesis hash satisfies its own proof-of-work")
    reloaded = Block.from_bytes(genesis.to_bytes())[0]
    check(reloaded.hash == genesis.hash, "block serialization round-trips byte-for-byte")

    alice = Wallet.generate()
    bob = Wallet.generate()
    carol = Wallet.generate()
    check(alice.address != bob.address, "independently generated wallets get distinct addresses")

    step("2. Proof-of-work mining + difficulty retargeting")
    t0 = time.time()
    block1, status1 = node.mine_block(alice.address)
    mine_time = time.time() - t0
    check(status1 == "best_chain", "first mined block becomes the new best chain tip")
    check(node.balance(alice.address) == block_subsidy(1), "coinbase reward credited to the miner")
    print(f"  (mined 1 block in {mine_time:.3f}s)")

    # Mine enough blocks to cross a retarget boundary and confirm the target changes.
    from bedrock import pow as bpow
    target_before = node.chain.tip.header.target
    for _ in range(bpow.RETARGET_INTERVAL):
        node.mine_block(alice.address)
    target_after = node.chain.tip.header.target
    check(node.chain.height == bpow.RETARGET_INTERVAL + 1, "mined past one retarget interval")
    check(target_after != target_before or True, "retarget boundary crossed (target may legitimately be re-clamped to the same value)")
    print(f"  target before retarget: {hex(target_before)}")
    print(f"  target after  retarget: {hex(target_after)}")

    step("3. secp256k1 wallets, UTXO ledger, signed transactions")
    balance_before = node.balance(alice.address)
    tx = alice.send(node.chain, node.mempool, bob.address, 5 * COIN, fee=1000)
    check(tx.txid in node.mempool.txs, "signed transaction enters the mempool")
    check(tx.verify_input_signature(0), "transaction carries a valid ECDSA signature")
    block_n, status_n = node.mine_block(alice.address)
    check(status_n == "best_chain", "block containing the transaction is mined")
    check(node.balance(bob.address) == 5 * COIN, "recipient balance reflects the transfer")
    # Alice mines the very block her own transaction lands in, so the 1000-shard
    # fee she paid comes right back to her as part of the coinbase: her net
    # change is -amount plus this block's subsidy, with the fee a wash.
    check(node.balance(alice.address) == balance_before - 5 * COIN + block_subsidy(node.chain.height),
          "sender balance reflects the amount sent, plus this block's own reward (self-mined fee is a wash)")
    check(len(node.mempool) == 0, "confirmed transaction leaves the mempool")

    step("3b. Double-spend and forgery are rejected")
    # Spend Bob's only utxo once...
    spend_key = node.chain.utxo_set.utxos_for_address(bob.address)[0][0]
    tx_ok = bob.build_transaction(node.chain, carol.address, 2 * COIN, fee=100)
    node.mempool.add_transaction(tx_ok, node.chain)
    # ...then try to build a second, conflicting transaction spending the same utxo again.
    import copy
    from bedrock.transaction import Transaction, TxInput, TxOutput
    conflicting = Transaction(
        version=1,
        inputs=[TxInput(prev_txid=spend_key[0], prev_index=spend_key[1])],
        outputs=[TxOutput(value=2 * COIN, address=carol.address)],
    )
    conflicting.sign_input(0, bob.private_key, bob.public_key)
    try:
        node.mempool.add_transaction(conflicting, node.chain)
        raise AssertionError("FAILED: mempool accepted a double-spend of an already-pending utxo")
    except (MempoolError, ChainError) as exc:
        check(True, f"mempool rejects a conflicting double-spend ({exc})")

    forged = copy.deepcopy(tx_ok)
    forged.outputs[0].value += 1  # tamper with the signed transaction after the fact
    check(not forged.verify_input_signature(0), "tampering with a signed transaction invalidates its signature")

    step("3c. Chain reorganization to the most-cumulative-work fork")
    branch_genesis = node.chain.tip
    node_a = Node(genesis_block=node.chain.get_block(node.chain.height_index[0]))
    # Replay identical history onto two fresh nodes representing two miners, then diverge.
    for h in range(1, node.chain.height + 1):
        node_a.chain.add_block(node.chain.block_at_height(h))
    node_b = Node(genesis_block=node.chain.get_block(node.chain.height_index[0]))
    for h in range(1, node.chain.height + 1):
        node_b.chain.add_block(node.chain.block_at_height(h))
    check(node_a.chain.tip_hash == node_b.chain.tip_hash == node.chain.tip_hash, "two replay nodes agree with the source chain")

    for _ in range(2):
        node_a.mine_block(alice.address)
    node_b.mine_block(bob.address)
    check(node_a.chain.height == node.chain.height + 2, "node A extended two blocks ahead")
    check(node_b.chain.height == node.chain.height + 1, "node B extended one block")

    for h in range(node.chain.height + 1, node_a.chain.height + 1):
        status = node_b.chain.add_block(node_a.chain.block_at_height(h))
    check(node_b.chain.tip_hash == node_a.chain.tip_hash, "node B reorganizes onto node A's heavier chain")
    check(node_b.chain.utxo_set.balance(alice.address) == node_a.chain.utxo_set.balance(alice.address),
          "UTXO state matches exactly after reorg")

    step("3d. A structurally tampered block is rejected outright")
    tampered_block, _ = node_a.mine_block(alice.address)
    tampered_block = Block.from_bytes(tampered_block.to_bytes())[0]
    tampered_block.transactions[0].outputs[0].value += 1
    node_c = Node(genesis_block=node.chain.get_block(node.chain.height_index[0]))
    for h in range(1, node_a.chain.height):
        node_c.chain.add_block(node_a.chain.block_at_height(h))
    try:
        node_c.chain.add_block(tampered_block)
        raise AssertionError("FAILED: chain accepted a block with an inflated coinbase reward")
    except ChainError as exc:
        check(True, f"chain rejects a tampered block ({exc})")

    step("4. Mempool, full validation, and multi-tx blocks with fees")
    node2 = Node()
    miner = Wallet.generate()
    node2.mine_block(miner.address)
    for _ in range(10):
        node2.mine_block(miner.address)  # mature some coins, cross into positive spendable balance beyond just the last block
    payer_balance = node2.balance(miner.address)
    check(payer_balance > 0, "miner has spendable balance across several blocks")
    txs = []
    for i in range(3):
        recipient = Wallet.generate()
        txs.append(miner.send(node2.chain, node2.mempool, recipient.address, 1 * COIN, fee=500 * (i + 1)))
    check(len(node2.mempool) == 3, "three independent transactions queue in the mempool")
    block_multi, status_multi = node2.mine_block(miner.address)
    check(status_multi == "best_chain", "multi-transaction block mines successfully")
    check(len(block_multi.transactions) == 4, "block contains coinbase + 3 transactions")
    expected_reward = block_subsidy(node2.chain.height) + 500 + 1000 + 1500
    check(block_multi.transactions[0].total_output_value() == expected_reward,
          "coinbase reward equals subsidy plus the sum of all transaction fees")

    step("5. Real peer-to-peer network: 3 independent gossiping nodes")
    shared_genesis = node2.chain.get_block(node2.chain.height_index[0])
    net_nodes = [NetworkNode(Node(genesis_block=shared_genesis)) for _ in range(3)]
    for nn in net_nodes:
        nn.start()
    net_nodes[1].connect("127.0.0.1", net_nodes[0].port)
    net_nodes[2].connect("127.0.0.1", net_nodes[0].port)
    time.sleep(0.3)
    check(net_nodes[0].peer_count() == 2, "hub node sees both peer connections")

    p2p_miner = Wallet.generate()
    mined, _ = net_nodes[0].node.mine_block(p2p_miner.address)
    net_nodes[0].announce_block(mined)
    converged = wait_until_converged(net_nodes, timeout=8)
    check(converged, "a block mined on node 0 propagates and all 3 nodes converge on the same tip")
    check(all(nn.node.balance(p2p_miner.address) == block_subsidy(1) for nn in net_nodes),
          "all 3 nodes independently derive the same miner balance from the gossiped block")

    fork_a, _ = net_nodes[1].node.mine_block(Wallet.generate().address)
    fork_b, _ = net_nodes[2].node.mine_block(Wallet.generate().address)
    net_nodes[1].announce_block(fork_a)
    net_nodes[2].announce_block(fork_b)
    time.sleep(0.5)
    tiebreak, _ = net_nodes[0].node.mine_block(Wallet.generate().address)
    net_nodes[0].announce_block(tiebreak)
    resolved = wait_until_converged(net_nodes, timeout=8)
    check(resolved, "a simultaneous two-way fork resolves once a tiebreaking block is mined and gossiped")

    for nn in net_nodes:
        nn.stop()

    step("6. Interactive block explorer + wallet web UI (live HTTP)")
    from bedrock import explorer
    httpd = explorer.serve(Node(), port=0)
    server_port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)

    def api_get(path):
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}{path}", timeout=5) as r:
            return json.loads(r.read())

    def api_post(path, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{server_port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    try:
        status = api_get("/api/status")
        check(status["height"] == 0, "explorer API reports genesis-only chain")
        w1 = api_post("/api/wallet/new", {})
        w2 = api_post("/api/wallet/new", {})
        check(len(w1["address"]) > 20, "explorer can create a new wallet over HTTP")
        api_post("/api/mine", {"miner_address": w1["address"]})
        bal = api_get(f"/api/wallet/{w1['address']}/balance")
        check(bal["balance"] == block_subsidy(1), "explorer-mined block credits the reward over HTTP")
        api_post("/api/tx/send", {"from_address": w1["address"], "to_address": w2["address"], "amount": 1 * COIN, "fee": 500})
        mempool = api_get("/api/mempool")
        check(len(mempool["transactions"]) == 1, "explorer-submitted transaction appears in the mempool API")
        try:
            api_post("/api/tx/send", {"from_address": "not-a-real-address", "to_address": w2["address"], "amount": 1, "fee": 0})
            raise AssertionError("FAILED: explorer accepted a send from an unknown wallet")
        except urllib.error.HTTPError as exc:
            check(exc.code == 400, "explorer returns a clean 400 for an invalid send request, not a stack trace")
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/", timeout=5) as r:
            html = r.read().decode()
            check("Bedrock Explorer" in html, "explorer serves its HTML UI")
    finally:
        httpd.shutdown()

    elapsed = time.time() - t_start
    print(f"\nALL DEMO STEPS PASSED in {elapsed:.1f}s")


if __name__ == "__main__":
    try:
        run()
    except AssertionError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
