"""Matchbook CLI: run/replay/viz/demo subcommands."""
from __future__ import annotations

import argparse
import json
import os
import sys

from .engine import Exchange
from .order import OrderType, Side, TimeInForce
from .risk import RiskLimits
from .simulator import SimulationConfig, Simulator
from .viz import render_session_html


def _parse_symbols(s: str) -> list[str]:
    seen: dict[str, None] = {}
    for x in s.split(","):
        x = x.strip().upper()
        if x:
            seen[x] = None  # dedupe while preserving first-seen order
    if not seen:
        raise argparse.ArgumentTypeError("at least one symbol is required")
    return list(seen)


def _require_positive_ticks(ticks: int) -> int | None:
    """Shared by every subcommand that runs a simulation. Returns an exit
    code to return immediately on failure, or None if `ticks` is fine."""
    if ticks <= 0:
        print("error: --ticks must be positive", file=sys.stderr)
        return 2
    return None


def _validate_journal_path(journal_path: str | None) -> int | None:
    if journal_path is None:
        return None
    parent = os.path.dirname(journal_path) or "."
    if not os.path.isdir(parent):
        print(f"error: --journal directory does not exist: {parent}", file=sys.stderr)
        return 2
    return None


def _validate_sim_args(args) -> int | None:
    """Shared by `run` and `viz`: every check a degenerate/adversarial CLI
    invocation of a full simulation config needs, in one place so the two
    subcommands can't drift out of sync the way they did before REVIEW.md
    finding #2 (viz silently accepted what run correctly rejected)."""
    rc = _require_positive_ticks(args.ticks)
    if rc is not None:
        return rc
    rc = _validate_journal_path(args.journal)
    if rc is not None:
        return rc
    if args.start_price <= 0:
        print("error: --start-price must be positive", file=sys.stderr)
        return 2
    if args.vol < 0:
        print("error: --vol (volatility) cannot be negative", file=sys.stderr)
        return 2
    for name in ("market_makers", "noise_traders", "momentum_traders", "informed_traders"):
        if getattr(args, name) < 0:
            print(f"error: --{name.replace('_', '-')} cannot be negative", file=sys.stderr)
            return 2
    return None


def _build_config(args) -> SimulationConfig:
    risk_limits = RiskLimits(
        position_limit=args.position_limit,
        fat_finger_pct=args.fat_finger_pct,
        max_order_qty=args.max_order_qty,
    )
    return SimulationConfig(
        symbols=args.symbols,
        n_ticks=args.ticks,
        seed=args.seed,
        start_price=args.start_price,
        fundamental_vol=args.vol,
        n_market_makers=args.market_makers,
        n_noise_traders=args.noise_traders,
        n_momentum_traders=args.momentum_traders,
        n_informed_traders=args.informed_traders,
        journal_path=args.journal,
        risk_limits=risk_limits,
        self_trade_prevention=not args.no_stp,
    )


