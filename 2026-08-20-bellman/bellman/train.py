"""CLI: train and evaluate every agent, writing JSON logs to results/ that
viz.py turns into the interactive HTML report.

    python -m bellman.train qlearning
    python -m bellman.train sarsa
    python -m bellman.train cliff-compare
    python -m bellman.train dqn
    python -m bellman.train reinforce
    python -m bellman.train ablation
    python -m bellman.train demo
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .envs.gridworld import make_simple_grid, make_cliff_walking
from .envs.cartpole import CartPole
from .agents.qlearning import QLearningAgent, SarsaAgent, run_episode, train as train_td
from .agents.dqn import DQNAgent, train as train_dqn, evaluate as evaluate_dqn
from .agents.reinforce import ReinforceAgent, train as train_reinforce, evaluate as evaluate_reinforce
from .verify import verify_against_value_iteration, greedy_path, cliff_edge_fraction

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def _save(name, payload):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"wrote {path}")
    return path


def _moving_avg(xs, window=20):
    out = []
    for i in range(len(xs)):
        lo = max(0, i - window + 1)
        chunk = xs[lo : i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def _verify_and_print(env, agent, gamma, label):
    result = verify_against_value_iteration(env, agent, gamma)
    print(
        f"{label}: greedy rollout from start achieves optimal return "
        f"({result['achieved_return']:.4f} vs V*={result['optimal_return']:.4f}) = {result['optimal_rollout']}; "
        f"table-wide: {result['action_matches']}/{result['total_states']} exact action match, "
        f"{result['value_close']}/{result['total_states']} value within 0.5"
    )
    return result


def _grid_layout(env):
    """A JSON-serializable description of a GridWorld's static layout, for
    the HTML report to draw the grid, walls, cliffs, start, and goal."""
    return {
        "width": env.width, "height": env.height,
        "start": list(env.start_rc), "goal": list(env.goal_rc),
        "walls": [list(w) for w in sorted(env.walls)],
        "cliffs": [list(c) for c in sorted(env.cliffs)],
    }


def cmd_qlearning(args):
    env = make_simple_grid()
    agent = QLearningAgent(
        env.n_states, env.n_actions, alpha=args.alpha, gamma=args.gamma,
        epsilon=1.0, epsilon_decay=0.99, epsilon_min=0.001, seed=args.seed,
    )
    t0 = time.time()
    returns = train_td(env, agent, args.episodes, max_steps=env.max_steps)
    elapsed = time.time() - t0
    print(f"Q-learning: {args.episodes} episodes in {elapsed:.2f}s")
    verification = _verify_and_print(env, agent, args.gamma, "Q-learning")

    _save("qlearning_simplegrid", {
        "agent": "qlearning", "env": "simple_grid",
        "episodes": args.episodes, "returns": returns,
        "moving_avg": _moving_avg(returns),
        "elapsed_sec": elapsed, **verification,
        "layout": _grid_layout(env), "policy": agent.greedy_policy(), "Q": agent.Q,
    })
    return verification["optimal_rollout"]


def cmd_sarsa(args):
    env = make_simple_grid()
    agent = SarsaAgent(
        env.n_states, env.n_actions, alpha=args.alpha, gamma=args.gamma,
        epsilon=1.0, epsilon_decay=0.99, epsilon_min=0.001, seed=args.seed,
    )
    t0 = time.time()
    returns = train_td(env, agent, args.episodes, max_steps=env.max_steps)
    elapsed = time.time() - t0
    print(f"SARSA: {args.episodes} episodes in {elapsed:.2f}s")
    verification = _verify_and_print(env, agent, args.gamma, "SARSA")

    _save("sarsa_simplegrid", {
        "agent": "sarsa", "env": "simple_grid",
        "episodes": args.episodes, "returns": returns,
        "moving_avg": _moving_avg(returns),
        "elapsed_sec": elapsed, **verification,
        "layout": _grid_layout(env), "policy": agent.greedy_policy(), "Q": agent.Q,
    })
    return verification["optimal_rollout"]


def cmd_cliff_compare(args):
    results = {}
    for name, cls in (("qlearning", QLearningAgent), ("sarsa", SarsaAgent)):
        env = make_cliff_walking()
        agent = cls(
            env.n_states, env.n_actions, alpha=0.5, gamma=1.0,
            epsilon=0.1, epsilon_decay=1.0, epsilon_min=0.1, seed=args.seed,
        )
        returns = train_td(env, agent, args.episodes, max_steps=env.max_steps)
        policy = agent.greedy_policy()
        path = greedy_path(env, policy)
        edge_fraction = cliff_edge_fraction(env, path)
        # The risky optimal path walks the entire edge row; a safer path
        # only ever touches it in passing near start/goal. >50% is "hugs it".
        hugs_cliff = edge_fraction > 0.5
        results[name] = {
            "returns": returns,
            "moving_avg": _moving_avg(returns),
            "final_avg_last50": sum(returns[-50:]) / len(returns[-50:]),
            "path": path,
            "hugs_cliff_edge": hugs_cliff,
            "edge_fraction": edge_fraction,
        }
        print(f"{name}: final avg return (last 50 eps) = {results[name]['final_avg_last50']:.1f}, "
              f"path length = {len(path)}, edge-row fraction = {edge_fraction:.2f}, hugs cliff edge = {hugs_cliff}")

    # The textbook divergence: Q-learning's greedy path should hug the row
    # directly above the cliff (shorter, riskier); SARSA's should not.
    diverged = results["qlearning"]["hugs_cliff_edge"] and not results["sarsa"]["hugs_cliff_edge"]
    print(f"Q-learning-vs-SARSA divergence reproduced: {diverged}")

    _save("cliff_compare", {
        "episodes": args.episodes, **results, "diverged": diverged,
        "layout": _grid_layout(make_cliff_walking()),
    })
    return diverged


def _capture_replay(select_action_fn, seed=1000, max_steps=500):
    """Runs one real greedy evaluation episode on a fresh CartPole and
    records its full state trajectory, for the HTML report's canvas replay
    — actual recorded physics frames from the actual trained agent, not a
    canned/scripted animation."""
    env = CartPole(max_steps=max_steps, seed=seed)
    state = env.reset()
    states = [list(state)]
    for _ in range(max_steps):
        action = select_action_fn(state)
        state, reward, done, _ = env.step(action)
        states.append(list(state))
        if done:
            break
    return states


def _train_dqn_variant(episodes, seed, no_replay=False, no_target=False, max_steps=500, capture_replay=False):
    """Trains one DQN configuration and returns a result dict with
    everything both `dqn` and `ablation` need — training curve, held-out
    eval return, and a max-drawdown instability metric (the largest drop
    from any earlier peak of the training moving-average return, i.e. how
    badly and how far training regressed after once doing well). A single
    run's final number is noisy; max-drawdown captures the "learned fine,
    then collapsed" failure mode DQN without a target network is known
    for, even on a run whose *final* eval happens to land fine anyway.
    """
    env = CartPole(max_steps=max_steps, seed=seed)
    agent = DQNAgent(
        state_dim=4, n_actions=2, hidden=(64, 64), lr=1e-3, gamma=0.99,
        epsilon=1.0, epsilon_decay=0.99, epsilon_min=0.05,
        buffer_capacity=20_000, batch_size=64, target_update_freq=200,
        use_replay=not no_replay, use_target_network=not no_target,
        seed=seed,
    )
    t0 = time.time()
    returns, losses = train_dqn(env, agent, episodes, max_steps=max_steps)
    elapsed = time.time() - t0

    eval_env = CartPole(max_steps=max_steps, seed=seed)
    eval_returns = evaluate_dqn(eval_env, agent, 20, max_steps=max_steps, seeds=list(range(1000, 1020)))
    avg_eval = sum(eval_returns) / len(eval_returns)

    mov_avg = _moving_avg(returns)
    peak = float("-inf")
    max_drawdown = 0.0
    for v in mov_avg:
        peak = max(peak, v)
        max_drawdown = max(max_drawdown, peak - v)

    result = {
        "use_replay": agent.use_replay, "use_target_network": agent.use_target_network,
        "episodes": episodes, "seed": seed, "returns": returns,
        "moving_avg": mov_avg, "losses": losses,
        "eval_returns": eval_returns, "eval_avg": avg_eval,
        "max_drawdown": max_drawdown, "elapsed_sec": elapsed,
    }
    if capture_replay:
        result["replay"] = _capture_replay(
            lambda s: agent.select_action(s, greedy=True), seed=1000, max_steps=max_steps
        )
    return result


def cmd_dqn(args):
    result = _train_dqn_variant(args.episodes, args.seed, args.no_replay, args.no_target, capture_replay=True)
    print(f"DQN ({'replay' if result['use_replay'] else 'no-replay'}, "
          f"{'target-net' if result['use_target_network'] else 'no-target-net'}): "
          f"{args.episodes} episodes in {result['elapsed_sec']:.2f}s, "
          f"eval avg return = {result['eval_avg']:.1f}, max drawdown = {result['max_drawdown']:.1f}")

    name = args.name or "dqn_cartpole"
    _save(name, {"agent": "dqn", "env": "cartpole", **result})
    return result["eval_avg"]


def cmd_reinforce(args):
    env = CartPole(max_steps=500, seed=args.seed)
    agent = ReinforceAgent(state_dim=4, n_actions=2, hidden=(64,), gamma=0.99, seed=args.seed)
    t0 = time.time()
    returns = train_reinforce(env, agent, args.episodes, max_steps=500)
    elapsed = time.time() - t0

    eval_env = CartPole(max_steps=500, seed=args.seed)
    eval_returns = evaluate_reinforce(eval_env, agent, 20, max_steps=500, seeds=list(range(1000, 1020)))
    avg_eval = sum(eval_returns) / len(eval_returns)
    print(f"REINFORCE: {args.episodes} episodes in {elapsed:.2f}s, eval avg return = {avg_eval:.1f}")
    replay = _capture_replay(lambda s: agent.select_action(s, greedy=True), seed=1000, max_steps=500)

    _save("reinforce_cartpole", {
        "agent": "reinforce", "env": "cartpole",
        "episodes": args.episodes, "returns": returns,
        "moving_avg": _moving_avg(returns), "replay": replay,
        "eval_returns": eval_returns, "eval_avg": avg_eval,
        "elapsed_sec": elapsed,
    })
    return avg_eval


def cmd_ablation(args):
    """Trains full DQN, DQN-without-replay, and DQN-without-a-target-network
    across `args.n_seeds` seeds each (a single training run is too noisy
    to honestly attribute a good/bad outcome to the ablated component —
    see REVIEW.md). Reports, per variant, the mean +- std of both the
    held-out eval return and the max-drawdown instability metric."""
    variants = [
        ("full", False, False),
        ("no_replay", True, False),
        ("no_target", False, True),
    ]
    seeds = [args.seed + i for i in range(args.n_seeds)]
    summary = {}
    for label, no_replay, no_target in variants:
        runs = []
        for seed in seeds:
            result = _train_dqn_variant(args.episodes, seed, no_replay, no_target)
            _save(f"dqn_ablation_{label}_seed{seed}", {"agent": "dqn", "env": "cartpole", **result})
            runs.append(result)
            print(f"  [{label}] seed={seed}: eval_avg={result['eval_avg']:.1f}, "
                  f"max_drawdown={result['max_drawdown']:.1f}")
        eval_avgs = [r["eval_avg"] for r in runs]
        drawdowns = [r["max_drawdown"] for r in runs]
        summary[label] = {
            "seeds": seeds,
            "eval_avg_mean": sum(eval_avgs) / len(eval_avgs),
            "eval_avg_std": _stdev(eval_avgs),
            "max_drawdown_mean": sum(drawdowns) / len(drawdowns),
            "max_drawdown_std": _stdev(drawdowns),
            "example_moving_avg": runs[0]["moving_avg"],  # for the HTML report's example curve
        }

    print(f"\nAblation summary ({args.n_seeds} seeds each, eval avg return over "
          f"20 held-out episodes, max-drawdown of the training moving average):")
    for label, d in summary.items():
        print(f"  {label:10s}: eval {d['eval_avg_mean']:6.1f} +- {d['eval_avg_std']:5.1f}   "
              f"drawdown {d['max_drawdown_mean']:6.1f} +- {d['max_drawdown_std']:5.1f}")
    _save("dqn_ablation_summary", {"episodes": args.episodes, "n_seeds": args.n_seeds, "variants": summary})
    return summary


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def cmd_demo(args):
    """A fast, condensed run of every feature — used by demo.sh. Smaller
    episode counts than the 'real' commands so it finishes quickly, but
    every code path (including the value-iteration cross-check and the
    cliff-walking divergence) actually runs for real."""
    ok = True
    print("=== [1/6] Tabular Q-learning vs value iteration ===")
    ok &= bool(cmd_qlearning(argparse.Namespace(episodes=args.episodes, alpha=0.3, gamma=0.99, seed=args.seed)))

    print("\n=== [2/6] SARSA vs value iteration ===")
    ok &= bool(cmd_sarsa(argparse.Namespace(episodes=args.episodes, alpha=0.3, gamma=0.99, seed=args.seed)))

    print("\n=== [3/6] Cliff Walking: Q-learning vs SARSA divergence ===")
    ok &= bool(cmd_cliff_compare(argparse.Namespace(episodes=max(200, args.episodes), seed=args.seed)))

    print("\n=== [4/6] DQN on CartPole ===")
    dqn_avg = cmd_dqn(argparse.Namespace(
        episodes=args.cartpole_episodes, seed=args.seed, no_replay=False, no_target=False, name="dqn_cartpole",
    ))

    print("\n=== [5/6] REINFORCE on CartPole ===")
    reinforce_avg = cmd_reinforce(argparse.Namespace(episodes=args.cartpole_episodes, seed=args.seed))

    print("\n=== [6/6] DQN ablation (full vs no-replay vs no-target) ===")
    ablation = cmd_ablation(argparse.Namespace(
        episodes=args.ablation_episodes, seed=args.seed, n_seeds=args.ablation_seeds,
    ))

    print(f"\ndemo summary: gridworld_ok={ok}, dqn_eval_avg={dqn_avg:.1f}, "
          f"reinforce_eval_avg={reinforce_avg:.1f}")
    return ok


def build_parser():
    p = argparse.ArgumentParser(prog="bellman-train", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp, episodes_default):
        sp.add_argument("--episodes", type=int, default=episodes_default)
        sp.add_argument("--seed", type=int, default=0)

    sp = sub.add_parser("qlearning"); add_common(sp, 800); sp.add_argument("--alpha", type=float, default=0.3); sp.add_argument("--gamma", type=float, default=0.99)
    sp = sub.add_parser("sarsa"); add_common(sp, 800); sp.add_argument("--alpha", type=float, default=0.3); sp.add_argument("--gamma", type=float, default=0.99)
    sp = sub.add_parser("cliff-compare"); add_common(sp, 500)
    sp = sub.add_parser("dqn"); add_common(sp, 300); sp.add_argument("--no-replay", action="store_true"); sp.add_argument("--no-target", action="store_true"); sp.add_argument("--name", default=None)
    sp = sub.add_parser("reinforce"); add_common(sp, 500)
    sp = sub.add_parser("ablation"); add_common(sp, 250); sp.add_argument("--n-seeds", type=int, default=3)
    sp = sub.add_parser("demo")
    sp.add_argument("--episodes", type=int, default=800)
    sp.add_argument("--cartpole-episodes", type=int, default=150)
    sp.add_argument("--ablation-episodes", type=int, default=120)
    sp.add_argument("--ablation-seeds", type=int, default=2)
    sp.add_argument("--seed", type=int, default=0)

    return p


COMMANDS = {
    "qlearning": cmd_qlearning,
    "sarsa": cmd_sarsa,
    "cliff-compare": cmd_cliff_compare,
    "dqn": cmd_dqn,
    "reinforce": cmd_reinforce,
    "ablation": cmd_ablation,
    "demo": cmd_demo,
}


def _validate_args(parser, args):
    """Rejects nonsensical numeric input early with a clear message,
    instead of e.g. silently training on `range(-5)` (0 real episodes)
    while still printing "-5 episodes" and writing a confusing "training
    failed to converge" result to disk."""
    for attr, label in (
        ("episodes", "--episodes"),
        ("cartpole_episodes", "--cartpole-episodes"),
        ("ablation_episodes", "--ablation-episodes"),
        ("n_seeds", "--n-seeds"),
        ("ablation_seeds", "--ablation-seeds"),
    ):
        if hasattr(args, attr) and getattr(args, attr) < 0:
            parser.error(f"{label} must be >= 0, got {getattr(args, attr)}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    COMMANDS[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
