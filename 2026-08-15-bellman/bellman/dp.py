"""Dynamic programming: the Bellman-optimality ground-truth oracle.

Value Iteration and Policy Iteration both solve the Bellman optimality
equation

    V*(s) = max_a  sum_{s',r} p(s',r | s,a) [ r + gamma * V*(s') ]

exactly, given the *true* transition model. Unlike every learning algorithm
in `td.py`/`mc.py`/`pg.py`, these never touch `env.step()` -- they read
`env.transition_model()` directly. That makes them independent ground truth:
`tests/` checks the learned agents' policies and value estimates against
what's computed here.

`blackjack_optimal_policy` is a second, independent oracle (exact expected-
value backward induction over the dealer's full outcome distribution) used
to grade the Monte Carlo control stretch feature -- deliberately *not*
sharing any code with `value_iteration`/`policy_iteration`, so it isn't
"testing the oracle against itself."
"""
from functools import lru_cache


def value_iteration(env, gamma=1.0, theta=1e-6, max_iter=100_000):
    """Returns (V, policy) dicts, both indexed by state."""
    V = {s: 0.0 for s in env.states}
    for _ in range(max_iter):
        delta = 0.0
        for s in env.states:
            if env.is_terminal(s):
                continue
            best_q = max(
                sum(p * (r + gamma * (0.0 if done else V[ns]))
                    for p, ns, r, done in env.transition_model(s, a))
                for a in env.actions
            )
            delta = max(delta, abs(best_q - V[s]))
            V[s] = best_q
        if delta < theta:
            break
    else:
        raise RuntimeError("value_iteration did not converge within max_iter")

    policy = _greedy_policy(env, V, gamma)
    return V, policy


def policy_iteration(env, gamma=1.0, theta=1e-6, max_eval_iter=2000, max_policy_iter=500):
    """Returns (V, policy). Alternates policy evaluation with greedy improvement.

    NOTE on `max_eval_iter`: with an undiscounted (gamma=1) episodic MDP like
    Cliff Walking, an *improper* initial policy (one that never reaches a
    terminal state from some state, e.g. "always move up" from the top row)
    makes iterative policy evaluation diverge rather than converge -- V for
    that state decreases by a fixed step every sweep forever, since nothing
    ever discounts it back toward zero. Capping evaluation sweeps at a finite
    budget (a standard "modified policy iteration" variant) keeps this
    correct and terminating: each capped evaluation still moves V *toward*
    the fixed policy's true value, and the subsequent greedy-improvement step
    still strictly improves any non-optimal action, so the outer loop
    converges to the same optimum as full evaluation would -- it just may
    take a few more outer iterations along the way.
    """
    policy = {s: 1 for s in env.states if not env.is_terminal(s)}  # start "move toward goal"
    V = {s: 0.0 for s in env.states}

    for _ in range(max_policy_iter):
        # --- policy evaluation: iterate V under the fixed current policy until it settles ---
        for _ in range(max_eval_iter):
            delta = 0.0
            for s in env.states:
                if env.is_terminal(s):
                    continue
                a = policy[s]
                v = sum(p * (r + gamma * (0.0 if done else V[ns]))
                        for p, ns, r, done in env.transition_model(s, a))
                delta = max(delta, abs(v - V[s]))
                V[s] = v
            if delta < theta:
                break

        # --- policy improvement: act greedily w.r.t. the evaluated V ---
        stable = True
        for s in env.states:
            if env.is_terminal(s):
                continue
            best_a, best_q = None, float("-inf")
            for a in env.actions:
                q = sum(p * (r + gamma * (0.0 if done else V[ns]))
                        for p, ns, r, done in env.transition_model(s, a))
                if q > best_q:
                    best_q, best_a = q, a
            if best_a != policy[s]:
                stable = False
            policy[s] = best_a
        if stable:
            break
    else:
        raise RuntimeError("policy_iteration did not converge within max_policy_iter")

    return V, policy


def _greedy_policy(env, V, gamma):
    policy = {}
    for s in env.states:
        if env.is_terminal(s):
            continue
        best_a, best_q = None, float("-inf")
        for a in env.actions:
            q = sum(p * (r + gamma * (0.0 if done else V[ns]))
                    for p, ns, r, done in env.transition_model(s, a))
            if q > best_q:
                best_q, best_a = q, a
        policy[s] = best_a
    return policy


