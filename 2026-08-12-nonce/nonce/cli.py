#!/usr/bin/env python3
"""Nonce CLI — mine, transact, and run multi-node network scenarios from
the command line."""

import argparse
import sys

from .wallet import Wallet, InsufficientFunds
from .core.blockchain import Blockchain, create_genesis, subsidy_at, COIN
from .core.difficulty import bits_to_target


def cmd_wallet(args):
    w = Wallet()
    print(f"address:     {w.address}")
    print(f"private key: {w.privkey:#066x}")
    print(f"public key:  {w.pubkey_bytes.hex()}")


def cmd_demo(args):
    from .demo_scenario import run_demo
    run_demo(verbose=True)


def cmd_mine(args):
    w = Wallet()
    print(f"mining to a fresh wallet: {w.address}")
    genesis = create_genesis(w.address)
    chain = Blockchain(genesis)
    print(f"genesis: {genesis.hash().hex()}  height 0  reward {subsidy_at(0) / 1e8} NCE")
    for i in range(args.blocks):
        block = chain.mine_new_block([], w.address, extra_nonce=i + 1)
        result = chain.add_block(block)
        target = bits_to_target(block.header.bits)
        print(f"height {block.height:>3}  hash {block.hash().hex()[:16]}  "
              f"bits {block.header.bits:#010x}  status {result.status}")
    print(f"\nfinal balance for {w.address}: {chain.balance(w.address) / 1e8} NCE")


def cmd_explorer(args):
    from .explorer_server import run_explorer
    run_explorer(host=args.host, port=args.port, num_nodes=args.nodes)


# ----------------------------------------------------------------------
# `nonce local ...` — a persisted single-node chain + wallet you can
# genuinely mine into and send from across separate CLI invocations,
# rather than everything living only inside one in-memory demo run.

