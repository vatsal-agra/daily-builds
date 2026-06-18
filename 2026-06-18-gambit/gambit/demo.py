"""A self-checking feature demo: exercises every part of Gambit and prints a tour."""

from __future__ import annotations

import time

from .board import Board, move_uci
from .perft import perft, PERFT_POSITIONS
from .san import to_san, game_to_pgn
from .engine import Engine, play_game, format_score


def _h(title):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def run() -> int:
    _h("1) Legal move generation — perft vs published node counts")
    all_ok = True
    for name, fen, exp in PERFT_POSITIONS:
        d = 3
        t = time.time()
        got = perft(Board.from_fen(fen), d)
        ok = got == exp[d]
        all_ok = all_ok and ok
        print(f"  {'OK ' if ok else 'BAD'} {name:10} perft({d}) = {got:>8}  "
              f"(expected {exp[d]:>8})  {time.time()-t:.2f}s")
    print("  => move generation", "VERIFIED" if all_ok else "FAILED")

    _h("2) Alpha-beta search — find a forced mate")
    fen = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
    b = Board.from_fen(fen)
    print(b)
    res = Engine(depth=4).best_move(b)
    print(f"\n  best move: {to_san(b, res.best_move)}  "
          f"score {format_score(res.score)}  (depth {res.depth}, {res.nodes} nodes)")

    _h("3) Position evaluation — a sharp middlegame")
    fen = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
    b = Board.from_fen(fen)
    info = Engine(depth=5, movetime=2.0).analyse(b)
    print(f"  position: {fen}")
    print(f"  engine likes {info['best_san']} ({info['score_str']}), "
          f"pv: {' '.join(info['pv'])}")

    _h("4) SAN / FEN / PGN round-trip + a full engine-vs-engine game")
    g = play_game(Engine(depth=3, movetime=1.0), Engine(depth=3, movetime=1.0),
                  max_moves=40, verbose=False)
    pgn = game_to_pgn(g["start_fen"], [m["san"] for m in g["moves"]], g["result"])
    print(pgn)
    print(f"\n  result: {g['result']}  ({len(g['moves'])} plies)")

    _h("5) Transposition table — node savings at fixed depth")
    fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    on = Engine(depth=4, use_tt=True).best_move(Board.from_fen(fen))
    off = Engine(depth=4, use_tt=False).best_move(Board.from_fen(fen))
    print(f"  TT off: {off.nodes:>8} nodes")
    print(f"  TT on : {on.nodes:>8} nodes  "
          f"({100*(off.nodes-on.nodes)/off.nodes:.1f}% fewer, same score "
          f"{format_score(on.score)})")

    _h("6) Interactive outputs")
    from .viz import write_viz
    path = write_viz(g, "demo_game.html")
    print(f"  wrote a self-contained HTML game viewer -> {path}")
    print("  run `python3 -m gambit.cli serve` to play the engine in your browser.")

    print("\nAll features exercised.\n")
    return 0
