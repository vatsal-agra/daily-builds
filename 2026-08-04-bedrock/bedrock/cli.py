"""The `bedrock` command-line entry point. Chain/mempool/wallet state
persists to a JSON file between invocations (a list of raw mined blocks
replayed — and thus fully re-validated — on every load, plus WIF-encoded
wallet private keys)."""

import argparse
import json
import os
import sys
import time
from decimal import Decimal, InvalidOperation

from bedrock.block import Block
from bedrock.chain import COIN, ChainError, block_subsidy
from bedrock.crypto import is_valid_address
from bedrock.mempool import MempoolError
from bedrock.network import NetworkNode, wait_until_converged
from bedrock.node import Node
from bedrock.transaction import Transaction
from bedrock.wallet import Wallet, WalletError

DEFAULT_DATA_PATH = "bedrock_data.json"


def save_state(path: str, node: Node, wallets: dict) -> None:
    data = {
        "blocks": [
            node.chain.get_block(h).to_bytes().hex()
            for h in node.chain.path_from_genesis(node.chain.tip_hash)
        ],
        "mempool": [tx.to_bytes().hex() for tx in node.mempool.select_for_block(node.chain)],
        "wallets": {addr: w.to_wif() for addr, w in wallets.items()},
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def load_state(path: str):
    with open(path) as fh:
        data = json.load(fh)
    if not data.get("blocks"):
        raise ValueError("state file has no genesis block")
    blocks = [Block.from_wire_hex(h) for h in data["blocks"]]
    node = Node(genesis_block=blocks[0])
    for block in blocks[1:]:
        status = node.chain.add_block(block)
        if status not in ("best_chain",):
            raise ChainError(f"persisted chain is not a single valid best-chain path (got status={status})")
    for tx_hex in data.get("mempool", []):
        tx, _ = Transaction.from_bytes(bytes.fromhex(tx_hex))
        try:
            node.mempool.add_transaction(tx, node.chain)
        except (ChainError, MempoolError):
            pass  # no longer valid (e.g. depended on since-reorganized state); drop silently
    wallets = {addr: Wallet.from_wif(wif) for addr, wif in data.get("wallets", {}).items()}
    return node, wallets


def load_or_new(path: str):
    if os.path.exists(path):
        return load_state(path)
    return Node(), {}


def fmt_coin(shards: int) -> str:
    return f"{shards / COIN:.8f}"


def parse_coin(s: str) -> int:
    """Parses a decimal coin-amount string into integer shards without
    going through `float` — float64 can't exactly represent most decimal
    fractions, and silently rounding a user's requested amount by even one
    shard is exactly the kind of "close enough" bug a currency shouldn't
    have."""
    try:
        shards = Decimal(s) * COIN
    except InvalidOperation:
        raise ValueError(f"'{s}' is not a valid decimal amount")
    if shards != shards.to_integral_value():
        raise ValueError(f"'{s}' specifies more precision than Bedrock's {len(str(COIN)) - 1} decimal places support")
    return int(shards)


# -- subcommands --------------------------------------------------------------

def cmd_keygen(args):
    node, wallets = load_or_new(args.data)
    wallet = Wallet.generate()
    wallets[wallet.address] = wallet
    save_state(args.data, node, wallets)
    print(f"address:     {wallet.address}")
    print(f"private key: {wallet.to_wif()}")


def cmd_balance(args):
    node, wallets = load_or_new(args.data)
    if not is_valid_address(args.address):
        print(f"error: '{args.address}' is not a valid Bedrock address", file=sys.stderr)
        sys.exit(1)
    print(fmt_coin(node.balance(args.address)))


def cmd_send(args):
    node, wallets = load_or_new(args.data)
    if args.from_address not in wallets:
        print(f"error: no local wallet for {args.from_address} (run 'bedrock keygen' first)", file=sys.stderr)
        sys.exit(1)
    if not is_valid_address(args.to_address):
        print(f"error: '{args.to_address}' is not a valid Bedrock address", file=sys.stderr)
        sys.exit(1)
    wallet = wallets[args.from_address]
    try:
        amount = parse_coin(args.amount)
        fee = parse_coin(args.fee)
        tx = wallet.send(node.chain, node.mempool, args.to_address, amount, fee=fee)
    except (ValueError, WalletError, ChainError, MempoolError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    save_state(args.data, node, wallets)
    print(f"broadcast txid: {tx.txid}")


def cmd_mine(args):
    node, wallets = load_or_new(args.data)
    if not is_valid_address(args.address):
        print(f"error: '{args.address}' is not a valid Bedrock address", file=sys.stderr)
        sys.exit(1)
    t0 = time.time()
    try:
        block, status = node.mine_block(args.address, max_nonce=args.max_nonce)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    save_state(args.data, node, wallets)
    print(f"mined block {block.hash} at height {node.chain.height} ({status}) in {time.time()-t0:.2f}s")


def cmd_chain(args):
    node, wallets = load_or_new(args.data)
    print(f"height: {node.chain.height}")
    print(f"tip:    {node.chain.tip_hash}")
    print(f"utxos:  {len(node.chain.utxo_set)}")
    print(f"mempool: {len(node.mempool)}")
    print()
    n = min(args.limit, node.chain.height + 1)
    for h in range(node.chain.height, node.chain.height - n, -1):
        block = node.chain.block_at_height(h)
        reward = block.transactions[0].total_output_value()
        print(f"  [{h:>4}] {block.hash}  txs={len(block.transactions):<3} reward={fmt_coin(reward)}")


def cmd_validate(args):
    try:
        node, wallets = load_state(args.data)
    except FileNotFoundError:
        print(f"error: no state file at {args.data}", file=sys.stderr)
        sys.exit(1)
    except (ChainError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"VALID: {node.chain.height + 1} blocks re-validated from genesis, tip={node.chain.tip_hash}")


def cmd_serve(args):
    from bedrock import explorer
    # `wallets` (CLI-created, from --data) is intentionally unused here: the
    # explorer manages its own separate, in-memory wallet set created via its
    # "+ New wallet" button, not the CLI's persisted ones. Documented in the
    # README as a known seam between the two UIs, not silently glossed over.
    node, _cli_wallets = load_or_new(args.data)

    net = None
    if args.listen or args.peer:
        net = NetworkNode(node, host=args.host, port=args.p2p_port, log=lambda m: print(f"[p2p] {m}"))
        net.start()
        print(f"p2p listening on {args.host}:{net.port}")
        for peer in args.peer or []:
            host, _, port = peer.partition(":")
            net.connect(host, int(port))
            print(f"connected to peer {peer}")

    httpd = explorer.serve(node, network=net, host=args.host, port=args.port)
    print(f"bedrock explorer: http://{args.host}:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if net:
            net.stop()


def cmd_netnode(args):
    node, wallets = load_or_new(args.data)
    net = NetworkNode(node, host=args.host, port=args.port, log=lambda m: print(f"[{args.host}:{args.port}] {m}"))
    net.start()
    print(f"netnode listening on {args.host}:{net.port}")
    for peer in args.peer or []:
        host, _, port = peer.partition(":")
        net.connect(host, int(port))
        print(f"connected to {peer}")

    miner_wallet = args.miner_address
    try:
        while True:
            time.sleep(args.mine_interval)
            if miner_wallet:
                # Mining mutates node.chain/node.mempool, exactly like the
                # gossip-message handlers running concurrently on peer
                # threads — both MUST go through the same lock net owns, or
                # the two can interleave their mutations and corrupt state.
                with net.lock:
                    block, status = node.mine_block(miner_wallet, max_nonce=50_000_000)
                    net.announce_block(block)
                print(f"mined height={node.chain.height} status={status}")
    except KeyboardInterrupt:
        pass
    finally:
        net.stop()


def cmd_demo(args):
    from bedrock import demo
    demo.run()


def build_parser():
    p = argparse.ArgumentParser(prog="bedrock", description="A from-scratch proof-of-work blockchain.")
    p.add_argument("--data", default=DEFAULT_DATA_PATH, help="state file path (default: %(default)s)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("keygen", help="generate a new wallet").set_defaults(func=cmd_keygen)

    sp = sub.add_parser("balance", help="show an address's balance")
    sp.add_argument("address")
    sp.set_defaults(func=cmd_balance)

    sp = sub.add_parser("send", help="build, sign, and broadcast a transaction")
    sp.add_argument("from_address")
    sp.add_argument("to_address")
    sp.add_argument("amount", help="amount in whole coins, e.g. 1.5")
    sp.add_argument("--fee", default="0.00001")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("mine", help="mine one block")
    sp.add_argument("address", help="reward address")
    sp.add_argument("--max-nonce", type=int, default=None)
    sp.set_defaults(func=cmd_mine)

    sp = sub.add_parser("chain", help="show chain summary")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(func=cmd_chain)

    sub.add_parser("validate", help="re-validate the entire persisted chain from genesis").set_defaults(func=cmd_validate)

    sp = sub.add_parser("serve", help="run the block explorer + wallet web UI")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8420)
    sp.add_argument("--p2p-port", type=int, default=0)
    sp.add_argument("--listen", action="store_true", help="also start a P2P server even with no --peer")
    sp.add_argument("--peer", action="append", help="host:port of a peer to connect to (repeatable)")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("netnode", help="run a headless P2P node (no web UI)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=0)
    sp.add_argument("--peer", action="append", help="host:port of a peer to connect to (repeatable)")
    sp.add_argument("--miner-address", default=None, help="if set, mines automatically every --mine-interval seconds")
    sp.add_argument("--mine-interval", type=float, default=3.0)
    sp.set_defaults(func=cmd_netnode)

    sub.add_parser("demo", help="run the full feature walkthrough").set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
