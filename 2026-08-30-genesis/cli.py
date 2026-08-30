#!/usr/bin/env python3
"""Genesis: a from-scratch blockchain -- wallet CLI.

A genuinely usable single-node wallet backed by on-disk persistence (so
`send` in one command and `mine` in the next actually see each other's
effects, the way a real wallet CLI has to work across separate process
invocations). For the multi-node consensus/fork-resolution demonstration
(this project's core subject), see `python3 cli.py demo` or `demo.sh`, and
`python3 cli.py serve` for the live 3-node block explorer.

Usage:
  python3 cli.py init                       create/open the local wallet + chain
  python3 cli.py address                    print this wallet's address
  python3 cli.py balance                    print this wallet's confirmed balance
  python3 cli.py status                     print chain height/tip/difficulty/mempool
  python3 cli.py mine [count]               mine `count` blocks (default 1)
  python3 cli.py send <address> <coins> [--fee sats]   sign+queue a payment
  python3 cli.py history                    list this wallet's UTXOs
  python3 cli.py serve [port] [host]        run the live multi-node block explorer
  python3 cli.py demo                       run a full scripted end-to-end demonstration
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import blockchain as bc
import crypto as c
import persistence as ps
import transaction as tx

DATA_DIR = os.environ.get(
    "GENESIS_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
)
COIN = 100_000_000  # 1 coin == 1e8 sats, same denomination convention as Bitcoin


def fmt_coins(sats: int) -> str:
    return f"{sats / COIN:.8f}"


def cmd_init(data_dir: str) -> None:
    chain = ps.load_or_init_chain(data_dir)
    wallet = ps.load_or_init_wallet(data_dir)
    print(f"chain ready at height {chain.height()} (tip {chain.tip.hex()[:16]}...)")
    print(f"wallet address: {wallet.address}")


def cmd_address(data_dir: str) -> None:
    wallet = ps.load_or_init_wallet(data_dir)
    print(wallet.address)


def cmd_balance(data_dir: str) -> None:
    chain = ps.load_or_init_chain(data_dir)
    wallet = ps.load_or_init_wallet(data_dir)
    bal = wallet.balance(chain.utxo_set())
    print(f"{fmt_coins(bal)} coins ({bal} sats) confirmed")


def cmd_status(data_dir: str) -> None:
    chain = ps.load_or_init_chain(data_dir)
    mempool, dropped = ps.load_mempool(data_dir, chain)
    print(f"height:          {chain.height()}")
    print(f"tip:             {chain.tip.hex()}")
    print(f"cumulative work: {chain.work[chain.tip]}")
    print(f"next target:     {chain.next_expected_target():#x}")
    print(f"mempool:         {len(mempool)} pending tx(s)")
    if dropped:
        print(f"  (dropped {len(dropped)} stale pending tx(s) that no longer validate:)")
        for txid, reason in dropped:
            print(f"    {txid}: {reason}")


def cmd_history(data_dir: str) -> None:
    chain = ps.load_or_init_chain(data_dir)
    wallet = ps.load_or_init_wallet(data_dir)
    utxos = wallet.utxos(chain.utxo_set())
    if not utxos:
        print("no unspent outputs")
        return
    for e in utxos:
        print(f"{e.txid.hex()[:16]}...:{e.index}  {fmt_coins(e.output.amount)} coins")


def cmd_send(data_dir: str, to_address: str, amount_coins: str, fee_sats: int) -> None:
    chain = ps.load_or_init_chain(data_dir)
    wallet = ps.load_or_init_wallet(data_dir)
    mempool, _dropped = ps.load_mempool(data_dir, chain)
    try:
        amount = int(round(float(amount_coins) * COIN))
    except ValueError:
        print(f"error: '{amount_coins}' is not a valid coin amount", file=sys.stderr)
        sys.exit(1)
    try:
        c.address_to_pubkey_hash(to_address)
    except ValueError as e:
        print(f"error: invalid destination address: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        t = wallet.create_transaction(chain.utxo_set(), to_address, amount, fee_sats)
    except Exception as e:  # noqa: BLE001 - insufficient funds / bad amount, reported cleanly
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    ok, reason = mempool.add_transaction(t, lambda txid, idx: chain.utxo_set().get((txid, idx)))
    if not ok:
        print(f"error: transaction rejected: {reason}", file=sys.stderr)
        sys.exit(1)
    ps.save_mempool(data_dir, mempool)
    print(f"queued tx {t.txid_hex()} : {fmt_coins(amount)} coins -> {to_address} (fee {fee_sats} sats)")
    print("run `python3 cli.py mine` to confirm it")


def cmd_mine(data_dir: str, count: int) -> None:
    chain = ps.load_or_init_chain(data_dir)
    wallet = ps.load_or_init_wallet(data_dir)
    mempool, _dropped = ps.load_mempool(data_dir, chain)
    import time
    from block import Block
    last_ts = chain.blocks[chain.tip].header.timestamp
    for i in range(count):
        height = chain.height() + 1
        target = chain.next_expected_target()
        utxo = chain.utxo_set()
        lookup = lambda txid, idx: utxo.get((txid, idx))
        txs = mempool.select_for_block(lookup)
        total_fees = sum(t.fee(lookup) for t in txs)
        coinbase = tx.Transaction.coinbase(wallet.pubkey_hash, bc.subsidy_at(height) + total_fees, height)
        ts = max(int(time.time()), last_ts + 1)
        last_ts = ts
        block = Block.new(prev_hash=chain.tip, transactions=[coinbase] + txs, target=target, timestamp=ts)
        nonce = block.mine()
        result = chain.accept_block(block, now=ts)
        if not result.accepted:
            print(f"error: mined block rejected by our own chain: {result.reason}", file=sys.stderr)
            sys.exit(1)
        ps.append_block(data_dir, block)
        mempool.remove_confirmed(block.transactions)
        reward = coinbase.total_output()
        print(f"mined block #{height} {block.block_hash_hex()[:16]}... "
              f"(nonce {nonce}, {len(txs)} tx, reward {fmt_coins(reward)} coins)")
    ps.save_mempool(data_dir, mempool)


def cmd_serve(port: int, host: str) -> None:
    import server
    server.serve(port=port, host=host)


def cmd_demo() -> None:
    import demo
    demo.run()


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    command, rest = argv[0], argv[1:]
    if command not in ("serve", "demo"):
        os.makedirs(DATA_DIR, exist_ok=True)
    if command == "init":
        cmd_init(DATA_DIR)
    elif command == "address":
        cmd_address(DATA_DIR)
    elif command == "balance":
        cmd_balance(DATA_DIR)
    elif command == "status":
        cmd_status(DATA_DIR)
    elif command == "history":
        cmd_history(DATA_DIR)
    elif command == "mine":
        count = int(rest[0]) if rest else 1
        cmd_mine(DATA_DIR, count)
    elif command == "send":
        if len(rest) < 2:
            print("usage: cli.py send <address> <coins> [--fee sats]", file=sys.stderr)
            return 1
        fee = 1000
        if "--fee" in rest:
            idx = rest.index("--fee")
            fee = int(rest[idx + 1])
            rest = rest[:idx] + rest[idx + 2:]
        cmd_send(DATA_DIR, rest[0], rest[1], fee)
    elif command == "serve":
        port = int(rest[0]) if len(rest) > 0 else 8765
        host = rest[1] if len(rest) > 1 else "127.0.0.1"
        cmd_serve(port, host)
    elif command == "demo":
        cmd_demo()
    else:
        print(f"unknown command: {command}\n")
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
