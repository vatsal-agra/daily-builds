"""Gambit command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time

from .board import Board, move_uci
from .movegen import legal_moves, in_check
from .perft import perft, perft_divide, PERFT_POSITIONS
from .san import to_san, from_san, game_to_pgn
from .engine import Engine, play_game, format_score, result_text


def _board_from_args(args) -> Board:
    if getattr(args, "fen", None):
        return Board.from_fen(args.fen)
    return Board.startpos()


def cmd_perft(args):
    if args.verify:
        ok = True
        for name, fen, exp in PERFT_POSITIONS:
            for d in sorted(exp):
                if d > args.depth:
                    continue
                t = time.time()
                got = perft(Board.from_fen(fen), d)
                good = got == exp[d]
                ok = ok and good
                flag = "ok " if good else "FAIL"
                print(f"{flag} {name:10} depth {d}: {got:>10}  "
                      f"(expected {exp[d]:>10})  {time.time()-t:.2f}s")
        return 0 if ok else 1

    b = _board_from_args(args)
    if args.divide:
        total = 0
        for uci, cnt in perft_divide(b, args.depth):
            print(f"{uci}: {cnt}")
            total += cnt
        print(f"\nnodes: {total}")
    else:
        t = time.time()
        n = perft(b, args.depth)
        print(f"perft({args.depth}) = {n}   ({time.time()-t:.3f}s)")
    return 0


def cmd_analyse(args):
    b = _board_from_args(args)
    eng = Engine(depth=args.depth, movetime=args.movetime)
    info = eng.analyse(b)
    print(b)
    print()
    print(f"side to move : {'white' if b.side == 0 else 'black'}")
    print(f"best move    : {info['best_san']}  ({info['best_move']})")
    print(f"score        : {info['score_str']}  ({info['score']} cp)")
    print(f"depth        : {info['depth']}")
    print(f"nodes        : {info['nodes']}  ({info['time']}s)")
    print(f"pv           : {' '.join(info['pv'])}")
    return 0


def cmd_selfplay(args):
    w = Engine(depth=args.depth, movetime=args.movetime)
    bl = Engine(depth=args.depth, movetime=args.movetime)
    game = play_game(w, bl, start_fen=args.fen, max_moves=args.max_moves,
                     verbose=not args.quiet)
    san_list = [m["san"] for m in game["moves"]]
    pgn = game_to_pgn(game["start_fen"], san_list, game["result"])
    print("\nresult:", game["result"])
    if args.pgn:
        with open(args.pgn, "w") as f:
            f.write(pgn + "\n")
        print("wrote PGN to", args.pgn)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(game, f, indent=2)
        print("wrote game JSON to", args.json)
    if not args.pgn and not args.json:
        print()
        print(pgn)
    return 0


def cmd_play(args):
    b = _board_from_args(args)
    eng = Engine(depth=args.depth, movetime=args.movetime)
    human = 0 if args.color == "white" else 1
    history = [b.zobrist]
    counts = {b.zobrist: 1}
    print("You are", args.color + ".  Enter moves in SAN (e.g. Nf3, e4, O-O) or 'quit'.")
    while True:
        print()
        print(b)
        over = result_text(b, counts)
        if over:
            print("\nGame over:", over)
            break
        if b.side == human:
            try:
                line = input("\nyour move> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye")
                break
            if line in ("quit", "exit"):
                break
            if not line:
                continue
            try:
                mv = from_san(b, line)
            except ValueError:
                legal = ", ".join(sorted(to_san(b, m) for m in legal_moves(b)))
                print(f"illegal move. legal: {legal}")
                continue
        else:
            res = eng.best_move(b, history=history[:-1])
            mv = res.best_move
            print(f"\nengine plays {to_san(b, mv)}  "
                  f"({format_score(res.score)}, depth {res.depth}, {res.nodes} nodes)")
        b.make_move(mv)
        history.append(b.zobrist)
        counts[b.zobrist] = counts.get(b.zobrist, 0) + 1
    return 0


def cmd_viz(args):
    from .viz import write_viz
    w = Engine(depth=args.depth, movetime=args.movetime)
    bl = Engine(depth=args.depth, movetime=args.movetime)
    print("playing game for visualisation...")
    game = play_game(w, bl, start_fen=args.fen, max_moves=args.max_moves,
                     verbose=not args.quiet)
    path = write_viz(game, args.out)
    print(f"\nresult: {game['result']}")
    print(f"wrote interactive viewer to {path}")
    return 0


def cmd_serve(args):
    from .server import serve
    serve(host=args.host, port=args.port, depth=args.depth, movetime=args.movetime)
    return 0


def cmd_demo(args):
    from . import demo
    return demo.run()


def build_parser():
    p = argparse.ArgumentParser(prog="gambit", description="Gambit chess engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("perft", help="count move-tree leaf nodes")
    pe.add_argument("depth", type=int)
    pe.add_argument("--fen")
    pe.add_argument("--divide", action="store_true")
    pe.add_argument("--verify", action="store_true",
                    help="check against published counts up to <depth>")
    pe.set_defaults(func=cmd_perft)

    pa = sub.add_parser("analyse", help="analyse a position")
    pa.add_argument("--fen")
    pa.add_argument("--depth", type=int, default=5)
    pa.add_argument("--movetime", type=float, default=None)
    pa.set_defaults(func=cmd_analyse)

    ps = sub.add_parser("selfplay", help="engine vs engine")
    ps.add_argument("--fen")
    ps.add_argument("--depth", type=int, default=4)
    ps.add_argument("--movetime", type=float, default=None)
    ps.add_argument("--max-moves", type=int, default=200)
    ps.add_argument("--pgn", help="write PGN to file")
    ps.add_argument("--json", help="write annotated game JSON to file")
    ps.add_argument("--quiet", action="store_true")
    ps.set_defaults(func=cmd_selfplay)

    pp = sub.add_parser("play", help="play against the engine in the terminal")
    pp.add_argument("--fen")
    pp.add_argument("--color", choices=["white", "black"], default="white")
    pp.add_argument("--depth", type=int, default=4)
    pp.add_argument("--movetime", type=float, default=2.0)
    pp.set_defaults(func=cmd_play)

    pv = sub.add_parser("viz", help="play a game and emit an HTML viewer")
    pv.add_argument("--fen")
    pv.add_argument("--depth", type=int, default=4)
    pv.add_argument("--movetime", type=float, default=None)
    pv.add_argument("--max-moves", type=int, default=120)
    pv.add_argument("--out", default="game.html")
    pv.add_argument("--quiet", action="store_true")
    pv.set_defaults(func=cmd_viz)

    pse = sub.add_parser("serve", help="serve a browser board (play the real engine)")
    pse.add_argument("--host", default="127.0.0.1")
    pse.add_argument("--port", type=int, default=8000)
    pse.add_argument("--depth", type=int, default=4)
    pse.add_argument("--movetime", type=float, default=2.0)
    pse.set_defaults(func=cmd_serve)

    pd = sub.add_parser("demo", help="run a full feature demo")
    pd.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
