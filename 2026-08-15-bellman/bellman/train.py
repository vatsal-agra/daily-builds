"""Orchestrates full training runs and assembles the results bundle the HTML
report (`report.py`) and CLI consume. Central place where the "which
hyperparameters actually work" knowledge from experimentation lives.
"""
import random
import time

from .envs import GridWorldEnv, CartPoleEnv, BlackjackEnv
from .dp import value_iteration, greedy_rollout_return, blackjack_optimal_policy
from .td import sarsa, sarsa_lambda, epsilon_greedy, _linear_decay
from .mc import mc_es_control
from .pg import train_reinforce, evaluate as pg_evaluate


def q_learning_with_snapshots(env, episodes, snapshot_every=25, **kwargs):
    """Like td.q_learning, but also returns periodic (episode, Q-copy, policy-copy)
    checkpoints so the viewer can scrub the learned policy across training time."""
    rng = random.Random(kwargs.pop("seed", 0))
    alpha = kwargs.pop("alpha", 0.5)
    gamma = kwargs.pop("gamma", 1.0)
    epsilon_start = kwargs.pop("epsilon_start", 1.0)
    epsilon_end = kwargs.pop("epsilon_end", 0.01)
    max_steps = kwargs.pop("max_steps", 10_000)

    Q = {s: {a: 0.0 for a in env.actions} for s in env.states}
    episode_returns = []
    snapshots = []

    for ep in range(episodes):
        epsilon = _linear_decay(epsilon_start, epsilon_end, ep, episodes)
        s = env.reset()
        total = 0.0
        for _ in range(max_steps):
            a = epsilon_greedy(Q, s, env.actions, epsilon, rng)
            ns, r, done, _ = env.step(a)
            total += r
            best_next = 0.0 if done else max(Q[ns].values())
            Q[s][a] += alpha * (r + gamma * best_next - Q[s][a])
            s = ns
            if done:
                break
        episode_returns.append(total)

        if ep % snapshot_every == 0 or ep == episodes - 1:
            q_copy = {s: dict(a_vals) for s, a_vals in Q.items()}
            policy_copy = {s: max(env.actions, key=lambda a: Q[s][a]) for s in env.states}
            snapshots.append({"episode": ep, "Q": q_copy, "policy": policy_copy})

    policy = {s: max(env.actions, key=lambda a: Q[s][a]) for s in env.states}
    return Q, policy, episode_returns, snapshots


def run_gridworld_experiment(rows=4, cols=12, slip_prob=0.0, episodes=500, seed=0):
    env = GridWorldEnv(rows=rows, cols=cols, slip_prob=slip_prob, seed=seed)
    V_star, policy_star = value_iteration(env, gamma=1.0)
    optimal_return = greedy_rollout_return(GridWorldEnv(rows=rows, cols=cols, slip_prob=0.0), policy_star)

    # Cap episode length well above the optimal path (13 steps) but far below
    # the pathological worst case: with epsilon near 1 early in training, an
    # uncapped episode can wander into the cliff (-100) hundreds of times
    # before reaching the goal, and those outlier episodes would otherwise
    # dominate the reward-curve's y-axis and hide the actual learning signal.
    max_steps = 200

    Q_q, policy_q, rewards_q, snapshots_q = q_learning_with_snapshots(
        GridWorldEnv(rows=rows, cols=cols, slip_prob=slip_prob, seed=seed),
        episodes=episodes, alpha=0.5, gamma=1.0, seed=seed, max_steps=max_steps)

    _, policy_s, rewards_s = sarsa(
        GridWorldEnv(rows=rows, cols=cols, slip_prob=slip_prob, seed=seed),
        episodes=episodes, alpha=0.5, gamma=1.0, seed=seed, max_steps=max_steps)

    _, policy_sl, rewards_sl = sarsa_lambda(
        GridWorldEnv(rows=rows, cols=cols, slip_prob=slip_prob, seed=seed),
        episodes=episodes, alpha=0.5, gamma=1.0, lam=0.9, seed=seed, max_steps=max_steps)

    eval_env = GridWorldEnv(rows=rows, cols=cols, slip_prob=0.0)
    q_return = greedy_rollout_return(eval_env, policy_q)
    s_return = greedy_rollout_return(eval_env, policy_s)
    sl_return = greedy_rollout_return(eval_env, policy_sl)

    return {
        "rows": rows, "cols": cols,
        "start": list(env.start), "goal": list(env.goal),
        "cliff": [list(c) for c in sorted(env.cliff)],
        "slip_prob": slip_prob,
        "optimal_return": optimal_return,
        "dp_policy": policy_star,
        "dp_V": V_star,
        "q_learning": {"rewards": rewards_q, "policy": policy_q, "greedy_return": q_return,
                       "snapshots": snapshots_q},
        "sarsa": {"rewards": rewards_s, "policy": policy_s, "greedy_return": s_return},
        "sarsa_lambda": {"rewards": rewards_sl, "policy": policy_sl, "greedy_return": sl_return},
    }


