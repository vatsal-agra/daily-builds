#!/usr/bin/env python3
"""Nonce CLI — mine, transact, and run multi-node network scenarios from
the command line."""

import argparse
import sys

from .wallet import Wallet
from .core.blockchain import Blockchain, create_genesis, subsidy_at
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

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