def _add_sim_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--symbols", type=_parse_symbols, default=["ACME"], help="comma-separated ticker list")
    p.add_argument("--ticks", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--start-price", type=float, default=100.0)
    p.add_argument("--vol", type=float, default=0.08, help="fundamental-value per-tick volatility")
    p.add_argument("--market-makers", type=int, default=2)
    p.add_argument("--noise-traders", type=int, default=6)
    p.add_argument("--momentum-traders", type=int, default=3)
    p.add_argument("--informed-traders", type=int, default=1)
    p.add_argument("--journal", default=None, help="path to write the event journal to")
    p.add_argument("--position-limit", type=int, default=500)
    p.add_argument("--fat-finger-pct", type=float, default=0.25)
    p.add_argument("--max-order-qty", type=int, default=200)
    p.add_argument("--no-stp", action="store_true", help="disable self-trade prevention")


def cmd_run(args) -> int:
    rc = _validate_sim_args(args)
    if rc is not None:
        return rc
    config = _build_config(args)
    sim = Simulator(config)
    sim.run(record_history=False)
    sim.close()
    summary = sim.exchange.summary()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_replay(args) -> int:
    if not os.path.exists(args.journal):
        print(f"error: journal file not found: {args.journal}", file=sys.stderr)
        return 2
    # Note: no risk-limit flags here. Replay never re-runs the risk engine
    # -- a journaled rejection is replayed verbatim, and an accepted order
    # is never re-checked -- so a risk limit passed here would silently do
    # nothing. `--no-stp` is the one flag that matters: self-trade
    # prevention *is* re-evaluated live during replay (it's a matching-time
    # decision, not something the journal records in advance), so it must
    # match whatever the original live session used.
    ex = Exchange.replay(args.journal, symbols=args.symbols, self_trade_prevention=not args.no_stp)
    print(json.dumps(ex.summary(), indent=2, sort_keys=True))
    return 0


def cmd_viz(args) -> int:
    rc = _validate_sim_args(args)
    if rc is not None:
        return rc
    config = _build_config(args)
    sim = Simulator(config)
    sim.run(record_history=True)
    sim.close()
    html = render_session_html(
        symbols=config.symbols,
        history=sim.history,
        trades=sim.exchange.trade_tape,
        summary=sim.exchange.summary(),
        bar_size=args.bar_size,
    )
    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {out_path} ({len(html)} bytes, {len(sim.exchange.trade_tape)} trades, {config.n_ticks} ticks)")
    return 0


def cmd_crash_demo(args) -> int:
    """Run half a session, 'crash' (abandon the live Exchange without a
    clean shutdown), then reconstruct state purely from the journal and
    prove it matches what was live at the moment of the crash."""
    rc = _require_positive_ticks(args.ticks)
    if rc is not None:
        return rc
    rc = _validate_journal_path(args.journal)
    if rc is not None:
        return rc
    journal_path = args.journal
    config = SimulationConfig(
        symbols=args.symbols, n_ticks=args.ticks, seed=args.seed,
        journal_path=journal_path,
    )
    sim = Simulator(config)
    half = args.ticks // 2
    sim.run(half, record_history=False)
    live_fingerprint = sim.exchange.state_fingerprint()
    live_summary = sim.exchange.summary()
    # Simulate a hard crash: do NOT call sim.close(); just drop the object.
    # (Every event was already fsynced at append time, so nothing more is
    # needed for the data to be durable.)
    del sim

    recovered = Exchange.replay(journal_path, symbols=config.symbols)
    recovered_fingerprint = recovered.state_fingerprint()
    ok = live_fingerprint == recovered_fingerprint
    print(json.dumps({
        "ticks_before_crash": half,
        "live_trade_count": live_summary["trade_count"],
        "recovered_trade_count": recovered.summary()["trade_count"],
        "fingerprints_match": ok,
    }, indent=2))
    return 0 if ok else 1


def cmd_demo(args) -> int:
    """Exercise every required and stretch feature end-to-end and print a
    human-readable report. This is what demo.sh runs."""
    from .book import OrderBook
    from .order import Order

    print("=== 1. Matching engine: limit/market/IOC/FOK, partial fills ===")
    book = OrderBook("DEMO")
    book.submit(Order(1, "DEMO", Side.BUY, OrderType.LIMIT, 100, 10.00, agent_id="alice"))
    book.submit(Order(2, "DEMO", Side.BUY, OrderType.LIMIT, 50, 10.05, agent_id="bob"))
    trades = book.submit(Order(3, "DEMO", Side.SELL, OrderType.LIMIT, 120, 9.90, agent_id="carol"))
    print(f"  aggressive sell of 120 vs two resting bids -> {len(trades)} trades: "
          + ", ".join(f"{t.qty}@{t.price}" for t in trades))
    fok_order = Order(4, "DEMO", Side.BUY, OrderType.LIMIT, 10_000, 10.10, tif=TimeInForce.FOK, agent_id="dave")
    book.submit(fok_order)
    print(f"  oversized FOK buy -> status={fok_order.status.value} (no partial fill, book untouched)")
    ioc_order = Order(5, "DEMO", Side.SELL, OrderType.LIMIT, 5, 10.20, tif=TimeInForce.IOC, agent_id="erin")
    book.submit(ioc_order)
    print(f"  IOC sell above the book -> status={ioc_order.status.value} (does not rest)")

    print("\n=== 2. Event-sourced journal + crash recovery ===")
    crash_rc = cmd_crash_demo(argparse.Namespace(journal=args.journal, symbols=["ACME"], ticks=200, seed=7))

    print("\n=== 3. Multi-agent market simulation (emergent price action) ===")
    tight_risk = RiskLimits(position_limit=80, fat_finger_pct=0.25, max_order_qty=50)
    sim_config = SimulationConfig(symbols=["ACME", "GLOBEX"], n_ticks=300, seed=99, journal_path=None, risk_limits=tight_risk)
    sim = Simulator(sim_config)
    sim.run(record_history=False)
    summary = sim.exchange.summary()
    print(f"  ran {sim_config.n_ticks} ticks, {summary['trade_count']} trades across {sim_config.symbols}")
    for s in sim_config.symbols:
        print(f"    {s} closed at {summary['last_price'].get(s)}")
    print(f"  risk rejections: {summary['rejections']}, self-trade cancels: {summary['stp_cancels']}")
    if sim.exchange.rejections:
        print(f"    e.g. {sim.exchange.rejections[0]['reason']}")

    print("\n=== 4/5/6. Interactive HTML visualizer, risk engine, multi-symbol ===")
    viz_config = SimulationConfig(symbols=["ACME", "GLOBEX"], n_ticks=300, seed=99, journal_path=None, risk_limits=tight_risk)
    viz_sim = Simulator(viz_config)
    viz_sim.run(record_history=True)
    html = render_session_html(
        symbols=viz_config.symbols, history=viz_sim.history,
        trades=viz_sim.exchange.trade_tape, summary=viz_sim.exchange.summary(),
    )
    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"  wrote {out_path} ({len(html)} bytes)")

    print("\n=== Demo complete ===")
    return 0 if crash_rc == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="matchbook", description="A from-scratch exchange matching engine + market simulator.")
    sub = p.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a market simulation and print a summary")
    _add_sim_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_replay = sub.add_parser("replay", help="rebuild exchange state from a journal file")
    p_replay.add_argument("journal")
    p_replay.add_argument("--symbols", type=_parse_symbols, default=["ACME"])
    p_replay.add_argument("--no-stp", action="store_true", help="must match the original live session's setting")
    p_replay.set_defaults(func=cmd_replay)

    p_viz = sub.add_parser("viz", help="run a simulation and render an interactive HTML replay")
    _add_sim_args(p_viz)
    p_viz.add_argument("--out", default="matchbook_session.html")
    p_viz.add_argument("--bar-size", type=int, default=10)
    p_viz.set_defaults(func=cmd_viz)

    p_crash = sub.add_parser("crash-demo", help="run half a session, simulate a crash, verify journal-only recovery")
    p_crash.add_argument("--journal", default="crash_demo.journal")
    p_crash.add_argument("--symbols", type=_parse_symbols, default=["ACME"])
    p_crash.add_argument("--ticks", type=int, default=200)
    p_crash.add_argument("--seed", type=int, default=7)
    p_crash.set_defaults(func=cmd_crash_demo)

    p_demo = sub.add_parser("demo", help="exercise every feature end-to-end")
    p_demo.add_argument("--journal", default="demo.journal")
    p_demo.add_argument("--out", default="matchbook_demo.html")
    p_demo.set_defaults(func=cmd_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: never a raw traceback
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
