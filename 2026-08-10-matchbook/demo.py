#!/usr/bin/env python3
"""Runs a complete, deterministic Matchbook session end to end and writes
output/report.html — a self-contained, interactive replay of everything
the engine actually produced.

Usage:
    python3 demo.py                 # default: two correlated instruments, 3000 ticks
    python3 demo.py --ticks 5000 --seed 7 --out output/report.html
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from simulator import MarketSimulator
from agents import MarketMaker, NoiseTrader, MomentumTrader, MeanReversionTrader, StatArbTrader
from marketdata import build_candles, candles_to_dicts
from report_template import build_report


def run_session(n_ticks=3000, seed=42):
    symbols = ["ACME", "GLBX"]  # two correlated instruments, for the stat-arb agent
    sim = MarketSimulator(symbols, seed=seed)
    sim.seed_liquidity("ACME", mid=10000)
    sim.seed_liquidity("GLBX", mid=9800)

    sim.register(NoiseTrader("noise.acme.1", mid_guess=10000), "ACME")
    sim.register(NoiseTrader("noise.acme.2", mid_guess=10000, place_prob=0.40, band=90), "ACME")
    sim.register(NoiseTrader("noise.glbx.1", mid_guess=9800), "GLBX")
    sim.register(NoiseTrader("noise.glbx.2", mid_guess=9800, place_prob=0.40, band=90), "GLBX")
    sim.register(MarketMaker("mm.acme"), "ACME")
    sim.register(MarketMaker("mm.glbx", min_edge=7), "GLBX")
    sim.register(MomentumTrader("momentum.acme"), "ACME")
    sim.register(MeanReversionTrader("meanrev.acme"), "ACME")
    sim.register(MomentumTrader("momentum.glbx", short_n=6, long_n=22), "GLBX")
    sim.register(StatArbTrader("statarb.pair"), "ACME")  # primary=ACME, sees GLBX too

    sim.run(n_ticks)
    return sim, symbols


def to_session_json(sim, symbols, bar_ticks=15):
    out = {"total_ticks": sim.t, "agents": [a.name for a, _ in sim.agents], "symbols": {}, "pnl_history": {}, "final_inventory": {}}
    for sym in symbols:
        book = sim.books[sym]
        trades = sim.trade_tape[sym]
        candles = build_candles(trades, bar_ticks)
        out["symbols"][sym] = {
            "trades": [
                {
                    "ts": tr.ts, "price": tr.price, "qty": tr.qty,
                    "aggressor_side": tr.aggressor_side.value,
                    "maker_owner": tr.maker_owner, "taker_owner": tr.taker_owner,
                }
                for tr in trades
            ],
            "candles": candles_to_dicts(candles),
            "depth_snapshots": sim.depth_recorders[sym].snapshots,
            "final_best_bid": book.best_bid(),
            "final_best_ask": book.best_ask(),
        }
    for agent, _ in sim.agents:
        out["pnl_history"][agent.name] = sim.pnl_history[agent.name]
        out["final_inventory"][agent.name] = dict(sim.inventory[agent.name])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "output", "report.html"))
    ap.add_argument("--json-out", default=os.path.join(os.path.dirname(__file__), "output", "session.json"))
    args = ap.parse_args()

    sim, symbols = run_session(n_ticks=args.ticks, seed=args.seed)
    session = to_session_json(sim, symbols)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.json_out, "w") as f:
        json.dump(session, f)
    build_report(session, args.out)

    print(f"ticks simulated:        {sim.t}")
    for sym in symbols:
        book = sim.books[sym]
        crossed = book.best_bid() is not None and book.best_ask() is not None and book.best_bid() >= book.best_ask()
        print(f"[{sym}] trades={len(sim.trade_tape[sym]):5d}  "
              f"best_bid={book.best_bid()}  best_ask={book.best_ask()}  crossed={crossed}")
    print("\nleaderboard (name, pnl_ticks, inventory):")
    for name, pnl, inv in sim.leaderboard():
        print(f"  {name:16s} {pnl:8d}  {inv}")
    print(f"\nwrote {args.json_out}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
