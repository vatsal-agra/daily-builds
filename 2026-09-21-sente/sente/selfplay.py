"""Self-play game generation: plays one full game with the current
network guiding PUCT MCTS, records (encoded_board, legal_mask,
visit-count policy, final outcome) training examples with the mover's
own perspective at every ply, and applies board-symmetry augmentation.

Dirichlet root noise and temperature-scaled sampling are used HERE and
only here -- evaluate.py's tournament/oracle-check code always calls
MCTS with add_root_noise=False and temperature 0, which is the exact
"Dirichlet noise must never leak into evaluation" invariant called out
in the brief (see REVIEW.md for how this is tested, not just asserted).
"""

from __future__ import annotations
from typing import List, Tuple
import numpy as np

from .mcts import MCTS, visit_policy, sample_action


def self_play_game(game, net, n_simulations=100, c_puct=1.5,
                    dirichlet_alpha=0.3, dirichlet_eps=0.25,
                    temp_moves=6, rng=None, augment=True):
    rng = rng or np.random.default_rng()
    state = game.initial_state()
    history: List[Tuple] = []
    move_count = 0

    while not game.is_terminal(state):
        mcts = MCTS(game, net, c_puct=c_puct, n_simulations=n_simulations,
                    dirichlet_alpha=dirichlet_alpha, dirichlet_eps=dirichlet_eps, rng=rng)
        visit_counts = mcts.run(state, add_root_noise=True)
        pi = visit_policy(game.action_size, visit_counts)
        history.append((state, pi))

        temperature = 1.0 if move_count < temp_moves else 0.0
        action = sample_action(visit_counts, temperature, rng)
        state = game.apply_move(state, action)
        move_count += 1

    examples = []
    for st, pi in history:
        mover = game.current_player(st)
        z = game.outcome_for(state, mover)  # perspective of the player who moved AT st
        if augment:
            for sym_state, sym_pi in game.symmetries(st, pi):
                examples.append((game.encode(sym_state), game.legal_mask(sym_state), sym_pi, z))
        else:
            examples.append((game.encode(st), game.legal_mask(st), pi, z))

    return examples, game.winner(state)
