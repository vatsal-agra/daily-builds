"""`bellman` command-line entry point.

Subcommands: gridworld / cartpole / blackjack / oracle / viz / demo.
"""
import argparse
import sys

from .envs import GridWorldEnv
from .dp import value_iteration, policy_iteration, greedy_rollout_return
from .train import run_gridworld_experiment, run_cartpole_experiment, run_blackjack_experiment
from .report import build_report


def positive_int(value):
    """argparse type= validator: rejects 0/negative/non-integer episode
    counts at parse time with a clean message, instead of silently running
    a 0-episode "experiment" that produces meaningless output (an untrained,
    all-zero Q-table's greedy rollout just bounces off the wall until the
    step cap -- garbage that looks superficially like a real result)."""
    try:
        iv = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}")
    if iv < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {iv}")
    return iv


def cmd_oracle(args):
    env = GridWorldEnv(rows=args.rows, cols=args.cols, slip_prob=0.0)
    V, policy = value_iteration(env, gamma=1.0)
    V2, policy2 = policy_iteration(env, gamma=1.0)
    agree = all(abs(V[s] - V2[s]) < 1e-3 for s in env.states)
    print(f"Value Iteration vs Policy Iteration agree on V*: {agree}")
    print(f"V*(start) = {V[env.encode(*env.start)]:.2f}")
    print(f"Optimal rollout return = {greedy_rollout_return(env, policy):.1f}")
    print()
    print(env.render_ascii(policy=policy))
    return 0 if agree else 1


def cmd_gridworld(args):
    result = run_gridworld_experiment(rows=args.rows, cols=args.cols,
                                       slip_prob=args.slip, episodes=args.episodes, seed=args.seed)
    print(f"DP-optimal return:          {result['optimal_return']:.1f}")
    print(f"Q-Learning greedy return:   {result['q_learning']['greedy_return']:.1f}"
          + ("  (matches optimal)" if result['q_learning']['greedy_return'] == result['optimal_return'] else ""))
    print(f"SARSA greedy return:        {result['sarsa']['greedy_return']:.1f}")
    print(f"SARSA(lambda) greedy return:{result['sarsa_lambda']['greedy_return']:.1f}")
    print()
    env = GridWorldEnv(rows=args.rows, cols=args.cols)
    print("Q-Learning's learned policy:")
    print(env.render_ascii(policy=result['q_learning']['policy']))
    return 0


def cmd_cartpole(args):
    result = run_cartpole_experiment(episodes=args.episodes, seed=args.seed)
    print(f"Trained policy eval mean:   {result['eval_mean']:.1f} steps (cap {result['eval_cap']})")
    print(f"Random baseline eval mean:  {result['baseline_mean']:.1f} steps")
    print(f"Improvement:                x{result['eval_mean'] / result['baseline_mean']:.1f}")
    print(f"Training time:              {result['train_time_sec']:.1f}s")
    return 0


def cmd_blackjack(args):
    result = run_blackjack_experiment(episodes=args.episodes, seed=args.seed)
    print(f"Agreement vs. optimal policy: {result['agreement'] * 100:.1f}% "
          f"({result['states_compared']} states)")
    print(f"Training episodes: {result['episodes']}, time: {result['train_time_sec']:.1f}s")
    if result['disagreements']:
        print(f"Disagreements ({len(result['disagreements'])}):")
        for d in result['disagreements'][:10]:
            print(f"  state={d['state']} learned={d['learned']} optimal={d['optimal']}")
    return 0


def cmd_viz(args):
    bundle = {
        "gridworld": run_gridworld_experiment(episodes=args.gridworld_episodes, seed=args.seed),
        "cartpole": run_cartpole_experiment(episodes=args.cartpole_episodes, seed=args.seed),
    }
    if not args.skip_blackjack:
        bundle["blackjack"] = run_blackjack_experiment(episodes=args.blackjack_episodes, seed=args.seed)
    out = build_report(bundle, args.out)
    print(f"Wrote {out}")
    return 0


def _parsed(*argv):
    """Parse argv through the real subparsers so `demo` always runs each
    subcommand with its actual current defaults -- not a second, hand-copied
    set of numbers here that could silently drift out of sync with them."""
    return build_parser().parse_args(list(argv))


def cmd_demo(args):
    print("=== Bellman demo: exercising every feature end to end ===\n")
    print("--- DP oracle ---")
    cmd_oracle(_parsed("oracle"))
    print("\n--- GridWorld TD control (Q-Learning / SARSA / SARSA(lambda)) ---")
    cmd_gridworld(_parsed("gridworld"))
    print("\n--- CartPole REINFORCE ---")
    cmd_cartpole(_parsed("cartpole"))
    print("\n--- Blackjack Monte Carlo Exploring Starts ---")
    cmd_blackjack(_parsed("blackjack"))
    print("\n--- Building interactive HTML report ---")
    cmd_viz(_parsed("viz", "--out", "viz/report.html"))
    print("\n=== Demo complete ===")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="bellman", description="A from-scratch reinforcement-learning laboratory.")
    sub = p.add_subparsers(dest="command", required=True)

    op = sub.add_parser("oracle", help="Solve GridWorld exactly via Value/Policy Iteration (ground truth).")
    op.add_argument("--rows", type=int, default=4)
    op.add_argument("--cols", type=int, default=12)
    op.set_defaults(func=cmd_oracle)

    gp = sub.add_parser("gridworld", help="Train Q-Learning/SARSA/SARSA(lambda) on Cliff Walking.")
    gp.add_argument("--rows", type=int, default=4)
    gp.add_argument("--cols", type=int, default=12)
    gp.add_argument("--slip", type=float, default=0.0, help="stochastic slip probability (0 = classic)")
    gp.add_argument("--episodes", type=positive_int, default=500)
    gp.add_argument("--seed", type=int, default=0)
    gp.set_defaults(func=cmd_gridworld)

    cp = sub.add_parser("cartpole", help="Train a REINFORCE policy-gradient agent on CartPole.")
    cp.add_argument("--episodes", type=positive_int, default=400)
    cp.add_argument("--seed", type=int, default=1)
    cp.set_defaults(func=cmd_cartpole)

    bp = sub.add_parser("blackjack", help="Train Monte Carlo Exploring Starts on Blackjack.")
    bp.add_argument("--episodes", type=positive_int, default=500_000)
    bp.add_argument("--seed", type=int, default=0)
    bp.set_defaults(func=cmd_blackjack)

    vp = sub.add_parser("viz", help="Run all experiments and build the interactive HTML report.")
    vp.add_argument("--out", default="viz/report.html")
    vp.add_argument("--gridworld-episodes", type=positive_int, default=500)
    vp.add_argument("--cartpole-episodes", type=positive_int, default=400)
    vp.add_argument("--blackjack-episodes", type=positive_int, default=500_000)
    vp.add_argument("--skip-blackjack", action="store_true")
    vp.add_argument("--seed", type=int, default=0)
    vp.set_defaults(func=cmd_viz)

    dp = sub.add_parser("demo", help="Run every feature end to end with a printed summary.")
    dp.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError) as e:
        # Domain errors from bellman/envs.py, dp.py, etc. (e.g. GridWorldEnv
        # rejecting a degenerate --rows/--cols combination) are meaningful,
        # already-clear messages -- a raw Python traceback would bury that
        # message under implementation detail the user doesn't need.
        print(f"bellman: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
