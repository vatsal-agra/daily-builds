"""`keystone` CLI: keygen, a full multi-node network demo, and an explorer
server for interactively watching a live demo network."""
from __future__ import annotations

import argparse
import sys
import time

from . import script
from .chain import Blockchain, create_genesis_chain
from .node import FullNode
from .wallet import Wallet

DEMO_BITS = 0x1F00FFFF  # easy enough that a demo mines a real block in well under a second


def cmd_keygen(args) -> int:
    wallet = Wallet.generate()
    print(f"private key: {wallet.privkey:064x}")
    print(f"public key:  {wallet.pubkey_compressed.hex()}")
    print(f"address:     {wallet.address}")
    return 0


def _build_network(n_nodes: int, base_port: int, bits: int, miner_wallets=None):
    genesis_wallet = miner_wallets[0] if miner_wallets else Wallet.generate()
    seed_chain = create_genesis_chain(genesis_wallet, bits=bits)
    genesis_block = seed_chain.blocks[seed_chain.tip_hash]

    wallets = miner_wallets or [Wallet.generate() for _ in range(n_nodes)]
    nodes = []
    for i in range(n_nodes):
        chain = Blockchain(genesis_block)
        node = FullNode("127.0.0.1", base_port + i, chain, miner_wallet=wallets[i], name=f"node{i}")
        try:
            node.start()
        except OSError as e:
            # Clean up whatever already bound successfully instead of
            # leaking listening sockets, then fail with a message that
            # actually says what to do — not a raw traceback.
            for started in nodes:
                started.stop()
            raise SystemExit(
                f"error: couldn't start node{i} on 127.0.0.1:{base_port + i} ({e}). "
                f"Try a different --base-port."
            )
        nodes.append(node)

    # connect in a ring so gossip has to actually relay, not just direct-broadcast
    for i in range(n_nodes):
        nodes[i].connect_to("127.0.0.1", base_port + ((i + 1) % n_nodes))
    time.sleep(0.3)
    return nodes, wallets


