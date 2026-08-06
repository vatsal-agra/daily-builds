"""SAN (Standard Algebraic Notation) move formatting and PGN export/import."""

from .board import Board, START_FEN, square_name, file_of, rank_of, parse_square
from .movegen import generate_legal_moves, is_in_check, opponent


def move_to_san(board, move, legal_moves=None):
    """board is the position BEFORE the move is played."""
    if move.castle in ("K", "k"):
        san = "O-O"
    elif move.castle in ("Q", "q"):
        san = "O-O-O"
    else:
        kind = move.piece.upper()
        dest = square_name(move.to)
        capture = bool(move.captured) or move.is_ep

        if kind == "P":
            san = (f"{square_name(move.frm)[0]}x{dest}" if capture else dest)
            if move.promotion:
                san += "=" + move.promotion.upper()
        else:
            disambiguation = _disambiguate(board, move, legal_moves)
            san = kind + disambiguation + ("x" if capture else "") + dest

    color = board.to_move
    u = board.make_move(move)
    opp = opponent(color)
    if is_in_check(board, opp):
        san += "#" if not generate_legal_moves(board) else "+"
    board.unmake_move(move, u)
    return san


def _disambiguate(board, move, legal_moves):
    if legal_moves is None:
        legal_moves = generate_legal_moves(board)
    same_dest_same_kind = [
        m for m in legal_moves
        if m.to == move.to and m.piece == move.piece and m.frm != move.frm
    ]
    if not same_dest_same_kind:
        return ""
    same_file = any(file_of(m.frm) == file_of(move.frm) for m in same_dest_same_kind)
    same_rank = any(rank_of(m.frm) == rank_of(move.frm) for m in same_dest_same_kind)
    src = square_name(move.frm)
    if not same_file:
        return src[0]
    if not same_rank:
        return src[1]
    return src


def game_to_pgn(moves_san, result="*", headers=None):
    """moves_san: list of SAN strings in play order. Returns a PGN string."""
    default_headers = {
        "Event": "Zugzwang Engine Game",
        "Site": "local",
        "Date": "????.??.??",
        "Round": "1",
        "White": "White",
        "Black": "Black",
        "Result": result,
    }
    if headers:
        default_headers.update(headers)

    lines = [f'[{k} "{v}"]' for k, v in default_headers.items()]
    lines.append("")

    move_text = ""
    for i, san in enumerate(moves_san):
        if i % 2 == 0:
            move_text += f"{i // 2 + 1}. {san} "
        else:
            move_text += f"{san} "
    move_text += result
    lines.append(move_text.strip())
    return "\n".join(lines) + "\n"


def parse_pgn_movetext(text):
    """Strip headers/comments/move numbers from PGN movetext, returning a
    flat list of SAN move tokens in order."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("[")]
    body = " ".join(lines)
    # strip comments in braces
    while "{" in body:
        start = body.index("{")
        end = body.find("}", start)
        if end == -1:
            body = body[:start]
            break
        body = body[:start] + body[end + 1:]
    tokens = body.split()
    result_tokens = {"1-0", "0-1", "1/2-1/2", "*"}
    san_moves = []
    for tok in tokens:
        if tok in result_tokens:
            continue
        # strip trailing move-number dots like "1." or "12..."
        cleaned = tok
        while cleaned and cleaned[0].isdigit():
            cleaned = cleaned[1:]
        cleaned = cleaned.lstrip(".")
        if cleaned:
            san_moves.append(cleaned)
    return san_moves


def san_to_move(board, san):
    """Resolve a SAN token against the current legal moves. Raises ValueError
    if it doesn't match exactly one legal move."""
    san_clean = san.rstrip("+#!?")
    legal = generate_legal_moves(board)

    if san_clean in ("O-O", "0-0"):
        for m in legal:
            if m.castle in ("K", "k"):
                return m
        raise ValueError(f"illegal move: {san}")
    if san_clean in ("O-O-O", "0-0-0"):
        for m in legal:
            if m.castle in ("Q", "q"):
                return m
        raise ValueError(f"illegal move: {san}")

    for m in legal:
        candidate = move_to_san(board, m, legal).rstrip("+#!?")
        if candidate == san_clean:
            return m
    raise ValueError(f"illegal or ambiguous move: {san}")


def replay_pgn(pgn_text, start_fen=START_FEN):
    """Returns (board, [(san, uci, fen_after), ...], position_hashes) after
    replaying a PGN. position_hashes is the Zobrist hash of every position
    from the start through the final move (for threefold-repetition
    bookkeeping downstream), avoiding a second, error-prone replay pass."""
    from .zobrist import hash_board

    board = Board.from_fen(start_fen)
    san_tokens = parse_pgn_movetext(pgn_text)
    history = []
    position_hashes = [hash_board(board)]
    for san in san_tokens:
        move = san_to_move(board, san)
        board.make_move(move)
        history.append((san, move.uci(), board.to_fen()))
        position_hashes.append(hash_board(board))
    return board, history, position_hashes
