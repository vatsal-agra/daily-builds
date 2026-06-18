"""Gambit command-line interface."""

import argparse
import sys
import time

from .board import Board, WHITE, move_uci
from .movegen import gen_legal, to_san, parse_san
from .perft import perft, perft_divide, REFERENCE
from .search import search, SearchInfo
from .engine import Engine, self_play, game_result, to_pgn


def cmd_perft(args):
    if args.suite:
        ok = True
        for name, fen, counts in REFERENCE:
            maxd = args.depth if args.depth else min(len(counts), 3)
            for d in range(1, maxd + 1):
                if d > len(counts):
                    break
                b = Board.from_fen(fen)
                t = time.time()
                got = perft(b, d)
                exp = counts[d - 1]
                status = "OK" if got == exp else "FAIL"
                if got != exp:
                    ok = False
                print(f"{name:12} d{d}: {got:>10} (exp {exp:>10}) {status}  "
                      f"{time.time()-t:.2f}s")
        sys.exit(0 if ok else 1)

    fen = args.fen or \
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    b = Board.from_fen(fen)
    if args.divide:
        total = 0
        for mv, cnt in perft_divide(b, args.depth).items():
            print(f"{mv}: {cnt}")
            total += cnt
        print(f"\nNodes: {total}")
    else:
        t = time.time()
        n = perft(b, args.depth)
        dt = time.time() - t
        nps = int(n / dt) if dt > 0 else 0
        print(f"perft({args.depth}) = {n}   ({dt:.2f}s, {nps} nps)")


def cmd_analyze(args):
    b = Board.from_fen(args.fen) if args.fen else Board.startpos()
    print(b)
    print(f"\nFEN: {b.to_fen()}")
    res, reason = game_result(b)
    if res:
        print(f"Game over: {res} ({reason})")
        return
    print(f"\nThinking (depth {args.depth})...")
    r = search(b, depth=args.depth, movetime=args.movetime, verbose=True)
    print(f"\nBest move: {to_san(b, r.move)} ({move_uci(r.move)})")
    print(f"Score: {r.score:+d} cp   Nodes: {r.nodes}   "
          f"Time: {r.elapsed:.2f}s")


def cmd_selfplay(args):
    print(f"Self-play (depth {args.depth}, max {args.maxmoves} moves)\n")
    board, sans, result, reason, evals, fens = self_play(
        depth=args.depth, movetime=args.movetime, max_moves=args.maxmoves,
        verbose=True)
    print(f"\nResult: {result} ({reason})")
    print(f"\n{board}")
    if args.pgn:
        pgn = to_pgn(sans, result)
        with open(args.pgn, "w") as f:
            f.write(pgn)
        print(f"\nPGN written to {args.pgn}")


def cmd_play(args):
    b = Board.from_fen(args.fen) if args.fen else Board.startpos()
    human = WHITE if args.color == "white" else 1
    engine = Engine(depth=args.depth, movetime=args.movetime)
    sans = []
    print("Gambit — you are", args.color)
    print("Enter moves as SAN (Nf3) or coordinates (g1f3). 'quit' to resign.\n")
    while True:
        print(b)
        res, reason = game_result(b)
        if res:
            print(f"\nGame over: {res} ({reason})")
            break
        if b.side == human:
            line = input("\nYour move: ").strip()
            if line in ("quit", "resign", "q"):
                print("You resigned.")
                break
            m = parse_san(b, line)
            if m is None:
                print("  Illegal/invalid move. Legal:",
                      ", ".join(to_san(b, x) for x in gen_legal(b)[:12]), "...")
                continue
            sans.append(to_san(b, m))
            b.make(m)
        else:
            print("\nGambit thinking...")
            r = engine.best_move(b)
            san = to_san(b, r.move)
            print(f"Gambit plays {san} (score {r.score:+d}, {r.nodes} nodes)")
            sans.append(san)
            b.make(r.move)
    if args.pgn and sans:
        with open(args.pgn, "w") as f:
            f.write(to_pgn(sans, game_result(b)[0] or "*"))
        print(f"PGN written to {args.pgn}")


def cmd_viz(args):
    from .viz import generate_viz
    out = args.out or "gambit_game.html"
    generate_viz(out, depth=args.depth, max_moves=args.maxmoves,
                 movetime=args.movetime)
    print(f"Wrote {out}")


def cmd_demo(args):
    from .demo import run_demo
    run_demo()


def main(argv=None):
    p = argparse.ArgumentParser(prog="gambit",
                                description="Gambit — a chess engine.")
    sub = p.add_subparsers(dest="cmd")

    pe = sub.add_parser("perft", help="count move-tree leaves / verify rules")
    pe.add_argument("depth", type=int, nargs="?", default=4)
    pe.add_argument("--fen")
    pe.add_argument("--divide", action="store_true")
    pe.add_argument("--suite", action="store_true",
                    help="run the reference verification suite")
    pe.set_defaults(func=cmd_perft)

    pa = sub.add_parser("analyze", help="search a position")
    pa.add_argument("--fen")
    pa.add_argument("--depth", type=int, default=5)
    pa.add_argument("--movetime", type=float, default=None)
    pa.set_defaults(func=cmd_analyze)

    ps = sub.add_parser("selfplay", help="engine vs engine")
    ps.add_argument("--depth", type=int, default=4)
    ps.add_argument("--movetime", type=float, default=None)
    ps.add_argument("--maxmoves", type=int, default=120)
    ps.add_argument("--pgn", help="write PGN to this path")
    ps.set_defaults(func=cmd_selfplay)

    pp = sub.add_parser("play", help="play against the engine")
    pp.add_argument("--fen")
    pp.add_argument("--color", choices=["white", "black"], default="white")
    pp.add_argument("--depth", type=int, default=4)
    pp.add_argument("--movetime", type=float, default=None)
    pp.add_argument("--pgn")
    pp.set_defaults(func=cmd_play)

    pv = sub.add_parser("viz", help="generate the HTML self-play replay")
    pv.add_argument("--out")
    pv.add_argument("--depth", type=int, default=4)
    pv.add_argument("--maxmoves", type=int, default=60)
    pv.add_argument("--movetime", type=float, default=None)
    pv.set_defaults(func=cmd_viz)

    pd = sub.add_parser("demo", help="run the end-to-end demo")
    pd.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