def cmd_demo(args) -> int:
    if args.nodes < 1:
        print(f"error: --nodes must be at least 1 (got {args.nodes})", file=sys.stderr)
        return 2
    if args.nodes == 1:
        print("note: a 1-node network has no peers to gossip with — it'll just mine on its own.")
    if args.seconds <= 0:
        print(f"error: --seconds must be positive (got {args.seconds})", file=sys.stderr)
        return 2
    print(f"Starting a {args.nodes}-node Keystone network (ring topology, real TCP sockets)...")
    nodes, wallets = _build_network(args.nodes, args.base_port, DEMO_BITS)

    for node in nodes:
        node.start_mining()

    print(f"Mining for {args.seconds}s across all {args.nodes} nodes...")
    deadline = time.time() + args.seconds
    payment = None
    while time.time() < deadline:
        time.sleep(0.2)
        # Keep trying to send a real wallet-to-wallet payment as soon as
        # *any* node's wallet has a matured, spendable coinbase output —
        # which node that ends up being is up to the luck of mining and
        # reorgs, so retrying every tick against every wallet (rather than
        # a single fixed-time attempt against a hardcoded node0) is what
        # makes this deterministic instead of an occasionally-flaky no-op.
        if payment is None:
            payment = _send_demo_payment(nodes, wallets)

    def payment_landed() -> bool:
        if payment is None:
            return False
        check_node = nodes[payment["sender_idx"]]
        recipient = wallets[payment["recipient_idx"]]
        return check_node.chain.utxo_set.balance_of(recipient.pubkey_hash) > payment["balance_before"]

    # If the payment only made it into the mempool right at the end of the
    # window, give it a short grace period (mining still running) to
    # actually get confirmed rather than reporting a false negative.
    grace_deadline = time.time() + 3.0
    while payment is not None and not payment_landed() and time.time() < grace_deadline:
        time.sleep(0.1)

    # Give the network a bounded settling window to converge on one tip
    # *with mining still running*. Two equal-height chains can legitimately
    # tie on cumulative work (this build's own adversarial-review testing
    # hit exactly this: two competing tips, every node already aware of
    # both, deadlocked at identical work) — that isn't a bug, it's how real
    # Nakamoto consensus behaves, and a genuine tie only ever gets broken by
    # someone finding the *next* block, never by waiting longer for
    # messages that have already arrived. So mining keeps running through
    # this window instead of stopping first and idly hoping propagation
    # alone resolves it. See REVIEW.md.
    settle_deadline = time.time() + 10.0
    while time.time() < settle_deadline:
        if len({n.chain.tip_hash for n in nodes}) == 1:
            break
        time.sleep(0.1)

    for node in nodes:
        node.stop_mining()
    time.sleep(0.3)

    tips = {n.chain.tip_hash for n in nodes}
    total_mined = sum(n.blocks_mined for n in nodes)
    total_reorgs = sum(n.net.reorg_count for n in nodes)
    payment_confirmed = payment_landed()

    print()
    print("=== Demo report ===")
    for i, n in enumerate(nodes):
        print(f"  node{i}: height={n.chain.height()} tip={n.chain.tip_hash[:16]}… "
              f"blocks_mined={n.blocks_mined} peers={n.net.peer_count()}")
    print(f"  converged on one tip: {len(tips) == 1}")
    print(f"  total blocks mined across network: {total_mined}")
    print(f"  reorgs observed: {total_reorgs}")
    print(f"  wallet-to-wallet payment confirmed on-chain: {payment_confirmed}")

    balances_match = True
    for i, w in enumerate(wallets):
        bals = [n.chain.utxo_set.balance_of(w.pubkey_hash) for n in nodes]
        if len(set(bals)) != 1:
            balances_match = False
        print(f"  wallet{i} ({w.address}) balance per node: {bals}")

    ok = len(tips) == 1 and balances_match and total_mined >= args.nodes and payment_confirmed
    for n in nodes:
        n.stop()

    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _send_demo_payment(nodes, wallets):
    """Returns (sender_index, recipient_index) once a real transaction has
    actually been submitted to the mempool, or None. Which node's wallet
    ends up with a matured, spendable coinbase output first is up to the
    luck of mining + reorgs — retrying every tick *and* checking every
    node/wallet pair (not just a hardcoded node0/wallet0) is what makes
    this deterministic instead of an occasionally-flaky no-op: node0 isn't
    guaranteed to ever have spendable funds if its blocks keep losing races
    against other nodes' — a real interaction between mining variance and
    coinbase maturity this build's own testing surfaced, see REVIEW.md."""
    fee = 1000
    for i, (node, wallet) in enumerate(zip(nodes, wallets)):
        spendable = [
            (txid, idx, txout.amount)
            for (txid, idx), (txout, h, is_cb) in node.chain.utxo_set.utxos.items()
            if txout.script_pubkey == wallet.lock_script_for_self()
            and (not is_cb or node.chain.height() - h >= 2)
            and txout.amount > fee
        ]
        if not spendable:
            continue
        txid, idx, amount = spendable[0]
        recipient_idx = (i + 1) % len(wallets)
        recipient = wallets[recipient_idx]
        # Snapshot the recipient's balance *before* submission, on this same
        # node's view, so confirmation can later be proven by strict
        # increase — the recipient is itself one of the mining wallets, so
        # "balance > 0" alone would prove nothing (its own block rewards
        # already make that true).
        balance_before = node.chain.utxo_set.balance_of(recipient.pubkey_hash)
        tx = wallet.build_transaction([(txid, idx)], [(amount - fee, recipient.pubkey_hash)])
        accepted = node.submit_transaction(tx)
        if accepted:
            print(f"  [demo payment] node{i} -> wallet{recipient_idx}: {amount - fee} keystones")
            return {"sender_idx": i, "recipient_idx": recipient_idx, "balance_before": balance_before}
    return None