def greedy_rollout_return(env, policy, max_steps=1000):
    """Deterministically greedy-rollout `policy` from env.reset() and sum the reward.

    Used to compare a learned (tabular Q-table -> greedy) or DP-derived policy
    to the classic Cliff-Walking result: the optimal path costs exactly -13.
    """
    s = env.reset()
    total = 0.0
    for _ in range(max_steps):
        a = policy[s]
        s, r, done, _ = env.step(a)
        total += r
        if done:
            break
    return total


# ---------------------------------------------------------------------------
# Independent Blackjack oracle: exact expected-value backward induction.
# Deliberately separate machinery from value_iteration/policy_iteration above.
# ---------------------------------------------------------------------------

def _card_prob(card):
    """P(drawing this card value) in an infinite/reshuffled deck: 1..9 each 1/13,
    10 (representing 10/J/Q/K) is 4/13."""
    return 4 / 13 if card == 10 else 1 / 13


@lru_cache(maxsize=None)
def _dealer_outcome_dist(dealer_total, dealer_usable_ace):
    """Exact probability distribution over the dealer's final total (17-21, or 'bust'),
    given the dealer plays the fixed "hit while < 17" policy, computed by exact
    recursion over all future draws (not simulation)."""
    if dealer_total >= 17:
        return {("bust" if dealer_total > 21 else dealer_total): 1.0}

    dist = {}
    for card in range(1, 11):
        p = _card_prob(card)
        total = dealer_total + card
        usable_ace = dealer_usable_ace
        if card == 1 and total + 10 <= 21:
            total += 10
            usable_ace = True
        if total > 21 and usable_ace:
            # the ace we were counting as 11 downgrades to 1
            total -= 10
            usable_ace = False
        sub = _dealer_outcome_dist(total, usable_ace)
        for outcome, sub_p in sub.items():
            dist[outcome] = dist.get(outcome, 0.0) + p * sub_p
    return dist


def _stick_expected_value(player_total, dealer_showing):
    """E[reward] if the player sticks now, given the dealer's up-card."""
    dealer_start_ace = dealer_showing == 1
    dealer_start_total = 11 if dealer_start_ace else dealer_showing
    dist = _dealer_outcome_dist(dealer_start_total, dealer_start_ace)
    ev = 0.0
    for outcome, p in dist.items():
        if outcome == "bust" or outcome < player_total:
            ev += p * 1.0
        elif outcome == player_total:
            ev += p * 0.0
        else:
            ev += p * -1.0
    return ev


@lru_cache(maxsize=None)
def _hit_expected_value(player_total, dealer_showing, usable_ace, depth=0):
    """E[reward] if the player hits now and then plays optimally thereafter."""
    if depth > 21:  # safety valve; unreachable in practice
        return -1.0
    ev = 0.0
    for card in range(1, 11):
        p = _card_prob(card)
        total = player_total + card
        ua = usable_ace
        if card == 1 and total + 10 <= 21:
            total += 10
            ua = True
        if total > 21 and ua:
            total -= 10
            ua = False
        if total > 21:
            ev += p * -1.0
        else:
            ev += p * max(
                _stick_expected_value(total, dealer_showing),
                _hit_expected_value(total, dealer_showing, ua, depth + 1),
            )
    return ev


def blackjack_optimal_policy():
    """Exact optimal hit/stick policy for every (player_total, dealer_showing,
    usable_ace) state with player_total in 4..21, computed by backward induction
    over the true dealer outcome distribution -- an independent ground truth
    for grading `mc.py`'s Monte Carlo control agent."""
    policy = {}
    values = {}
    for usable_ace in (False, True):
        for dealer_showing in range(1, 11):
            for player_total in range(4, 22):
                stick_ev = _stick_expected_value(player_total, dealer_showing)
                hit_ev = _hit_expected_value(player_total, dealer_showing, usable_ace)
                state = (player_total, dealer_showing, usable_ace)
                if hit_ev > stick_ev:
                    policy[state] = 1
                    values[state] = hit_ev
                else:
                    policy[state] = 0
                    values[state] = stick_ev
    return policy, values
