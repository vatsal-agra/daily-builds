"""Evaluation & ground-truth verification harness:

  (a) `oracle_invariant_check` -- exhaustively walks the real Tic-Tac-Toe
      game tree, branching over EVERY game-theoretically-optimal move the
      oracle could make (not just one arbitrary optimal line), and checks
      that the trained agent (deterministic argmax MCTS, zero Dirichlet
      noise, zero temperature) never ends up losing, from either side.

  (b) a round-robin tournament + simple sequential-Elo ladder across
      baselines (random, pure-MCTS-with-uniform-priors-and-rollout-value)
      and successive training-generation checkpoints, proving learning
      actually happened (measured win rates), not merely "it ran".

Both entry points build players with `add_root_noise=False` and
`temperature=0` -- Dirichlet noise and temperature sampling are a
self-play-only exploration device and must never leak into evaluation
(see REVIEW.md for how this separation is actually tested).
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import numpy as np

from .mcts import MCTS, sample_action
from .oracle_tictactoe import minimax_value, best_moves
from .games.tictactoe import TicTacToe


# ----------------------------------------------------------------------
# Players
# ----------------------------------------------------------------------

class Player:
    name = "abstract"

    def select_move(self, game, state, rng: np.random.Generator) -> int:
        raise NotImplementedError


class RandomPlayer(Player):
    name = "random"

    def select_move(self, game, state, rng):
        moves = game.legal_moves(state)
        return int(rng.choice(moves))


class NetMCTSPlayer(Player):
    """The real agent under test: PUCT MCTS guided by a trained network,
    deterministic (argmax, no Dirichlet noise) for evaluation."""

    def __init__(self, net, n_simulations=100, c_puct=1.5, name="net-mcts"):
        self.net = net
        self.n_simulations = n_simulations
        self.c_puct = c_puct
        self.name = name

    def select_move(self, game, state, rng):
        mcts = MCTS(game, self.net, c_puct=self.c_puct, n_simulations=self.n_simulations, rng=rng)
        visit_counts = mcts.run(state, add_root_noise=False)
        return sample_action(visit_counts, temperature=0.0, rng=rng)


class RolloutMCTS(MCTS):
    """'Pure' MCTS baseline: uniform priors (no learned policy) and leaf
    values estimated by random-play rollout to a terminal state (the
    pre-AlphaZero, classic-MCTS way of getting a value without a network).
    Deliberately does not use `self.net` at all.
    """

    def __init__(self, game, n_rollouts_per_leaf=4, rng=None, **kwargs):
        super().__init__(game, net=None, rng=rng, **kwargs)
        self.n_rollouts_per_leaf = n_rollouts_per_leaf

    def _evaluate(self, state):
        legal = self.game.legal_moves(state)
        priors = {a: 1.0 / len(legal) for a in legal}
        total = 0.0
        mover = self.game.current_player(state)
        for _ in range(self.n_rollouts_per_leaf):
            total += self._random_rollout(state, mover)
        return priors, total / self.n_rollouts_per_leaf

    def _random_rollout(self, state, perspective_player) -> float:
        s = state
        while not self.game.is_terminal(s):
            moves = self.game.legal_moves(s)
            a = moves[self.rng.integers(len(moves))]
            s = self.game.apply_move(s, a)
        return self.game.outcome_for(s, perspective_player)


class NetPolicyOnlyPlayer(Player):
    """No search at all: argmax of the network's raw (legal-masked)
    policy head. Used to isolate and demonstrate the NETWORK's own
    learned quality across generations, independent of how much a strong
    tree search can compensate for a weak network -- which matters
    precisely because Tic-Tac-Toe's tree is shallow enough that even a
    handful of MCTS simulations can play it almost perfectly regardless
    of network quality (see REVIEW.md / README.md for why the
    search-based tournament alone is a noisy signal of learning on this
    particular game, and why this player exists)."""

    def __init__(self, net, name="net-policy-only"):
        self.net = net
        self.name = name

    def select_move(self, game, state, rng):
        x = game.encode(state)
        mask = game.legal_mask(state)
        probs, _ = self.net.predict_one(x, mask)
        return int(np.argmax(probs))


class PureMCTSPlayer(Player):
    def __init__(self, n_simulations=100, c_puct=1.5, n_rollouts_per_leaf=4, name="pure-mcts"):
        self.n_simulations = n_simulations
        self.c_puct = c_puct
        self.n_rollouts_per_leaf = n_rollouts_per_leaf
        self.name = name

    def select_move(self, game, state, rng):
        mcts = RolloutMCTS(game, n_rollouts_per_leaf=self.n_rollouts_per_leaf,
                            c_puct=self.c_puct, n_simulations=self.n_simulations, rng=rng)
        visit_counts = mcts.run(state, add_root_noise=False)
        return sample_action(visit_counts, temperature=0.0, rng=rng)


# ----------------------------------------------------------------------
# (a) Minimax-oracle "never loses to perfect play" invariant
# ----------------------------------------------------------------------

def oracle_invariant_check(game, agent: Player, rng: np.random.Generator,
                            max_states: int = 20000) -> Tuple[bool, dict]:
    """Exhaustively (bounded by max_states as a safety valve) explores the
    real game tree. At every state where it is the ORACLE's turn, branches
    over ALL of the oracle's game-theoretically-optimal moves (true
    "perfect play" is not required to be unique). At every state where it
    is the AGENT's turn, takes the agent's single deterministic move.
    Fails loudly (returns False + the losing line) the first time this
    ever reaches a terminal state that is a loss for the agent.

    Runs the check with the agent playing BOTH sides (agent-as-X from the
    empty board, agent-as-O after every possible X opening), which is the
    "either side" requirement.
    """
    assert game is TicTacToe, "oracle_invariant_check is Tic-Tac-Toe-specific (has a minimax oracle)"
    visited = 0
    losing_lines: List[list] = []

    def recurse(state, agent_player: int, line: list):
        nonlocal visited
        visited += 1
        if visited > max_states:
            return
        if game.is_terminal(state):
            outcome = game.outcome_for(state, agent_player)
            if outcome < 0:
                losing_lines.append(list(line))
            return
        mover = game.current_player(state)
        if mover == agent_player:
            a = agent.select_move(game, state, rng)
            child = game.apply_move(state, a)
            recurse(child, agent_player, line + [("agent", a)])
        else:
            for a in best_moves(state):
                child = game.apply_move(state, a)
                recurse(child, agent_player, line + [("oracle", a)])

    for agent_player in (1, -1):
        recurse(game.initial_state(), agent_player, [])

    passed = len(losing_lines) == 0
    return passed, {
        "states_visited": visited,
        "losing_lines_found": len(losing_lines),
        "example_losing_line": losing_lines[0] if losing_lines else None,
    }


# ----------------------------------------------------------------------
# (b) Round-robin tournament + sequential Elo
# ----------------------------------------------------------------------

def play_game(game, player_x: Player, player_o: Player, rng: np.random.Generator) -> int:
    """player_x moves as +1, player_o moves as -1 (Sente's absolute
    player-id convention). Returns the absolute winner: +1, -1, or 0."""
    state = game.initial_state()
    while not game.is_terminal(state):
        mover = game.current_player(state)
        player = player_x if mover == 1 else player_o
        a = player.select_move(game, state, rng)
        state = game.apply_move(state, a)
    return game.winner(state)


def round_robin(game, players: Dict[str, Player], games_per_pairing: int,
                 rng: np.random.Generator) -> Tuple[List[Tuple[str, str, float]], Dict[str, dict]]:
    """Every unordered pair of distinct players plays `games_per_pairing`
    games with colors alternating (split as evenly as possible). Returns
    (raw_results, summary) where raw_results is a flat list of
    (name_a, name_b, score_a) used to feed sequential Elo, and summary is
    a per-player {wins, losses, draws, games} dict.
    """
    names = list(players.keys())
    raw_results: List[Tuple[str, str, float]] = []
    summary = {n: {"wins": 0, "losses": 0, "draws": 0, "games": 0} for n in names}

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            for g in range(games_per_pairing):
                a_is_x = (g % 2 == 0)
                px, po = (players[a], players[b]) if a_is_x else (players[b], players[a])
                w = play_game(game, px, po, rng)
                if w == 0:
                    score_a = 0.5
                    summary[a]["draws"] += 1
                    summary[b]["draws"] += 1
                else:
                    a_won = (w == 1) == a_is_x
                    score_a = 1.0 if a_won else 0.0
                    summary[a]["wins" if a_won else "losses"] += 1
                    summary[b]["losses" if a_won else "wins"] += 1
                summary[a]["games"] += 1
                summary[b]["games"] += 1
                raw_results.append((a, b, score_a))
    return raw_results, summary


def compute_elo(names: List[str], raw_results: List[Tuple[str, str, float]],
                 k: float = 24.0, base: float = 1200.0, rng: Optional[np.random.Generator] = None) -> Dict[str, float]:
    """Simple sequential Elo: process games in random order, standard
    logistic expected-score update. Good enough for a relative ladder
    across a fixed small set of players/checkpoints -- not claimed to be
    a rigorous rating with confidence intervals."""
    rng = rng or np.random.default_rng(0)
    ratings = {n: base for n in names}
    order = list(range(len(raw_results)))
    rng.shuffle(order)
    for idx in order:
        a, b, score_a = raw_results[idx]
        ra, rb = ratings[a], ratings[b]
        expected_a = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        ratings[a] = ra + k * (score_a - expected_a)
        ratings[b] = rb + k * ((1 - score_a) - (1 - expected_a))
    return ratings
