"""Tic-Tac-Toe board mechanics shared by the minimax oracle and the TD
self-play trainer. A board is a 9-tuple of ' '/'X'/'O', row-major."""

WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # columns
    (0, 4, 8), (2, 4, 6),              # diagonals
)

EMPTY_BOARD = tuple(" " * 9)


def winner(board):
    for a, b, c in WIN_LINES:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]
    return None


def is_full(board):
    return " " not in board


def is_terminal(board):
    return winner(board) is not None or is_full(board)


def available_actions(board):
    return [i for i, v in enumerate(board) if v == " "]


def apply_move(board, action, player):
    if board[action] != " ":
        raise ValueError(f"cell {action} is already occupied")
    cells = list(board)
    cells[action] = player
    return tuple(cells)


def other_player(player):
    return "O" if player == "X" else "X"


def render(board):
    rows = [" | ".join(board[r * 3:r * 3 + 3]) for r in range(3)]
    return "\n---------\n".join(rows)