def _load_local(args):
    from . import store
    try:
        loaded = store.load(args.data_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
    if loaded is None:
        print(f"error: no chain found in {args.data_dir!r} — run `nonce local init` first", file=sys.stderr)
        raise SystemExit(1)
    return loaded


def cmd_local_init(args):
    from . import store
    if store.exists(args.data_dir):
        print(f"error: {args.data_dir!r} already has a chain "
              f"(use --data-dir to start a separate one)", file=sys.stderr)
        raise SystemExit(1)
    wallet = Wallet()
    genesis = create_genesis(wallet.address)
    chain = Blockchain(genesis)
    store.save(args.data_dir, wallet, chain)
    print(f"initialized a new chain in {args.data_dir!r}")
    print(f"your address: {wallet.address}")
    print(f"genesis reward ({subsidy_at(0) / 1e8} NCE) is already yours — try `nonce local balance`")


def cmd_local_address(args):
    wallet, _chain = _load_local(args)
    print(wallet.address)


def cmd_local_balance(args):
    wallet, chain = _load_local(args)
    bal = chain.balance(wallet.address)
    print(f"{bal / 1e8:.8f} NCE  ({bal} sats)  at height {chain.height()}")


def cmd_local_mine(args):
    from . import store
    wallet, chain = _load_local(args)
    for i in range(args.blocks):
        block = chain.mine_new_block([], wallet.address, extra_nonce=chain.height() + i + 1)
        result = chain.add_block(block)
        print(f"height {block.height:>4}  {block.hash().hex()[:16]}  "
              f"bits {block.header.bits:#010x}  {result.status}")
    store.save(args.data_dir, wallet, chain)
    print(f"\nbalance: {chain.balance(wallet.address) / 1e8:.8f} NCE")


def cmd_local_send(args):
    from . import store
    wallet, chain = _load_local(args)

    if args.amount <= 0:
        print("error: amount must be positive", file=sys.stderr)
        raise SystemExit(1)
    amount_sats = round(args.amount * COIN)
    fee_sats = round(args.fee * COIN)

    try:
        tx = wallet.build_transaction(chain, args.to_address, amount_sats, fee=fee_sats)
    except InsufficientFunds as e:
        print(f"error: insufficient funds — {e}", file=sys.stderr)
        raise SystemExit(1)
    except ValueError as e:
        print(f"error: invalid recipient address — {e}", file=sys.stderr)
        raise SystemExit(1)

    # this "local" mode has no network/mempool of its own, so the payment
    # is mined into the very next block immediately rather than waiting
    # in a mempool for a separate `mine` call
    block = chain.mine_new_block([tx], wallet.address, extra_nonce=chain.height() + 1)
    result = chain.add_block(block)
    assert result.status == "new_tip", result  # our own freshly-built block must always validate
    store.save(args.data_dir, wallet, chain)

    print(f"sent {args.amount} NCE to {args.to_address}")
    print(f"mined into block {block.hash().hex()[:16]} (height {block.height})")
    print(f"new balance: {chain.balance(wallet.address) / 1e8:.8f} NCE")


def cmd_local_history(args):
    """Every payment that ever landed in this wallet, oldest to newest.
    Deliberately incoming-only: showing outgoing amounts precisely would
    require walking every prior block's UTXOs by (txid, index) to resolve
    what each spent input used to be worth, which is more machinery than
    a CLI convenience view needs — `nonce local balance` already gives
    the authoritative current total."""
    wallet, chain = _load_local(args)
    shown = 0
    for h in chain.chain_to_genesis(chain.tip_hash):
        block = chain.blocks[h]
        for tx in block.transactions:
            for out in tx.outputs:
                if out.to_address == wallet.address:
                    kind = "coinbase reward" if tx.is_coinbase() else "received"
                    print(f"height {block.height:>4}  +{out.amount / 1e8:.8f} NCE  ({kind})")
                    shown += 1
    if shown == 0:
        print("no incoming payments yet")


def build_parser():
    p = argparse.ArgumentParser(prog="nonce", description="A from-scratch proof-of-work blockchain.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("wallet", help="generate a new keypair + address").set_defaults(func=cmd_wallet)

    demo_p = sub.add_parser("demo", help="run the full scripted end-to-end demo scenario")
    demo_p.set_defaults(func=cmd_demo)

    mine_p = sub.add_parser("mine", help="mine an isolated single-node chain and print progress")
    mine_p.add_argument("--blocks", type=int, default=10)
    mine_p.set_defaults(func=cmd_mine)

    exp_p = sub.add_parser("explorer", help="run the live block-explorer web server")
    exp_p.add_argument("--host", default="127.0.0.1")
    exp_p.add_argument("--port", type=int, default=8420)
    exp_p.add_argument("--nodes", type=int, default=3)
    exp_p.set_defaults(func=cmd_explorer)

    local_p = sub.add_parser("local", help="a persisted single-node wallet + chain you can mine/send with "
                                            "across separate commands (state saved to --data-dir)")
    local_p.add_argument("--data-dir", default=".nonce-data",
                          help="directory to save wallet.json/chain.json in (default: .nonce-data)")
    local_sub = local_p.add_subparsers(dest="local_command", required=True)

    local_sub.add_parser("init", help="create a fresh wallet + genesis block").set_defaults(func=cmd_local_init)
    local_sub.add_parser("address", help="print your address").set_defaults(func=cmd_local_address)
    local_sub.add_parser("balance", help="print your current balance").set_defaults(func=cmd_local_balance)
    local_sub.add_parser("history", help="print every incoming payment").set_defaults(func=cmd_local_history)

    local_mine_p = local_sub.add_parser("mine", help="mine empty blocks to yourself")
    local_mine_p.add_argument("--blocks", type=int, default=1)
    local_mine_p.set_defaults(func=cmd_local_mine)

    local_send_p = local_sub.add_parser("send", help="build, sign, and mine a payment in one step")
    local_send_p.add_argument("to_address")
    local_send_p.add_argument("amount", type=float, help="amount in NCE (e.g. 1.5)")
    local_send_p.add_argument("--fee", type=float, default=0.00001, help="fee in NCE (default: 0.00001)")
    local_send_p.set_defaults(func=cmd_local_send)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
