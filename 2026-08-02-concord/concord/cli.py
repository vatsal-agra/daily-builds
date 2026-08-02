import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from . import pow as powmod
from .block import Block
from .chain import Blockchain
from .explorer import ExplorerServer
from .mempool import Mempool
from .miner import Miner
from .node import Node
from .transaction import TxOutput
from .wallet import InsufficientFunds, Wallet


def _api_get(api, path):
    with urllib.request.urlopen(f"{api}{path}", timeout=10) as resp:
        return json.loads(resp.read())


def _api_post(api, path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{api}{path}", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def cmd_wallet_new(args):
    w = Wallet()
    w.save(args.out)
    print(f"created wallet at {args.out}")
    print(f"address: {w.address}")


def cmd_wallet_address(args):
    try:
        w = Wallet.load(args.wallet)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"error: could not load wallet {args.wallet!r}: {e}", file=sys.stderr)
        sys.exit(1)
    print(w.address)


def cmd_wallet_balance(args):
    try:
        w = Wallet.load(args.wallet)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"error: could not load wallet {args.wallet!r}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        info = _api_get(args.api, f"/api/utxo/{w.address}")
    except (urllib.error.URLError, ConnectionError) as e:
        print(f"error: could not reach node at {args.api}: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"address: {w.address}")
    print(f"balance: {info['balance']}")
    print(f"utxos:   {len(info['utxos'])}")


def cmd_genesis_create(args):
    from .curve import is_valid_address
    if not is_valid_address(args.address):
        print(f"error: {args.address!r} is not a valid Concord address", file=sys.stderr)
        sys.exit(1)
    if args.amount <= 0:
        print("error: --amount must be positive", file=sys.stderr)
        sys.exit(1)
    genesis = Block.genesis(args.address, powmod.GENESIS_TARGET, amount=args.amount)
    with open(args.out, "w") as f:
        json.dump(genesis.to_dict(), f, indent=2)
    print(f"genesis written to {args.out}")
    print(f"genesis hash: {genesis.hash()}")
    print(f"premine {args.amount} -> {args.address}")


def _load_genesis(path):
    with open(path) as f:
        return Block.from_dict(json.load(f))


def cmd_node(args):
    try:
        genesis = _load_genesis(args.genesis)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"error: could not load genesis file {args.genesis!r}: {e}", file=sys.stderr)
        print("hint: create one with 'concord genesis-create --address <addr> --out genesis.json'",
              file=sys.stderr)
        sys.exit(1)
    chain = Blockchain(genesis)
    mempool = Mempool()
    node = Node(args.host, args.p2p_port, chain, mempool, name=args.name or f"node-{args.p2p_port}")
    node.on_event = lambda msg: print(f"[{node.name}] {msg}")
    node.start()

    for peer in args.peer or []:
        host, port = peer.split(":")
        try:
            node.connect(host, int(port))
        except OSError as e:
            print(f"[{node.name}] could not connect to {peer}: {e}")

    explorer = ExplorerServer(node, host=args.host, port=args.api_port)
    explorer.start()
    print(f"[{node.name}] P2P on {args.host}:{args.p2p_port}, API/explorer on http://{args.host}:{explorer.port}")

    miner = None
    if args.mine:
        wallet = Wallet.load_or_create(args.wallet)
        print(f"[{node.name}] mining to {wallet.address}")
        miner = Miner(node, wallet.address)
        miner.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if miner:
            miner.stop()
        node.stop()
        explorer.stop()


def cmd_send(args):
    try:
        wallet = Wallet.load(args.wallet)
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"error: could not load wallet {args.wallet!r}: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        info = _api_get(args.api, f"/api/utxo/{wallet.address}")
    except (urllib.error.URLError, ConnectionError) as e:
        print(f"error: could not reach node at {args.api}: {e}", file=sys.stderr)
        sys.exit(1)
    utxo = {(u["txid"], u["index"]): TxOutput(u["amount"], wallet.address) for u in info["utxos"]}
    try:
        tx = wallet.build_transaction(utxo, args.to, args.amount, fee=args.fee)
    except (InsufficientFunds, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    result = _api_post(args.api, "/api/submit_tx", tx.to_dict())
    if result.get("accepted"):
        print(f"sent: txid {result['txid']}")
    else:
        print(f"rejected: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


def cmd_demo(args):
    from . import demo
    demo.run_demo()


def cmd_attack(args):
    from . import attack_demo
    attack_demo.run_attack_demo()


def build_parser():
    p = argparse.ArgumentParser(prog="concord", description="A from-scratch blockchain and cryptocurrency.")
    sub = p.add_subparsers(dest="command", required=True)

    w = sub.add_parser("wallet-new", help="create a new wallet")
    w.add_argument("--out", default="wallet.json")
    w.set_defaults(func=cmd_wallet_new)

    wa = sub.add_parser("wallet-address", help="print a wallet's address")
    wa.add_argument("--wallet", default="wallet.json")
    wa.set_defaults(func=cmd_wallet_address)

    wb = sub.add_parser("wallet-balance", help="query a wallet's balance from a running node")
    wb.add_argument("--wallet", default="wallet.json")
    wb.add_argument("--api", default="http://127.0.0.1:8000")
    wb.set_defaults(func=cmd_wallet_balance)

    g = sub.add_parser("genesis-create", help="create a genesis block")
    g.add_argument("--address", required=True)
    g.add_argument("--amount", type=int, default=1000)
    g.add_argument("--out", default="genesis.json")
    g.set_defaults(func=cmd_genesis_create)

    n = sub.add_parser("node", help="run a P2P node with a JSON API / explorer")
    n.add_argument("--genesis", default="genesis.json")
    n.add_argument("--host", default="127.0.0.1")
    n.add_argument("--p2p-port", type=int, required=True)
    n.add_argument("--api-port", type=int, required=True)
    n.add_argument("--peer", action="append", help="host:port of a peer to connect to (repeatable)")
    n.add_argument("--mine", action="store_true")
    n.add_argument("--wallet", default="wallet.json", help="mining reward wallet")
    n.add_argument("--name", default=None)
    n.set_defaults(func=cmd_node)

    s = sub.add_parser("send", help="build, sign, and submit a transaction to a running node")
    s.add_argument("--api", default="http://127.0.0.1:8000")
    s.add_argument("--wallet", default="wallet.json")
    s.add_argument("--to", required=True)
    s.add_argument("--amount", type=int, required=True)
    s.add_argument("--fee", type=int, default=0)
    s.set_defaults(func=cmd_send)

    d = sub.add_parser("demo", help="run a full end-to-end in-process network demo")
    d.set_defaults(func=cmd_demo)

    a = sub.add_parser("attack", help="run the double-spend / fork attack simulation")
    a.set_defaults(func=cmd_attack)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
