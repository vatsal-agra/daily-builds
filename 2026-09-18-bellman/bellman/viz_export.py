"""Runs every algorithm in the package and serializes the results to JSON
for visualizer/index.html. This is the one script that ties the whole
project together end to end -- if it runs clean, every required feature
actually works, not just in isolation but wired into the same artifact a
human opens in a browser.
"""
import argparse
import json
import os
import random

from .envs.cliffwalking import (
    ACTION_NAMES, COLS, GOAL, ROWS, START, CliffWalking, is_cliff, to_rc,
)
from .envs.tictactoe import EMPTY_BOARD, apply_move, is_terminal, other_player, winner
from . import convergence, dp, td, minimax
from .selfplay import SelfPlayAgent
from .utils import rollout_policy

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "..", "visualizer", "data", "bellman_data.json")


def _grid_meta():
    return {
        "rows": ROWS,
        "cols": COLS,
        "start": list(START),
        "goal": list(GOAL),
        "cliff_cells": [
            [r, c] for r in range(ROWS) for c in range(COLS) if is_cliff(r, c)
        ],
    }


def _serialize_v(env, V):
    return {str(s): V[s] for s in env.states}


def _serialize_policy(env, policy):
    return {str(s): {"action": policy[s], "name": ACTION_NAMES[policy[s]]}
            for s in env.states}


def _trajectory_rc(states):
    return [list(to_rc(s)) for s in states]


def build_cliff_section(episodes=500, seed=42):
    env = CliffWalking()

    vi = dp.value_iteration(env)
    pi = dp.policy_iteration(env)
    assert all(abs(vi["V"][s] - pi["V"][s]) < 1e-6 for s in env.states), (
        "value iteration and policy iteration disagree -- oracle is broken"
    )

    sarsa_res = td.sarsa(env, episodes=episodes, alpha=0.5, epsilon=0.1, seed=seed)
    q_res = td.q_learning(env, episodes=episodes, alpha=0.5, epsilon=0.1, seed=seed)
    lambda_res = td.sarsa_lambda(
        env, episodes=episodes, alpha=0.1, epsilon=0.1, lam=0.9, seed=seed
    )

    speed = build_convergence_speed_comparison(env, seed=seed)

    sarsa_states, sarsa_return, sarsa_reached = rollout_policy(env, sarsa_res["policy"])
    q_states, q_return, q_reached = rollout_policy(env, q_res["policy"])
    lambda_states, lambda_return, lambda_reached = rollout_policy(env, lambda_res["policy"])

    def bundle(name, result, states, path_return, reached):
        exact_return = dp.policy_evaluation(env, result["policy"])[env.start_state]
        state_value = {
            s: max(result["Q"][(s, a)] for a in range(env.n_actions))
            for s in env.states
        }
        return {
            "name": name,
            "policy": _serialize_policy(env, result["policy"]),
            "V": _serialize_v(env, state_value),
            "returns": result["returns"],
            "moving_avg_return": _moving_average(result["returns"], 20),
            "trajectory": _trajectory_rc(states),
            "rollout_return": path_return,
            "rollout_reached_goal": reached,
            "exact_policy_value_at_start": exact_return,
        }

    return {
        "meta": _grid_meta(),
        "optimal": {
            "V": _serialize_v(env, vi["V"]),
            "policy": _serialize_policy(env, vi["policy"]),
            "value_iteration_iterations": vi["iterations"],
            "policy_iteration_iterations": pi["iterations"],
            "value_at_start": vi["V"][env.start_state],
        },
        "sarsa": bundle("SARSA (on-policy)", sarsa_res, sarsa_states, sarsa_return, sarsa_reached),
        "qlearning": bundle("Q-learning (off-policy)", q_res, q_states, q_return, q_reached),
        "sarsa_lambda": bundle(
            "SARSA(λ=0.9)", lambda_res, lambda_states, lambda_return, lambda_reached
        ),
        "convergence_speed": speed,
    }


def build_convergence_speed_comparison(env, seed):
    """SARSA vs SARSA(lambda) at matched alpha/epsilon: how many episodes
    until the greedy policy is at least a working (near-cliff-avoiding)
    path to the goal? Backs the PLAN.md stretch claim; failure here means
    that claim is false and the JSON must not silently ship it anyway."""
    checkpoints = [10, 25, 50, 75, 100, 150, 200, 300, 400, 500]
    threshold = -20.0
    shared_kwargs = dict(alpha=0.1, epsilon=0.1, seed=seed)

    sarsa_crossing, sarsa_curve = convergence.episodes_to_threshold(
        env, td.sarsa, checkpoints, threshold, **shared_kwargs
    )
    lambda_crossing, lambda_curve = convergence.episodes_to_threshold(
        env, td.sarsa_lambda, checkpoints, threshold, lam=0.9, **shared_kwargs
    )

    assert lambda_crossing is not None, (
        "SARSA(lambda) never reached a working Cliff Walking policy within "
        f"{checkpoints[-1]} episodes -- stretch feature claim is false"
    )
    assert sarsa_crossing is None or lambda_crossing < sarsa_crossing, (
        "SARSA(lambda) did not converge in fewer episodes than 1-step SARSA "
        f"at matched hyperparameters (lambda={lambda_crossing}, sarsa={sarsa_crossing})"
    )

    return {
        "checkpoints": checkpoints,
        "threshold": threshold,
        "alpha": shared_kwargs["alpha"],
        "epsilon": shared_kwargs["epsilon"],
        "sarsa_curve": sarsa_curve,
        "sarsa_lambda_curve": lambda_curve,
        "sarsa_crossing_episode": sarsa_crossing,
        "sarsa_lambda_crossing_episode": lambda_crossing,
    }


