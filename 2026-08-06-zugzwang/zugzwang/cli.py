"""Terminal interface: human vs engine, and engine vs engine self-play."""

import argparse
import re

from .board import Board, START_FEN, parse_square, WHITE, BLACK
from .movegen import generate_legal_moves, game_state, is_in_check
from .search import Searcher
from .pgn import move_to_san, game_to_pgn
from .zobrist import hash_board
from . import book as opening_book

UNICODE_PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
    ".": "·",
}

UCI_RE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbnQRBN]?$")


def render_board(board, unicode=True, flipped=False):
    ranks = range(7, -1, -1) if not flipped else range(0, 8)
    files = range(8) if not flipped else range(7, -1, -1)
    lines = []
    for r in ranks:
        row = f"{r + 1} "
        for f in files:
            piece = board.squares[r * 8 + f]
            glyph = UNICODE_PIECES[piece] if unicode else piece
            row += glyph + " "
        lines.append(row)
    file_labels = "abcdefgh" if not flipped else "hgfedcba"
    lines.append("  " + " ".join(file_labels))
    return "\n".join(lines)


def parse_user_move(board, text):
    text = text.strip()
    legal = generate_legal_moves(board)
    if UCI_RE.match(text):
        frm = parse_square(text[0:2])
        to = parse_square(text[2:4])
        promo = text[4:5].lower() if len(text) > 4 else None
        for m in legal:
            if m.frm == frm and m.to == to:
                if promo:
                    if m.promotion and m.promotion.lower() == promo:
                        return m
                elif not m.promotion:
                    return m
        raise ValueError(f"illegal move: {text}")
    from .pgn import san_to_move
    try:
        return san_to_move(board, text)
    except ValueError:
        # forgiving of e.g. "nf3" for "Nf3" -- capitalize a leading piece letter
        if text[:1].lower() in "nbrqk":
            return san_to_move(board, text[0].upper() + text[1:])
        raise


def describe_state(board, position_history=None):
    state = game_state(board, position_history)
    if state == "checkmate":
        winner = "Black" if board.to_move == WHITE else "White"
        return f"Checkmate -- {winner} wins.", True
    if state == "stalemate":
        return "Stalemate -- draw.", True
    if state == "draw_fifty":
        return "Draw -- fifty-move rule.", True
    if state == "draw_insufficient":
        return "Draw -- insufficient material.", True
    if state == "draw_repetition":
        return "Draw -- threefold repetition.", True
    return None, False


def play(args):
    board = Board.from_fen(args.fen) if args.fen else Board.from_fen(START_FEN)
    searcher = Searcher()
    human_color = WHITE if args.side == "white" else BLACK
    san_history = []
    position_history = [hash_board(board)]
    book = opening_book.OpeningBook() if not args.no_book else None

    print("Zugzwang -- you are", "White" if human_color == WHITE else "Black")
    print("Enter moves in SAN (e4, Nf3, O-O) or UCI (e2e4). Type 'quit' to resign.\n")

    while True:
        print(render_board(board, unicode=not args.ascii))
        msg, over = describe_state(board, position_history)
        if over:
            print("\n" + msg)
            break
        in_check = is_in_check(board, board.to_move)
        turn = "White" if board.to_move == WHITE else "Black"
        print(f"\n{turn} to move." + (" (in check)" if in_check else ""))

        if board.to_move == human_color:
            raw = input("> ").strip()
            if raw.lower() in ("quit", "resign"):
                print(f"{turn} resigns.")
                break
            try:
                move = parse_user_move(board, raw)
            except ValueError as e:
                print(f"  {e}")
                continue
        else:
            move = book.lookup(board, san_history) if book else None
            if move:
                print("(engine plays from book)")
            else:
                move, score, depth = searcher.choose_move(board, seconds=args.time)
                print(f"(engine searched depth {depth}, eval {score:+d}cp, {searcher.nodes} nodes)")

        legal = generate_legal_moves(board)
        san = move_to_san(board, move, legal)
        board.make_move(move)
        san_history.append(san)
        position_history.append(hash_board(board))
        print(f"  played: {san}\n")

    if args.pgn:
        with open(args.pgn, "w") as f:
            f.write(game_to_pgn(san_history))
        print(f"\nPGN saved to {args.pgn}")


def selfplay(args):
    board = Board.from_fen(args.fen) if args.fen else Board.from_fen(START_FEN)
    searcher = Searcher()
    book = opening_book.OpeningBook() if not args.no_book else None
    san_history = []
    position_history = [hash_board(board)]

    for ply in range(args.max_moves * 2):
        msg, over = describe_state(board, position_history)
        if over:
            print(msg)
            break
        move = book.lookup(board, san_history) if book else None
        source = "book"
        if move is None:
            move, score, depth = searcher.choose_move(board, seconds=args.time)
            source = f"depth {depth}, {score:+d}cp"
        legal = generate_legal_moves(board)
        san = move_to_san(board, move, legal)
        board.make_move(move)
        san_history.append(san)
        position_history.append(hash_board(board))
        mover = "White" if ply % 2 == 0 else "Black"
        print(f"{ply // 2 + 1}{'.' if ply % 2 == 0 else '...'} {san:<8} ({mover}, {source})")
    else:
        print(f"Stopped after {args.max_moves} full moves.")

    print()
    print(render_board(board, unicode=not args.ascii))

    if args.pgn:
        with open(args.pgn, "w") as f:
            f.write(game_to_pgn(san_history))
        print(f"\nPGN saved to {args.pgn}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="zugzwang", description="A from-scratch chess engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_play = sub.add_parser("play", help="play a game against the engine in the terminal")
    p_play.add_argument("--side", choices=["white", "black"], default="white")
    p_play.add_argument("--time", type=float, default=3.0, help="engine think time per move, seconds")
    p_play.add_argument("--fen", default=None, help="start from a custom FEN")
    p_play.add_argument("--pgn", default=None, help="save the finished game to this PGN file")
    p_play.add_argument("--ascii", action="store_true", help="use ASCII piece letters instead of unicode")
    p_play.add_argument("--no-book", action="store_true", help="disable the opening book")
    p_play.set_defaults(func=play)

    p_self = sub.add_parser("selfplay", help="watch the engine play itself")
    p_self.add_argument("--time", type=float, default=1.0)
    p_self.add_argument("--max-moves", type=int, default=80, dest="max_moves")
    p_self.add_argument("--fen", default=None)
    p_self.add_argument("--pgn", default=None)
    p_self.add_argument("--ascii", action="store_true")
    p_self.add_argument("--no-book", action="store_true")
    p_self.set_defaults(func=selfplay)

    p_perft = sub.add_parser("perft", help="run perft node-count verification")
    p_perft.add_argument("--fen", default=START_FEN)
    p_perft.add_argument("--depth", type=int, default=4)
    p_perft.set_defaults(func=lambda a: _run_perft(a))

    args = parser.parse_args(argv)
    args.func(args)


def _run_perft(args):
    from .perft import perft
    import time
    board = Board.from_fen(args.fen)
    for d in range(1, args.depth + 1):
        t0 = time.time()
        n = perft(board, d)
        print(f"depth {d}: {n} nodes ({time.time() - t0:.2f}s)")


if __name__ == "__main__":
    main()
