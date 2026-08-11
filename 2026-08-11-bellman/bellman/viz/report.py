"""Builds a single self-contained HTML report: it actually runs the DP
oracle, every tabular agent, and both cart-pole agents, then embeds the
real results (training curves, a recorded greedy-policy replay, a
value-function heatmap next to the DP oracle's true optimum) as JSON data
consumed by plain JS/Canvas -- no server, no client-side RL logic, no
placeholder numbers.
"""
import json
import statistics

from ..envs import gridworld, cartpole
from ..agents import dp, tabular, dqn, reinforce


def _replay_path(env, policy, max_steps=100):
    s = env.reset()
    path = [list(env.rc(s))]
    for _ in range(max_steps):
        a = policy.get(s)
        if a is None:
            break
        s, r, done, truncated = env.step(a)
        path.append(list(env.rc(s)))
        if done or truncated:
            break
    return path


def _gridworld_section(env_name, tabular_episodes, seed):
    env = gridworld.make(env_name)
    V, Q, opt_policy = dp.value_iteration(gridworld.make(env_name))

    curves = {}
    matches = {}
    final_paths = {}
    for agent_name in ("qlearning", "sarsa", "montecarlo"):
        agent = tabular.make(agent_name, gridworld.make(env_name), seed=seed)
        kw = {"max_steps": 150} if agent_name == "montecarlo" else {}
        rewards = agent.train(episodes=tabular_episodes, **kw)
        curves[agent_name] = _downsample(rewards, 120)
        learned = agent.greedy_policy()
        total = sum(1 for s in opt_policy if not env.is_terminal(s))
        match = sum(1 for s in opt_policy
                     if not env.is_terminal(s) and opt_policy[s] == learned.get(s))
        matches[agent_name] = {"matches": match, "total": total}
        final_paths[agent_name] = _replay_path(gridworld.make(env_name), learned)

    cells = []
    for r in range(env.n_rows):
        row = []
        for c in range(env.n_cols):
            s = env.state_of(r, c)
            kind = "empty"
            if s in env.walls:
                kind = "wall"
            elif s in env.goals:
                kind = "goal"
            elif s in env.holes:
                kind = "hole"
            elif s in env.cliffs:
                kind = "cliff"
            elif s == env.start_state:
                kind = "start"
            row.append({
                "kind": kind,
                "v": None if s in env.walls else round(V[s], 3),
                "action": opt_policy.get(s) if s not in env.walls and not env.is_terminal(s) else None,
            })
        cells.append(row)

    return {
        "name": env.name,
        "rows": env.n_rows,
        "cols": env.n_cols,
        "cells": cells,
        "optimal_value_at_start": round(V[env.start_state], 3),
        "curves": curves,
        "matches": matches,
        "final_paths": final_paths,
    }


def _downsample(values, n):
    """Keeps report payload size sane for long training runs -- a moving
    average over n buckets, not a truncation, so early/late trends both
    survive."""
    if not values:
        return []
    if len(values) <= n:
        return [round(v, 2) for v in values]
    bucket = len(values) / n
    out = []
    for i in range(n):
        lo = int(i * bucket)
        # the last bucket must reach the true end: float rounding on
        # (i+1)*bucket can otherwise land one short and silently drop
        # the final data point
        hi = len(values) if i == n - 1 else max(lo + 1, int((i + 1) * bucket))
        chunk = values[lo:hi]
        out.append(round(sum(chunk) / len(chunk), 2))
    return out


def _cliff_compare_section(episodes, seed):
    env_template = lambda: gridworld.make("cliffwalking")
    schedule = tabular.EpsilonGreedy(1.0, 0.1, 300)

    ql = tabular.QLearning(env_template(), alpha=0.5, gamma=1.0, seed=seed, schedule=schedule)
    ql.train(episodes=episodes)
    sarsa = tabular.Sarsa(env_template(), alpha=0.5, gamma=1.0, seed=seed, schedule=schedule)
    sarsa.train(episodes=episodes)

    env = env_template()
    cliffs = [list(env.rc(s)) for s in env.cliffs]
    start = list(env.rc(env.start_state))
    goal = list(env.rc(next(iter(env.goals))))

    return {
        "rows": env.n_rows,
        "cols": env.n_cols,
        "cliffs": cliffs,
        "start": start,
        "goal": goal,
        "qlearning_path": _replay_path(env_template(), ql.greedy_policy(), max_steps=60),
        "sarsa_path": _replay_path(env_template(), sarsa.greedy_policy(), max_steps=60),
    }


def _cartpole_replay(env, act_fn, max_steps=500):
    s = env.reset()
    frames = [[round(s[0], 4), round(s[2], 4)]]
    for _ in range(max_steps):
        a = act_fn(s)
        s, r, done, truncated = env.step(a)
        frames.append([round(s[0], 4), round(s[2], 4)])
        if done or truncated:
            break
    return frames


def _cartpole_section(dqn_episodes, reinforce_episodes, seed):
    dqn_env = cartpole.CartPoleEnv(seed=seed)
    dqn_agent, dqn_rewards, dqn_losses = dqn.train(dqn_env, episodes=dqn_episodes, seed=seed)
    dqn_eval_env = cartpole.CartPoleEnv(seed=seed + 1000)
    dqn_evals = dqn.evaluate(dqn_eval_env, dqn_agent, episodes=30)
    dqn_replay_env = cartpole.CartPoleEnv(max_steps=500, seed=seed + 2000)
    dqn_replay = _cartpole_replay(dqn_replay_env, lambda s: dqn_agent.act(s, epsilon=0.0))

    re_env = cartpole.CartPoleEnv(seed=seed)
    re_agent, re_rewards = reinforce.train(re_env, episodes=reinforce_episodes, seed=seed)
    re_eval_env = cartpole.CartPoleEnv(seed=seed + 1000)
    re_evals = reinforce.evaluate(re_eval_env, re_agent, episodes=30)
    re_replay_env = cartpole.CartPoleEnv(max_steps=500, seed=seed + 2000)

    def re_act(s):
        logits = re_agent.policy_net.forward(list(s))
        return 0 if logits[0] >= logits[1] else 1

    re_replay = _cartpole_replay(re_replay_env, re_act)

    return {
        "dqn": {
            "reward_curve": _downsample(dqn_rewards, 150),
            "eval_mean": round(statistics.mean(dqn_evals), 1),
            "eval_min": min(dqn_evals),
            "eval_max": max(dqn_evals),
            "replay": dqn_replay,
        },
        "reinforce": {
            "reward_curve": _downsample(re_rewards, 150),
            "eval_mean": round(statistics.mean(re_evals), 1),
            "eval_min": min(re_evals),
            "eval_max": max(re_evals),
            "replay": re_replay,
        },
    }


def collect_data(seed=0, dqn_episodes=260, reinforce_episodes=350, tabular_episodes=800):
    data = {
        "gridworlds": {
            name: _gridworld_section(name, tabular_episodes, seed)
            for name in ("gridworld", "windygridworld", "frozenlake")
        },
        "cliff_compare": _cliff_compare_section(episodes=800, seed=2),
        "cartpole": _cartpole_section(dqn_episodes, reinforce_episodes, seed),
    }
    return data


def build_report(out_path="report.html", seed=0, dqn_episodes=260,
                  reinforce_episodes=350, tabular_episodes=800):
    data = collect_data(seed, dqn_episodes, reinforce_episodes, tabular_episodes)
    html = _render_html(data)
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


def _render_html(data):
    from .template import TEMPLATE

    return TEMPLATE.replace("__BELLMAN_DATA__", json.dumps(data))