def _moving_average(values, window):
    out = []
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
            out.append(running / window)
        else:
            out.append(running / (i + 1))
    return out


def _play_greedy_game(agent):
    board = EMPTY_BOARD
    player = "X"
    trace = [{"board": list(board), "player": None}]
    while not is_terminal(board):
        action, _ = agent.choose_move_greedy(board, player)
        board = apply_move(board, action, player)
        trace.append({"board": list(board), "player": player, "action": action})
        player = other_player(player)
    return trace, winner(board)


def _evaluate_vs_oracle(agent, agent_player, n_games, seed):
    # Both the agent (greedy over its learned V) and the oracle (minimax)
    # are otherwise-deterministic; without randomized tie-breaking every
    # one of n_games would replay the exact same moves. Random tie-breaks
    # on both sides make each game genuinely different while every move
    # stays provably optimal, so "N games, zero losses" is honest -- not
    # the same single game counted N times.
    rng = random.Random(seed)
    outcomes = {"agent_win": 0, "oracle_win": 0, "draw": 0}
    for _ in range(n_games):
        board = EMPTY_BOARD
        player = "X"
        while not is_terminal(board):
            if player == agent_player:
                action, _ = agent.choose_move_greedy(board, player)
            else:
                action = minimax.best_move_random_tiebreak(board, player, rng)
            board = apply_move(board, action, player)
            player = other_player(player)
        w = winner(board)
        if w is None:
            outcomes["draw"] += 1
        elif w == agent_player:
            outcomes["agent_win"] += 1
        else:
            outcomes["oracle_win"] += 1
    return outcomes


def build_tictactoe_section(train_episodes=60000, eval_games=300, seed=7):
    # epsilon=0.3 (fairly high, sustained for the whole run rather than
    # decayed) matters more than it looks: at epsilon=0.1 the agent beats
    # a *deterministic* oracle every time but starts losing real games
    # once the oracle's own tie-breaks are randomized (see
    # best_move_random_tiebreak above), because self-play under low
    # exploration only ever visits a narrow slice of reachable boards and
    # never learns correct values for the ones a varied optimal opponent
    # can actually steer into. Verified stable (0 losses in 800 games
    # across 5 training seeds) at these settings before wiring it in here.
    agent = SelfPlayAgent(alpha=0.1, epsilon=0.3, seed=seed)
    training_outcomes = agent.train(train_episodes)

    eval_as_x = _evaluate_vs_oracle(agent, "X", eval_games, seed=100)
    eval_as_o = _evaluate_vs_oracle(agent, "O", eval_games, seed=200)
    assert eval_as_x["agent_win"] + eval_as_x["draw"] == eval_games, (
        "self-play agent lost a game to the perfect oracle as X"
    )
    assert eval_as_o["agent_win"] + eval_as_o["draw"] == eval_games, (
        "self-play agent lost a game to the perfect oracle as O"
    )

    sample_game, sample_winner = _play_greedy_game(agent)

    # Populate the oracle's memo table for every board reachable from an
    # empty board under alternating play (negamax visits every child while
    # deciding the root move, so a single root call already walks the
    # entire reachable game tree) and ship it so the visualizer's
    # play-against-the-agent board can also offer a provably-perfect
    # opponent with zero server round trips.
    minimax.best_move(EMPTY_BOARD, "X")
    oracle_table = {
        "".join(board) + player: {"score": score, "action": action}
        for (board, player), (score, action) in minimax.memo_snapshot().items()
    }
    value_table = {"".join(board): round(v, 4) for board, v in agent.V.items()}

    return {
        "training_episodes": train_episodes,
        "training_outcomes": training_outcomes,
        "states_learned": len(agent.V),
        "eval_vs_oracle": {"as_X": eval_as_x, "as_O": eval_as_o, "games_each": eval_games},
        "sample_greedy_vs_greedy_game": sample_game,
        "sample_game_winner": sample_winner,
        "agent_epsilon": agent.epsilon,
        "agent_alpha": agent.alpha,
        "value_table": value_table,
        "oracle_table": oracle_table,
    }


def build_all(episodes=500, ttt_episodes=60000, seed=42):
    return {
        "cliff": build_cliff_section(episodes=episodes, seed=seed),
        "tictactoe": build_tictactoe_section(train_episodes=ttt_episodes, seed=seed),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--ttt-episodes", type=int, default=60000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data = build_all(episodes=args.episodes, ttt_episodes=args.ttt_episodes, seed=args.seed)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f)
    print(f"wrote {args.out}")

    # Also emit a plain <script> file that assigns the same JSON to a
    # global, so index.html can be opened straight from disk (file://)
    # without hitting the fetch()-of-local-JSON CORS block most browsers
    # apply -- the .json file above still exists for tooling/tests that
    # want the data on its own.
    js_path = os.path.splitext(args.out)[0] + ".js"
    with open(js_path, "w") as f:
        f.write("var BELLMAN_DATA = ")
        json.dump(data, f)
        f.write(";\n")
    print(f"wrote {js_path}")
    print(
        "cliff: optimal V(start)=%.1f sarsa=%.1f qlearning=%.1f sarsa_lambda=%.1f"
        % (
            data["cliff"]["optimal"]["value_at_start"],
            data["cliff"]["sarsa"]["exact_policy_value_at_start"],
            data["cliff"]["qlearning"]["exact_policy_value_at_start"],
            data["cliff"]["sarsa_lambda"]["exact_policy_value_at_start"],
        )
    )
    print("tictactoe: eval vs oracle", data["tictactoe"]["eval_vs_oracle"])


if __name__ == "__main__":
    main()
