"""`ledgerline` command-line entry point."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .explorer_server import run_explorer
from .network import create_network, start_all, stop_all
from .wallet import Wallet


def cmd_keygen(args: argparse.Namespace) -> int:
    wallet = Wallet()
    print(f"address:     {wallet.address}")
    print(f"private key: {hex(wallet.privkey)}")
    if args.out:
        wallet.save(Path(args.out))
        print(f"saved to {args.out}")
    return 0


def _print_status_table(nodes) -> None:
    rows = [n.status() for n in nodes]
    header = f"{'node':<8} {'height':>6} {'balance':>9} {'peers':>5} {'mempool':>8} {'mined':>6} {'reorgs':>6}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['name']:<8} {r['height']:>6} {r['balance']:>9} {len(r['peers']):>5} "
            f"{r['mempool_size']:>8} {r['blocks_mined']:>6} {r['reorg_count']:>6}"
        )


def cmd_network(args: argparse.Namespace) -> int:
    def log(msg):
        print(msg)

    nodes, premine_wallet = create_network(
        args.nodes, base_port=args.port, genesis_bits=args.bits, mine=True, log=log
    )
    print(f"premine wallet: {premine_wallet.address} (funded with {1_000_000})")
    start_all(nodes)
    try:
        end = time.time() + args.seconds
        while time.time() < end:
            time.sleep(2)
            _print_status_table(nodes)
            print()
    except KeyboardInterrupt:
        pass
    finally:
        stop_all(nodes)
    return 0


def cmd_explorer(args: argparse.Namespace) -> int:
    def log(msg):
        print(msg)

    nodes, premine_wallet = create_network(
        args.nodes, base_port=args.port, genesis_bits=args.bits, mine=True, log=log
    )
    print(f"premine wallet: {premine_wallet.address}")
    start_all(nodes)
    run_explorer(nodes, port=args.http_port, log_fn=log)
    print(f"explorer running at http://127.0.0.1:{args.http_port}  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all(nodes)
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from . import demo as demo_module
    return demo_module.run()


def cmd_test(args: argparse.Namespace) -> int:
    import subprocess
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root)
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ledgerline", description="A from-scratch PoW blockchain + P2P network.")
    sub = p.add_subparsers(dest="command", required=True)

    kg = sub.add_parser("keygen", help="generate a new wallet keypair")
    kg.add_argument("--out", help="save the wallet to this JSON file")
    kg.set_defaults(func=cmd_keygen)

    net = sub.add_parser("network", help="run a headless multi-node network in the terminal")
    net.add_argument("--nodes", type=int, default=4)
    net.add_argument("--port", type=int, default=18500)
    net.add_argument("--bits", type=int, default=18, help="PoW difficulty (leading zero bits)")
    net.add_argument("--seconds", type=int, default=30)
    net.set_defaults(func=cmd_network)

    exp = sub.add_parser("explorer", help="run a multi-node network + the live web explorer")
    exp.add_argument("--nodes", type=int, default=4)
    exp.add_argument("--port", type=int, default=18500)
    exp.add_argument("--bits", type=int, default=18)
    exp.add_argument("--http-port", type=int, default=8765)
    exp.set_defaults(func=cmd_explorer)

    demo = sub.add_parser("demo", help="scripted end-to-end walkthrough of every feature")
    demo.set_defaults(func=cmd_demo)

    test = sub.add_parser("test", help="run the unit test suite")
    test.set_defaults(func=cmd_test)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
