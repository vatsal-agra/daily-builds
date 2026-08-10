#!/usr/bin/env python3
"""Differential fuzz-testing harness (stretch feature #5).

Throws thousands of randomized order/cancel sequences at the real engine
(`book.OrderBook`) and the deliberately naive reference matcher
(`oracle.NaiveOrderBook`) side by side, feeding both *exactly* the same
operations (same explicit order ids, so cancels target the same logical
order in each), and asserts after every single operation that:

  1. the trades produced by that operation are identical, in order
     (price, qty, aggressor side, maker/taker owner) — proves price-time
     priority is implemented correctly, not just "produces plausible
     trades";
  2. best_bid()/best_ask() agree;
  3. the full depth ladder (all price levels, not just the top) agrees.

Any disagreement means the real engine has a bug, independent of whether
its output "looks right" in isolation — the same differential-testing
instinct this repo has used before (a VCS diffed against real git, SAT
solutions independently proof-checked).

Usage: python3 fuzz.py [--trials N] [--ops-per-trial N] [--seed N]
Exit code 0 = every trial matched exactly. Non-zero = a mismatch was found
(details printed).
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from order import Side, OrderType, reset_id_counter
from book import OrderBook, RejectedOrder
from oracle import NaiveOrderBook


OWNERS = ["alice", "bob", "carol"]  # small set -> frequent self-trade-prevention exercising
OTYPES = [OrderType.LIMIT, OrderType.LIMIT, OrderType.LIMIT, OrderType.MARKET, OrderType.IOC, OrderType.FOK]


def trade_key(tr):
    return (tr.price, tr.qty, tr.aggressor_side.value, tr.maker_owner, tr.taker_owner)


def run_trial(n_ops, seed):
    rng = random.Random(seed)
    real = OrderBook("FUZZ")
    naive = NaiveOrderBook("FUZZ")
    open_ids = []
    next_id = [1]

    for op_i in range(n_ops):
        if open_ids and rng.random() < 0.20:
            oid = rng.choice(open_ids)
            r1 = real.cancel(oid)
            r2 = naive.cancel(oid)
            if r1 != r2:
                return f"op {op_i}: cancel({oid}) mismatch real={r1} naive={r2}"
            if r1:
                open_ids.remove(oid)
            continue

        side = rng.choice([Side.BUY, Side.SELL])
        otype = rng.choice(OTYPES)
        qty = rng.randint(1, 12)
        price = None
        if otype in (OrderType.LIMIT,) or (otype in (OrderType.IOC, OrderType.FOK) and rng.random() < 0.6):
            price = rng.randint(9900, 10100)
        owner = rng.choice(OWNERS)
        oid = next_id[0]
        next_id[0] += 1
        ts = op_i

        try:
            r_resting, r_trades = real.submit(side, otype, qty, price=price, owner=owner, order_id=oid, ts=ts)
        except RejectedOrder as e:
            r_resting, r_trades, r_err = None, None, str(e)
        else:
            r_err = None

        try:
            n_resting, n_trades = naive.submit(side, otype, qty, price=price, owner=owner, order_id=oid, ts=ts)
        except RejectedOrder as e:
            n_resting, n_trades, n_err = None, None, str(e)
        else:
            n_err = None

        if (r_err is None) != (n_err is None):
            return f"op {op_i}: rejection mismatch real_err={r_err!r} naive_err={n_err!r} (side={side}, otype={otype}, qty={qty}, price={price})"
        if r_err is not None:
            continue  # both rejected identically, nothing else to compare for this op

        r_keys = [trade_key(t) for t in r_trades]
        n_keys = [trade_key(t) for t in n_trades]
        if r_keys != n_keys:
            return f"op {op_i}: trade sequence mismatch\n  real ={r_keys}\n  naive={n_keys}"

        if (r_resting is not None) != (n_resting is not None):
            return f"op {op_i}: resting-order presence mismatch real={r_resting} naive={n_resting}"

        if real.best_bid() != naive.best_bid() or real.best_ask() != naive.best_ask():
            return (f"op {op_i}: best bid/ask mismatch "
                    f"real=({real.best_bid()},{real.best_ask()}) naive=({naive.best_bid()},{naive.best_ask()})")

        r_depth = real.depth(levels=999)
        n_depth = naive.depth(levels=999)
        if r_depth != n_depth:
            return f"op {op_i}: depth mismatch\n  real ={r_depth}\n  naive={n_depth}"

        if r_resting is not None:
            open_ids.append(oid)

    return None  # trial passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--ops-per-trial", type=int, default=150)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    failures = 0
    for trial in range(args.trials):
        reset_id_counter()
        failure = run_trial(args.ops_per_trial, seed=args.seed * 100_003 + trial)
        if failure:
            failures += 1
            print(f"TRIAL {trial} FAILED (seed={args.seed * 100_003 + trial}): {failure}")

    total_ops = args.trials * args.ops_per_trial
    if failures:
        print(f"\n{failures}/{args.trials} trials failed out of {total_ops} total randomized operations.")
        sys.exit(1)
    print(f"OK: {args.trials} trials x {args.ops_per_trial} ops = {total_ops} randomized operations, "
          f"real engine and naive reference matcher agreed on every single trade, book, and depth check.")


if __name__ == "__main__":
    main()
