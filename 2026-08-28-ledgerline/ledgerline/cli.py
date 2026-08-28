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


def _load_or_create_wallet(path_str: str) -> Wallet:
    path = Path(path_str)
    if path.exists():
        try:
            wallet = Wallet.load(path)
        except (ValueError, KeyError, OSError) as exc:
            print(f"error: {path} doesn't look like a valid wallet file ({exc})", file=sys.stderr)
            raise SystemExit(1)
        print(f"loaded existing wallet from {path}: {wallet.address}")
    else:
        wallet = Wallet()
        wallet.save(path)
        print(f"created new wallet, saved to {path}: {wallet.address}")
    return wallet


def _validate_network_args(args: argparse.Namespace) -> None:
    """Fail with one clear message instead of a confusing hang (--nodes 0)
    or a raw traceback (`negative shift count` from a negative --bits)."""
    if args.nodes < 1:
        raise SystemExit("error: --nodes must be at least 1")
    if not (1 <= args.bits <= 63):
        raise SystemExit("error: --bits must be between 1 and 63")
    if args.port < 1 or args.port > 65535 - args.nodes:
        raise SystemExit(f"error: --port must leave room for {args.nodes} consecutive ports below 65536")


def cmd_network(args: argparse.Namespace) -> int:
    _validate_network_args(args)
    if args.seconds < 1:
        raise SystemExit("error: --seconds must be at least 1")

    def log(msg):
        print(msg)

    premine_wallet = _load_or_create_wallet(args.wallet) if args.wallet else None
    nodes, premine_wallet = create_network(
        args.nodes, base_port=args.port, genesis_bits=args.bits, mine=True,
        premine_wallet=premine_wallet, retarget_enabled=args.retarget, log=log,
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
    _validate_network_args(args)
    if not (1 <= args.http_port <= 65535):
        raise SystemExit("error: --http-port must be between 1 and 65535")

    def log(msg):
        print(msg)

    premine_wallet = _load_or_create_wallet(args.wallet) if args.wallet else None
    nodes, premine_wallet = create_network(
        args.nodes, base_port=args.port, genesis_bits=args.bits, mine=True,
        premine_wallet=premine_wallet, retarget_enabled=args.retarget, log=log,
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
    net.add_argument("--nodes", type=int, default=4, help="number of mining nodes to run (>=1)")
    net.add_argument("--port", type=int, default=18500, help="base TCP port; node i listens on port+i")
    net.add_argument("--bits", type=int, default=18, help="PoW difficulty (leading zero bits, 1-63)")
    net.add_argument("--seconds", type=int, default=30, help="how long to run before stopping")
    net.add_argument("--wallet", help="load/save node0's (premine) wallet from this JSON file, "
                                       "so its address stays the same across runs")
    net.add_argument("--retarget", action="store_true",
                      help="enable Bitcoin-style difficulty retargeting (off by default: fixed difficulty)")
    net.set_defaults(func=cmd_network)

    exp = sub.add_parser("explorer", help="run a multi-node network + the live web explorer")
    exp.add_argument("--nodes", type=int, default=4, help="number of mining nodes to run (>=1)")
    exp.add_argument("--port", type=int, default=18500, help="base TCP port; node i listens on port+i")
    exp.add_argument("--bits", type=int, default=18, help="PoW difficulty (leading zero bits, 1-63)")
    exp.add_argument("--http-port", type=int, default=8765, help="port to serve the web explorer on")
    exp.add_argument("--wallet", help="load/save node0's (premine) wallet from this JSON file, "
                                       "so its address stays the same across runs")
    exp.add_argument("--retarget", action="store_true",
                      help="enable Bitcoin-style difficulty retargeting (off by default: fixed difficulty)")
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
