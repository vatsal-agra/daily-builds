#!/usr/bin/env python3
"""The `vein` command-line tool: run a node, manage a wallet, mine, and
run the built-in demos."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

from .core.chain import ChainParams
from .core.block import target_to_bits, MAX_TARGET
from .node.server import VeinNode
from .wallet.wallet import Wallet, InsufficientFunds
from .crypto.address import pubkey_hash_from_address, is_valid_address
from .core.transaction import TxOut
from .core.script import Script

DEFAULT_PARAMS = ChainParams(
    initial_bits=target_to_bits(MAX_TARGET >> 12),
    retarget_interval=8,
    target_block_time=3.0,
    halving_interval=64,
)


def _rpc_get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def _rpc_post(base: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base}{path}", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(f"RPC error {e.code}: {body}")


# -- node -----------------------------------------------------------------

def cmd_node_start(args: argparse.Namespace) -> None:
    if args.miner_address:
        pkh = pubkey_hash_from_address(args.miner_address)
    else:
        w = Wallet.generate()
        pkh = w.pubkey_hash
        print(f"[vein] generated ephemeral miner address: {w.address}", file=sys.stderr)

    node = VeinNode(DEFAULT_PARAMS, args.p2p_host, args.p2p_port, args.rpc_host, args.rpc_port,
                     pkh, node_name=args.name)
    node.start(mine=args.mine)
    print(f"[vein] node '{args.name}' up — p2p {args.p2p_host}:{args.p2p_port}, "
          f"rpc http://{args.rpc_host}:{args.rpc_port}", file=sys.stderr)

    for peer in args.connect or []:
        host, port = peer.split(":")
        node.p2p.connect(host, int(port))
        print(f"[vein] connecting to {peer}", file=sys.stderr)

    try:
        while True:
            time.sleep(5)
            c = node.chain
            print(f"[vein:{args.name}] height={c.height} tip={c.tip_hash.hex()[:12]} "
                  f"peers={len(node.p2p.peers)} mempool={len(node.mempool)} "
                  f"hashrate={node.miner.stats.last_hashrate:.0f}h/s", file=sys.stderr)
    except KeyboardInterrupt:
        print("[vein] shutting down", file=sys.stderr)
        node.stop()


# -- wallet -----------------------------------------------------------------

def cmd_wallet_new(args: argparse.Namespace) -> None:
    w = Wallet.generate()
    w.save(args.out)
    print(f"address: {w.address}")
    print(f"saved to: {args.out}")


def cmd_wallet_address(args: argparse.Namespace) -> None:
    w = Wallet.load(args.wallet)
    print(w.address)


def cmd_wallet_balance(args: argparse.Namespace) -> None:
    w = Wallet.load(args.wallet)
    result = _rpc_get(args.rpc, f"/balance?address={w.address}")
    print(f"{w.address}: {result['balance']} sats ({result['balance'] / 1e8:.8f} VEIN)")


def cmd_wallet_send(args: argparse.Namespace) -> None:
    w = Wallet.load(args.wallet)
    if not is_valid_address(args.to):
        print(f"error: {args.to!r} is not a valid Vein address", file=sys.stderr)
        sys.exit(1)
    to_pkh = pubkey_hash_from_address(args.to)
    utxo_resp = _rpc_get(args.rpc, f"/utxos?address={w.address}")
    utxos = [((bytes.fromhex(u["txid"]), u["index"]), TxOut(u["value"], Script.p2pkh_lock(w.pubkey_hash)))
             for u in utxo_resp["utxos"]]
    try:
        tx = w.build_transaction(utxos, to_pkh, args.amount, args.fee)
    except InsufficientFunds as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    result = _rpc_post(args.rpc, "/submit_tx", {"tx": tx.serialize().hex()})
    if not result.get("accepted"):
        print(f"rejected: {result.get('error')}", file=sys.stderr)
        sys.exit(1)
    print(f"sent {args.amount} sats to {args.to}")
    print(f"txid: {result['txid']}")


# -- status -----------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> None:
    print(json.dumps(_rpc_get(args.rpc, "/status"), indent=2))


def cmd_chain(args: argparse.Namespace) -> None:
    print(json.dumps(_rpc_get(args.rpc, f"/chain?limit={args.limit}"), indent=2))


# -- demos --------------------------------------------------------------

def cmd_demo(args: argparse.Namespace) -> None:
    from .demos.core_demo import run_core_demo
    run_core_demo()


def cmd_partition_demo(args: argparse.Namespace) -> None:
    from .demos.partition_demo import run_partition_demo
    run_partition_demo()


def cmd_explorer(args: argparse.Namespace) -> None:
    import os
    explorer_path = os.path.join(os.path.dirname(__file__), "explorer", "explorer.html")
    with open(explorer_path) as f:
        html = f.read()
    html = html.replace("__DEFAULT_RPC__", args.rpc)
    out_path = args.out or "vein_explorer.html"
    with open(out_path, "w") as f:
        f.write(html)
    print(f"wrote {out_path} — open it in a browser (node RPC must be reachable at {args.rpc})")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vein", description="A from-scratch proof-of-work blockchain.")
    sub = p.add_subparsers(dest="command", required=True)

    node = sub.add_parser("node", help="run a Vein node")
    node_sub = node.add_subparsers(dest="node_command", required=True)
    start = node_sub.add_parser("start", help="start a node process")
    start.add_argument("--name", default="node")
    start.add_argument("--p2p-host", default="127.0.0.1")
    start.add_argument("--p2p-port", type=int, required=True)
    start.add_argument("--rpc-host", default="127.0.0.1")
    start.add_argument("--rpc-port", type=int, required=True)
    start.add_argument("--connect", action="append", help="host:port of a peer to dial, repeatable")
    start.add_argument("--mine", action="store_true")
    start.add_argument("--miner-address", help="Vein address to receive mining rewards")
    start.set_defaults(func=cmd_node_start)

    wallet = sub.add_parser("wallet", help="manage a Vein wallet")
    wallet_sub = wallet.add_subparsers(dest="wallet_command", required=True)

    w_new = wallet_sub.add_parser("new")
    w_new.add_argument("--out", default="wallet.json")
    w_new.set_defaults(func=cmd_wallet_new)

    w_addr = wallet_sub.add_parser("address")
    w_addr.add_argument("--wallet", default="wallet.json")
    w_addr.set_defaults(func=cmd_wallet_address)

    w_bal = wallet_sub.add_parser("balance")
    w_bal.add_argument("--wallet", default="wallet.json")
    w_bal.add_argument("--rpc", default="http://127.0.0.1:18332")
    w_bal.set_defaults(func=cmd_wallet_balance)

    w_send = wallet_sub.add_parser("send")
    w_send.add_argument("--wallet", default="wallet.json")
    w_send.add_argument("--rpc", default="http://127.0.0.1:18332")
    w_send.add_argument("--to", required=True)
    w_send.add_argument("--amount", type=int, required=True)
    w_send.add_argument("--fee", type=int, default=1000)
    w_send.set_defaults(func=cmd_wallet_send)

    status = sub.add_parser("status", help="query a node's status over RPC")
    status.add_argument("--rpc", default="http://127.0.0.1:18332")
    status.set_defaults(func=cmd_status)

    chain = sub.add_parser("chain", help="print the active chain from a node")
    chain.add_argument("--rpc", default="http://127.0.0.1:18332")
    chain.add_argument("--limit", type=int, default=20)
    chain.set_defaults(func=cmd_chain)

    demo = sub.add_parser("demo", help="single-process walkthrough of crypto/UTXO/mining")
    demo.set_defaults(func=cmd_demo)

    pdemo = sub.add_parser("partition-demo", help="multi-node network-partition + reorg demo")
    pdemo.set_defaults(func=cmd_partition_demo)

    explorer = sub.add_parser("explorer", help="write out the block explorer HTML pointed at a node")
    explorer.add_argument("--rpc", default="http://127.0.0.1:18332")
    explorer.add_argument("--out", default=None)
    explorer.set_defaults(func=cmd_explorer)

    return p


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
