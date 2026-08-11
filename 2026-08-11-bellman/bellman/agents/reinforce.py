"""REINFORCE: Monte-Carlo policy gradient with a learned baseline.

Structurally different from DQN in every way that matters:

  * DQN learns a *value* (Q(s,a)) and derives a policy from it (act
    greedily / epsilon-greedily); REINFORCE learns the *policy* directly
    as a parametric distribution over actions and pushes probability mass
    toward actions that led to high return.
  * DQN bootstraps its TD target from its own current value estimate one
    step ahead (biased but low-variance); REINFORCE uses the actual
    observed Monte-Carlo return G_t = sum of discounted rewards for the
    *rest of the real episode* (unbiased but high-variance -- the whole
    reason for the learned baseline below).
  * DQN is off-policy (replay buffer full of old-policy data is fine);
    REINFORCE is on-policy -- every gradient step uses trajectories from
    the *current* policy and then throws them away.

The policy gradient theorem gives, for a return G_t following (s_t, a_t):

    grad_theta J = E[ G_t * grad_theta log pi_theta(a_t | s_t) ]

Subtracting any state-dependent baseline b(s_t) from G_t leaves this
expectation unbiased (E[grad log pi * b(s)] = 0 for a baseline that
doesn't depend on the action) while cutting its variance a lot when b is
close to G_t -- so a second small network is trained by ordinary
regression to predict G_t, and (G_t - b(s_t)) is used as the advantage.
"""
import math

from .nn import MLP, Adam


def softmax(logits):
    m = max(logits)
    exps = [math.exp(v - m) for v in logits]
    total = sum(exps)
    return [e / total for e in exps]


class ReinforceAgent:
    def __init__(self, state_dim, n_actions, hidden=32, gamma=0.99,
                 policy_lr=5e-3, value_lr=5e-3, seed=0):
        self.n_actions = n_actions
        self.gamma = gamma
        self.policy_net = MLP([state_dim, hidden, n_actions], seed=seed)
        self.value_net = MLP([state_dim, hidden, 1], seed=seed + 1)
        self.policy_opt = Adam(self.policy_net, lr=policy_lr)
        self.value_opt = Adam(self.value_net, lr=value_lr)
        import random

        self.rng = random.Random(seed + 2)

    def act(self, state):
        """Samples an action from the current stochastic policy. Returns
        (action, action_probs) -- probs are cached by the caller if it
        wants them, but recomputed cheaply from logits on update anyway."""
        logits = self.policy_net.forward(list(state))
        probs = softmax(logits)
        x = self.rng.random()
        acc = 0.0
        for a, p in enumerate(probs):
            acc += p
            if x <= acc:
                return a, probs
        return self.n_actions - 1, probs

    def _returns(self, rewards):
        G = 0.0
        out = [0.0] * len(rewards)
        for t in range(len(rewards) - 1, -1, -1):
            G = rewards[t] + self.gamma * G
            out[t] = G
        return out

    def update(self, states, actions, rewards):
        """One on-policy gradient step from one full episode's trajectory."""
        returns = self._returns(rewards)
        n = len(states)
        if n == 0:
            return None

        # baseline: predicted value of each visited state, from the
        # *current* (pre-update) value network
        baselines = [self.value_net.forward(list(s))[0] for s in states]
        advantages = [returns[t] - baselines[t] for t in range(n)]

        # normalizing advantages stabilizes the gradient scale across
        # episodes of very different length/return without changing what
        # the policy gradient is an unbiased estimator of
        mean_adv = sum(advantages) / n
        var_adv = sum((a - mean_adv) ** 2 for a in advantages) / n
        std_adv = math.sqrt(var_adv) + 1e-8
        norm_adv = [(a - mean_adv) / std_adv for a in advantages]

        policy_grads_sum = self._zero_grads_like(self.policy_net)
        value_grads_sum = self._zero_grads_like(self.value_net)

        for t in range(n):
            s, a = states[t], actions[t]
            logits = self.policy_net.forward(list(s))
            probs = softmax(logits)
            onehot = [1.0 if i == a else 0.0 for i in range(self.n_actions)]
            # d(-J)/dlogits = -(advantage) * (onehot - probs); we hand
            # this "loss gradient" to backward()/Adam so a normal gradient
            # *descent* step performs gradient *ascent* on J
            d_out = [-norm_adv[t] * (onehot[i] - probs[i]) for i in range(self.n_actions)]
            grads = self.policy_net.backward(d_out)
            self._accumulate(policy_grads_sum, grads)

            pred = self.value_net.forward(list(s))
            err = pred[0] - returns[t]  # dMSE/dpred
            grads_v = self.value_net.backward([err])
            self._accumulate(value_grads_sum, grads_v)

        self.policy_opt.step(self.policy_net, self._average(policy_grads_sum, n))
        self.value_opt.step(self.value_net, self._average(value_grads_sum, n))
        return sum(returns) / n

    @staticmethod
    def _zero_grads_like(mlp):
        return [([[0.0] * layer.n_in for _ in range(layer.n_out)], [0.0] * layer.n_out)
                for layer in mlp.layers]

    @staticmethod
    def _accumulate(grads_sum, grads):
        for (dW_sum, db_sum), (dW, db) in zip(grads_sum, grads):
            for o in range(len(dW)):
                row_sum, row = dW_sum[o], dW[o]
                for i in range(len(row)):
                    row_sum[i] += row[i]
                db_sum[o] += db[o]

    @staticmethod
    def _average(grads_sum, n):
        return [([[v / n for v in row] for row in dW], [v / n for v in db])
                for dW, db in grads_sum]


def train(env, agent=None, episodes=350, max_steps=500, seed=0, on_episode=None):
    from ..envs.cartpole import STATE_DIM, ACTIONS

    if agent is None:
        agent = ReinforceAgent(STATE_DIM, len(ACTIONS), seed=seed)

    rewards = []
    for ep in range(episodes):
        s = env.reset()
        states, actions, step_rewards = [], [], []
        total = 0.0
        for _ in range(max_steps):
            a, _ = agent.act(s)
            ns, r, done, truncated = env.step(a)
            states.append(s)
            actions.append(a)
            step_rewards.append(r)
            total += r
            s = ns
            if done or truncated:
                break
        agent.update(states, actions, step_rewards)
        rewards.append(total)
        if on_episode:
            on_episode(ep, total)
    return agent, rewards


def evaluate(env, agent, episodes=20, max_steps=500):
    totals = []
    for _ in range(episodes):
        s = env.reset()
        total = 0.0
        for _ in range(max_steps):
            logits = agent.policy_net.forward(list(s))
            a = 0 if logits[0] >= logits[1] else 1  # greedy (argmax) eval
            s, r, done, truncated = env.step(a)
            total += r
            if done or truncated:
                break
        totals.append(total)
    return totals
