"""End-to-end demo: exercises every feature in one run."""

import time

from .board import Board
from .movegen import to_san, gen_legal
from .perft import perft, REFERENCE
from .search import search
from .engine import self_play, to_pgn
from .eval import evaluate, MATE_THRESHOLD


def _hr(title):
    print("\n" + "=" * 66)
    print(f"  {title}")
    print("=" * 66)


def run_demo():
    _hr("1. perft — proving the move generator is exact")
    caps = {"startpos": 4, "kiwipete": 3, "position3": 4,
            "position4": 3, "position5": 3}
    for name, fen, counts in REFERENCE:
        d = min(caps[name], len(counts))
        b = Board.from_fen(fen)
        t = time.time()
        got = perft(b, d)
        ok = "OK" if got == counts[d - 1] else "FAIL"
        print(f"  {name:11} perft({d}) = {got:>9}  (exp {counts[d-1]:>9})  "
              f"{ok}  {time.time()-t:.2f}s")

    _hr("2. evaluation — material/PST, color-symmetric")
    b = Board.startpos()
    print(f"  start position eval: {evaluate(b)} cp (balanced)")
    b2 = Board.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN1 "
                        "w Qkq - 0 1")
    print(f"  white down a rook:   {evaluate(b2)} cp")

    _hr("3. search — solving tactics")
    puzzles = [
        ("Mate in 1 (back rank)", "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1", 3),
        ("Win the hanging queen", "4k3/8/8/8/3q4/8/8/3RK3 w - - 0 1", 4),
        ("KQ vs K — find mate", "6k1/8/6K1/8/8/8/8/3Q4 w - - 0 1", 4),
    ]
    for label, fen, d in puzzles:
        b = Board.from_fen(fen)
        r = search(b, depth=d)
        sc = "mate" if abs(r.score) > MATE_THRESHOLD else f"{r.score:+d}cp"
        print(f"  {label:24} -> {to_san(b, r.move):7} ({sc}, {r.nodes} nodes)")

    _hr("4. self-play — engine vs engine converts a won endgame")
    b, sans, res, reason, evals, fens = self_play(
        depth=4, max_moves=40, verbose=False,
        start_fen="4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    moves_str = " ".join(
        (f"{i//2+1}." if i % 2 == 0 else "") + s for i, s in enumerate(sans))
    print(f"  {moves_str}")
    print(f"  result: {res} ({reason})")

    _hr("5. PGN export")
    print(to_pgn(sans, res, {"Event": "Gambit demo (KQ vs K)"}))

    _hr("Demo complete — every subsystem exercised.")
    print("  Try:  python3 -m gambit.cli play       (play against it)")
    print("        python3 -m gambit.cli viz        (HTML self-play replay)")
    print("        python3 -m gambit.cli perft --suite")


if __name__ == "__main__":
    run_demo()
