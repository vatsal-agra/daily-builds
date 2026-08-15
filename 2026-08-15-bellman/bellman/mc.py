"""First-visit Monte Carlo control.

Unlike TD control (`td.py`), MC never bootstraps: it plays a full episode
to completion, then updates every first-visited (state, action) pair toward
the *actual* observed return. On Blackjack -- episodic, no useful notion of
"one step" reward until the hand resolves -- that's a very natural fit.

Two variants are implemented:

- `mc_control`: the general on-policy, epsilon-greedy version (works with
  any env exposing reset()/step()/actions).
- `mc_es_control`: Monte Carlo **Exploring Starts** specialized to
  `BlackjackEnv` -- the actual algorithm Sutton & Barto use to produce the
  optimal-Blackjack-policy figure (their Example 5.3 / Figure 5.2), not the
  epsilon-soft variant. Each episode starts at a uniformly random
  (state, action) pair via `BlackjackEnv.reset_to`, then follows the current
  greedy policy thereafter -- exploration comes entirely from the randomized
  start, not from ongoing randomness during play. This matters here because
  Blackjack's textbook comparison policy in `dp.py` is the value of *always*
  playing optimally from here on; an epsilon-soft behavior policy instead
  converges to Q_pi (value under a policy that keeps exploring 5% of the
  time forever), which is a measurably different, slightly pessimistic
  target for "hit" -- exploring starts avoids that gap entirely.
"""
import random

from .envs import BlackjackEnv


def mc_control(env_factory, episodes=500_000, gamma=1.0,
               epsilon_start=1.0, epsilon_end=0.05, seed=0):
    """`env_factory()` must return a fresh env each call (Blackjack has no
    fixed `states` list to pre-size a table with, since hands are dealt
    randomly -- so the Q-table grows lazily, keyed by whatever states are
    actually visited)."""
    rng = random.Random(seed)
    actions = env_factory().actions  # a fixed, env-independent action set -- read once
    Q = {}
    counts = {}

    def ensure(state):
        if state not in Q:
            Q[state] = {a: 0.0 for a in actions}
            counts[state] = {a: 0 for a in actions}

    for ep in range(episodes):
        epsilon = epsilon_start + (epsilon_end - epsilon_start) * min(ep / max(episodes - 1, 1), 1.0)
        env = env_factory()
        s = env.reset()
        trajectory = []  # (state, action, reward)
        done = getattr(env, "done", False)

        while not done:
            ensure(s)
            if rng.random() < epsilon:
                a = rng.choice(list(Q[s].keys()))
            else:
                a = max(Q[s], key=lambda act: Q[s][act])
            ns, r, done, _ = env.step(a)
            trajectory.append((s, a, r))
            s = ns

        # first-visit MC: walk backward accumulating return, update on first occurrence
        G = 0.0
        seen = set()
        for t in reversed(range(len(trajectory))):
            st, a, r = trajectory[t]
            G = gamma * G + r
            if (st, a) in seen:
                continue
            seen.add((st, a))
            counts[st][a] += 1
            Q[st][a] += (G - Q[st][a]) / counts[st][a]

    policy = {s: max(Q[s], key=lambda a: Q[s][a]) for s in Q}
    return Q, policy


def mc_es_control(episodes=500_000, gamma=1.0, seed=0):
    """Monte Carlo Exploring Starts control, specialized to BlackjackEnv's
    graded state space (player_total 12..21 x dealer_showing 1..10 x
    usable_ace). Hitting only ever increases player_total, so once an
    episode starts inside this range every subsequent state it visits stays
    inside it too (or busts, ending the episode) -- the domain is closed
    under `step()`, which is what lets a plain dict keyed by these states
    (no lazy growth needed) work here."""
    rng = random.Random(seed)
    all_states = [(t, d, ace) for t in range(12, 22) for d in range(1, 11) for ace in (False, True)]
    Q = {s: {0: 0.0, 1: 0.0} for s in all_states}
    counts = {s: {0: 0, 1: 0} for s in all_states}
    env = BlackjackEnv(seed=seed)

    for _ in range(episodes):
        s0 = rng.choice(all_states)
        a = rng.choice((0, 1))
        s = env.reset_to(*s0)
        trajectory = []
        done = False
        while not done:
            ns, r, done, _ = env.step(a)
            trajectory.append((s, a, r))
            s = ns
            if not done:
                a = max(Q[s], key=lambda act: Q[s][act])

        G = 0.0
        seen = set()
        for t in reversed(range(len(trajectory))):
            st, act, r = trajectory[t]
            G = gamma * G + r
            if (st, act) in seen:
                continue
            seen.add((st, act))
            counts[st][act] += 1
            Q[st][act] += (G - Q[st][act]) / counts[st][act]

    policy = {s: max(Q[s], key=lambda a: Q[s][a]) for s in Q}
    return Q, policy
