"""A from-scratch, memoized negamax perfect Tic-Tac-Toe player.

Tic-Tac-Toe is a solved game: with correct play by both sides the result
is always a draw. This module exhaustively searches the full game tree
(memoized on (board, player-to-move), at most 5478 reachable boards) to
play provably optimal moves — it never loses, and it wins whenever the
opponent gives it the chance. It is the ground-truth oracle
bellman/selfplay.py's learned agent is validated against: a self-play
agent that has actually learned to play well must never lose to this.

Scores are from the perspective of the player to move, in {win, draw,
loss}, tie-broken by search depth so the engine prefers a faster win and
a slower loss over an equally "won"/"lost" line that gets there slower.
The state space is tiny enough (well under 6000 boards) that a full
memoized search is already instant, so this deliberately skips alpha-beta
pruning: combining alpha-beta with a plain "cache by (board, player)"
transposition table is a classic correctness bug (a score returned under
a narrowed alpha-beta window can be a bound, not the true value, and is
unsafe to reuse for a *different* window) unless the cache also records
the bound type — machinery this game is too small to need.
"""
from .envs.tictactoe import (
    apply_move, available_actions, is_full, other_player, winner,
)

_MEMO = {}


def _negamax(board, player, depth):
    key = (board, player)
    cached = _MEMO.get(key)
    if cached is not None:
        return cached

    opponent = other_player(player)
    w = winner(board)
    if w == player:
        result = (10 - depth, None)
    elif w == opponent:
        result = (depth - 10, None)
    elif is_full(board):
        result = (0, None)
    else:
        best_score = None
        best_action = None
        for action in available_actions(board):
            child = apply_move(board, action, player)
            child_score, _ = _negamax(child, opponent, depth + 1)
            score = -child_score
            if best_score is None or score > best_score:
                best_score = score
                best_action = action
        result = (best_score, best_action)

    _MEMO[key] = result
    return result


def best_move(board, player):
    """Return (action, score) for the optimal move; action is None if the
    board is already terminal."""
    score, action = _negamax(board, player, 0)
    return action, score


def _category(score):
    """win/draw/loss, independent of the "prefer a faster win" depth bonus
    baked into the raw score -- see the note below on why best_moves()
    compares categories rather than raw scores."""
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def best_moves(board, player):
    """Return (category, [all actions achieving that optimal outcome
    category]). Several moves are often equally optimal (e.g. the empty
    board: every opening square is a drawn position under correct play),
    and always taking the first one in index order makes the "oracle"
    play the same predictable line every game -- fine for a proof of
    optimality, useless for generating varied games to stress-test another
    agent against.

    This compares win/draw/loss *category* rather than the exact raw
    score `best_move` uses, deliberately: raw scores embed a "prefer a
    faster win / slower loss" depth bonus that is only meaningful measured
    from a single fixed search root, but _MEMO caches nodes across many
    different root calls (this function's own root included), so two
    cached scores for sibling children are not guaranteed to share the
    same depth baseline and are not safe to compare for exact equality.
    Category (sign of the score) has no such problem: is_full() draws are
    always exactly 0 and win/loss scores never cross zero regardless of
    which call first populated the cache, so every node ever stored
    unambiguously reflects which one of the three outcomes is forced --
    which is the only thing "equally optimal" needs to mean here.
    """
    opponent = other_player(player)
    best_cat = None
    tied_actions = []
    for action in available_actions(board):
        child = apply_move(board, action, player)
        child_score, _ = _negamax(child, opponent, 0)
        cat = -_category(child_score)
        if best_cat is None or cat > best_cat:
            best_cat = cat
            tied_actions = [action]
        elif cat == best_cat:
            tied_actions.append(action)
    return best_cat, tied_actions


def best_move_random_tiebreak(board, player, rng):
    """Like best_move, but pick uniformly among all equally-optimal moves
    using the supplied random.Random instead of always the first one --
    for generating varied (but still perfectly-played) oracle games."""
    _, actions = best_moves(board, player)
    if not actions:
        return None
    return rng.choice(actions)


def memo_snapshot():
    """A read-only copy of every (board, player) -> (score, action) entry
    computed so far. Used to export the full solved game tree once for the
    visualizer's client-side "play against a perfect opponent" mode."""
    return dict(_MEMO)


def play(board, player):
    """Convenience wrapper: apply the optimal move and return the new board.
    Raises ValueError if `board` is already terminal (nothing to play)."""
    action, _ = best_move(board, player)
    if action is None:
        raise ValueError("board is already terminal, no move to make")
    return apply_move(board, action, player)
