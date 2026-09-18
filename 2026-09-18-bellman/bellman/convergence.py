"""Measures how many training episodes an algorithm needs before its
greedy policy is actually good, by re-training from scratch at each
checkpoint episode count and scoring the resulting policy against the
exact DP oracle. This is what backs the stretch claim that SARSA(lambda)
reaches a working Cliff Walking policy in measurably fewer episodes than
1-step SARSA at matched hyperparameters (bellman/td.py's docstrings).

Re-training from scratch at each checkpoint (rather than checkpointing a
single run) costs more compute but avoids a subtle mistake: a single
run's episode-N snapshot depends on the exact sequence of exploratory
moves taken in episodes 1..N-1, which is not "how many episodes does this
algorithm typically need" so much as "what did this one lucky/unlucky
run's Q table look like partway through" -- reusing the same seed across
algorithms at least makes the two comparable to each other, even if not
averaged over multiple seeds.
"""
from . import dp


def policy_value_at_start(env, policy):
    return dp.policy_evaluation(env, policy)[env.start_state]


def episodes_to_threshold(env, train_fn, checkpoints, threshold, **train_kwargs):
    """Return (first_checkpoint_meeting_threshold_or_None, [(n, value), ...])
    for a training function like td.sarsa or td.sarsa_lambda, called fresh
    at each checkpoint episode count with **train_kwargs forwarded."""
    curve = []
    crossing = None
    for n in checkpoints:
        result = train_fn(env, episodes=n, **train_kwargs)
        value = policy_value_at_start(env, result["policy"])
        curve.append((n, value))
        if crossing is None and value >= threshold:
            crossing = n
    return crossing, curve