def cmd_script_demo(args) -> int:
    """Standalone demonstration of the multisig scripting stretch feature."""
    print("Multisig (2-of-3) scripting demo")
    signers = [Wallet.generate() for _ in range(3)]
    pubkeys = [w.pubkey_compressed for w in signers]
    lock = script.multisig_lock(2, pubkeys)
    print(f"  locking script: {lock}")

    from .crypto import sha256, sign as ec_sign
    fake_sighash = sha256(b"demo transaction body")

    sig1 = script.encode_sig(*ec_sign(signers[0].privkey, fake_sighash))
    sig2 = script.encode_sig(*ec_sign(signers[1].privkey, fake_sighash))
    sig_only_one = script.encode_sig(*ec_sign(signers[2].privkey, fake_sighash))

    unlock_ok = script.multisig_unlock([sig1, sig2])
    result_ok = script.execute(unlock_ok, lock, fake_sighash)
    print(f"  spend with 2 valid sigs (signers 0,1): {result_ok} (expect True)")

    unlock_bad = script.multisig_unlock([sig_only_one])
    result_bad = script.execute(unlock_bad, lock, fake_sighash)
    print(f"  spend with only 1 sig: {result_bad} (expect False)")

    non_signer = Wallet.generate()
    forged = script.encode_sig(*ec_sign(non_signer.privkey, fake_sighash))
    unlock_forged = script.multisig_unlock([sig1, forged])
    result_forged = script.execute(unlock_forged, lock, fake_sighash)
    print(f"  spend with 1 valid + 1 non-signer sig: {result_forged} (expect False)")

    ok = result_ok is True and result_bad is False and result_forged is False
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_explorer(args) -> int:
    from . import explorer as explorer_module

    if args.nodes < 1:
        print(f"error: --nodes must be at least 1 (got {args.nodes})", file=sys.stderr)
        return 2
    if args.seconds <= 0:
        print(f"error: --seconds must be positive (got {args.seconds})", file=sys.stderr)
        return 2
    print(f"Starting a {args.nodes}-node network with a block explorer on http://127.0.0.1:{args.port}")
    nodes, wallets = _build_network(args.nodes, args.base_port, DEMO_BITS)
    for node in nodes:
        node.start_mining()

    server, thread = explorer_module.run_explorer_in_thread(nodes[0], "127.0.0.1", args.port)
    actual_port = server.server_address[1]
    print(f"Explorer live at http://127.0.0.1:{actual_port} (Ctrl+C to stop, or --seconds elapses)")

    try:
        deadline = time.time() + args.seconds
        mid_sent = False
        while time.time() < deadline:
            time.sleep(0.2)
            if not mid_sent and time.time() > deadline - args.seconds / 2:
                mid_sent = True
                _send_demo_payment(nodes, wallets)
    except KeyboardInterrupt:
        pass
    finally:
        for node in nodes:
            node.stop_mining()
        time.sleep(0.3)
        server.shutdown()
        for node in nodes:
            node.stop()
    print("Explorer demo finished.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keystone", description="A from-scratch PoW blockchain & cryptocurrency.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="generate a new wallet keypair + address")
    p_keygen.set_defaults(func=cmd_keygen)

    p_demo = sub.add_parser("demo", help="run a multi-node gossiping network end-to-end")
    p_demo.add_argument("--nodes", type=int, default=4)
    p_demo.add_argument("--seconds", type=float, default=8.0)
    p_demo.add_argument("--base-port", type=int, default=18800)
    p_demo.set_defaults(func=cmd_demo)

    p_script = sub.add_parser("script-demo", help="demonstrate the m-of-n multisig scripting stretch feature")
    p_script.set_defaults(func=cmd_script_demo)

    p_explorer = sub.add_parser("explorer", help="run a demo network with a live HTML block explorer")
    p_explorer.add_argument("--nodes", type=int, default=3)
    p_explorer.add_argument("--seconds", type=float, default=20.0)
    p_explorer.add_argument("--base-port", type=int, default=18900)
    p_explorer.add_argument("--port", type=int, default=8765)
    p_explorer.set_defaults(func=cmd_explorer)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
