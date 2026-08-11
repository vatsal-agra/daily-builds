"""bellman CLI: train/evaluate/compare every environment and agent, and
build the HTML report.

    python -m bellman.cli dp <env>
    python -m bellman.cli tabular <agent> <env> [--episodes N]
    python -m bellman.cli cliff-compare
    python -m bellman.cli dqn [--episodes N]
    python -m bellman.cli reinforce [--episodes N]
    python -m bellman.cli report [--out report.html]
"""
import argparse
import statistics
import sys

from .envs import gridworld, cartpole
from .agents import dp, tabular, dqn, reinforce


def positive_int(raw):
    """argparse type for --episodes/--seed-style flags: rejects
    zero/negative counts with a clean argparse error instead of letting
    an empty-episode run crash deep inside statistics.mean() on an empty
    reward list."""
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer")
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return value


def cmd_dp(args):
    env = gridworld.make(args.env)
    V, Q, policy = dp.value_iteration(env)
    print(env.render_ascii())
    print()
    print(f"V*(start) = {V[env.start_state]:.4f}")
    print("optimal policy (state -> action):")
    for s in sorted(policy):
        if env.is_terminal(s) or env.is_wall(s):
            continue
        print(f"  {env.rc(s)}: {gridworld.ACTION_NAMES[policy[s]]}")


def cmd_tabular(args):
    env = gridworld.make(args.env)
    agent = tabular.make(args.agent, env, seed=args.seed)
    rewards = agent.train(episodes=args.episodes)
    V, Q, opt_policy = dp.value_iteration(gridworld.make(args.env))
    learned = agent.greedy_policy()
    matches = sum(1 for s in opt_policy if not env.is_terminal(s) and opt_policy[s] == learned.get(s))
    total = sum(1 for s in opt_policy if not env.is_terminal(s))
    print(f"{agent.name} on {env.name}: {args.episodes} episodes")
    print(f"  last 50 episodes mean reward: {statistics.mean(rewards[-50:]):.2f}")
    print(f"  greedy policy matches DP-optimal policy: {matches}/{total} states")


def cmd_cliff_compare(args):
    """Reproduces the classic Q-learning-vs-SARSA divergence on
    CliffWalking: Q-learning's greedy policy walks the cliff edge
    (shortest path), SARSA's stays safely away from it."""
    def path_of(policy_env_pair):
        policy, env = policy_env_pair
        s = env.reset()
        path = [env.rc(s)]
        for _ in range(200):
            a = policy[s]
            s, r, done, trunc = env.step(a)
            path.append(env.rc(s))
            if done or trunc:
                break
        return path

    ql = tabular.QLearning(gridworld.make("cliffwalking"), alpha=0.5, gamma=1.0,
                            seed=args.seed, schedule=tabular.EpsilonGreedy(1.0, 0.1, 300))
    ql.train(episodes=args.episodes)
    sarsa = tabular.Sarsa(gridworld.make("cliffwalking"), alpha=0.5, gamma=1.0,
                           seed=args.seed, schedule=tabular.EpsilonGreedy(1.0, 0.1, 300))
    sarsa.train(episodes=args.episodes)

    ql_path = path_of((ql.greedy_policy(), gridworld.make("cliffwalking")))
    sarsa_path = path_of((sarsa.greedy_policy(), gridworld.make("cliffwalking")))
    print("Q-learning (off-policy) greedy path:", ql_path)
    print("SARSA (on-policy) greedy path:      ", sarsa_path)
    print(f"Q-learning path length: {len(ql_path)}, SARSA path length: {len(sarsa_path)}")


def cmd_dqn(args):
    env = cartpole.CartPoleEnv(seed=args.seed)

    def cb(ep, r, eps):
        if ep % max(1, args.episodes // 10) == 0:
            print(f"  episode {ep:4d}  reward {r:6.1f}  epsilon {eps:.3f}")

    agent, rewards, losses = dqn.train(env, episodes=args.episodes, seed=args.seed, on_episode=cb)
    print(f"training complete. last 30 episodes mean reward: {statistics.mean(rewards[-30:]):.2f}")
    eval_env = cartpole.CartPoleEnv(seed=args.seed + 1000)
    evals = dqn.evaluate(eval_env, agent, episodes=30)
    print(f"greedy evaluation over 30 episodes: mean={statistics.mean(evals):.2f} "
          f"min={min(evals):.1f} max={max(evals):.1f}")


def cmd_reinforce(args):
    env = cartpole.CartPoleEnv(seed=args.seed)

    def cb(ep, r):
        if ep % max(1, args.episodes // 10) == 0:
            print(f"  episode {ep:4d}  reward {r:6.1f}")

    agent, rewards = reinforce.train(env, episodes=args.episodes, seed=args.seed, on_episode=cb)
    print(f"training complete. last 30 episodes mean reward: {statistics.mean(rewards[-30:]):.2f}")
    eval_env = cartpole.CartPoleEnv(seed=args.seed + 1000)
    evals = reinforce.evaluate(eval_env, agent, episodes=30)
    print(f"greedy evaluation over 30 episodes: mean={statistics.mean(evals):.2f} "
          f"min={min(evals):.1f} max={max(evals):.1f}")


def cmd_report(args):
    from .viz import report

    path = report.build_report(out_path=args.out, seed=args.seed,
                                dqn_episodes=args.dqn_episodes,
                                reinforce_episodes=args.reinforce_episodes,
                                tabular_episodes=args.tabular_episodes)
    print(f"wrote {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bellman")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dp = sub.add_parser("dp", help="solve a gridworld env exactly with value iteration")
    p_dp.add_argument("env", choices=sorted(gridworld.REGISTRY))
    p_dp.set_defaults(func=cmd_dp)

    p_tab = sub.add_parser("tabular", help="train a tabular agent on a gridworld env")
    p_tab.add_argument("agent", choices=sorted(tabular.AGENTS))
    p_tab.add_argument("env", choices=sorted(gridworld.REGISTRY))
    p_tab.add_argument("--episodes", type=positive_int, default=800)
    p_tab.add_argument("--seed", type=int, default=0)
    p_tab.set_defaults(func=cmd_tabular)

    p_cliff = sub.add_parser("cliff-compare", help="Q-learning vs SARSA on CliffWalking")
    p_cliff.add_argument("--episodes", type=positive_int, default=800)
    p_cliff.add_argument("--seed", type=int, default=2)
    p_cliff.set_defaults(func=cmd_cliff_compare)

    p_dqn = sub.add_parser("dqn", help="train a Deep Q-Network on CartPole")
    p_dqn.add_argument("--episodes", type=positive_int, default=260)
    p_dqn.add_argument("--seed", type=int, default=0)
    p_dqn.set_defaults(func=cmd_dqn)

    p_re = sub.add_parser("reinforce", help="train a REINFORCE policy-gradient agent on CartPole")
    p_re.add_argument("--episodes", type=positive_int, default=350)
    p_re.add_argument("--seed", type=int, default=0)
    p_re.set_defaults(func=cmd_reinforce)

    p_rep = sub.add_parser("report", help="run everything and build the HTML report")
    p_rep.add_argument("--out", default="report.html")
    p_rep.add_argument("--seed", type=int, default=0)
    p_rep.add_argument("--dqn-episodes", type=positive_int, default=260)
    p_rep.add_argument("--reinforce-episodes", type=positive_int, default=350)
    p_rep.add_argument("--tabular-episodes", type=positive_int, default=800)
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