def _random_policy_returns(episodes=30, max_steps=500, seed=0):
    rng = random.Random(seed)
    totals = []
    for i in range(episodes):
        env = CartPoleEnv(max_steps=max_steps, seed=seed * 1000 + i)
        env.reset()
        total = 0.0
        done = False
        while not done:
            _, r, done, _ = env.step(rng.choice((0, 1)))
            total += r
        totals.append(total)
    return totals


def run_cartpole_experiment(episodes=400, hidden=8, lr=0.05, gamma=0.99,
                             max_steps=300, eval_max_steps=500, seed=1):
    train_env = CartPoleEnv(max_steps=max_steps, seed=seed)
    t0 = time.time()
    agent, train_rewards = train_reinforce(
        train_env, episodes=episodes, hidden=hidden, lr=lr, gamma=gamma,
        max_steps=max_steps, seed=seed)
    train_time = time.time() - t0

    eval_env = CartPoleEnv(max_steps=eval_max_steps, seed=seed + 500)
    eval_rewards = pg_evaluate(eval_env, agent, episodes=30, max_steps=eval_max_steps, greedy=True)

    # Genuine random-action baseline (uniform coin-flip each step) -- NOT an
    # untrained network's argmax, which would be a fixed action every step,
    # not "random" in any meaningful sense.
    baseline_rewards = _random_policy_returns(episodes=30, max_steps=eval_max_steps, seed=seed + 700)

    return {
        "episodes": episodes, "hidden": hidden, "lr": lr, "gamma": gamma,
        "eval_cap": eval_max_steps,
        "train_time_sec": train_time,
        "train_rewards": train_rewards,
        "eval_rewards": eval_rewards,
        "eval_mean": sum(eval_rewards) / len(eval_rewards),
        "baseline_rewards": baseline_rewards,
        "baseline_mean": sum(baseline_rewards) / len(baseline_rewards),
        "policy_weights": agent.policy.state_dict(),
    }


def run_blackjack_experiment(episodes=500_000, seed=0):
    t0 = time.time()
    Q, policy = mc_es_control(episodes=episodes, gamma=1.0, seed=seed)
    train_time = time.time() - t0

    optimal_policy, optimal_values = blackjack_optimal_policy()

    agree = 0
    total = 0
    disagreements = []
    for state, learned_a in policy.items():
        player_total, dealer_showing, usable_ace = state
        if player_total < 12:
            # With near-certain "hit" being correct and few visits at low
            # sums (episode ends fast at higher totals), skip these from the
            # accuracy score -- keep the check focused on the genuinely hard
            # decision boundary (12-21) the textbook table is defined over.
            continue
        total += 1
        opt_a = optimal_policy[state]
        if learned_a == opt_a:
            agree += 1
        else:
            disagreements.append({"state": list(state), "learned": learned_a, "optimal": opt_a})

    def state_key(state):
        # Matches the key format the JS report builds via `[t, d, ace].join(",")`
        # (JSON booleans stringify as "true"/"false" under Array.join).
        t, d, ace = state
        return f"{t},{d},{'true' if ace else 'false'}"

    return {
        "episodes": episodes,
        "train_time_sec": train_time,
        "agreement": agree / total if total else 0.0,
        "states_compared": total,
        "disagreements": disagreements,
        "learned_policy": {state_key(k): v for k, v in policy.items()},
        "optimal_policy": {state_key(k): v for k, v in optimal_policy.items()},
    }
