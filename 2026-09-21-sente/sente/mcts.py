"""Generic PUCT Monte Carlo Tree Search (the AlphaZero search variant),
operating over any concrete `Game`. One `MCTS` instance runs exactly one
search from one root state per call to `run()` -- there is deliberately
no persistent tree reused across moves inside a game, so there is no
"stale child node from a different game" state-corruption hazard to
reason about (see REVIEW.md for the tree-reuse bug class this sidesteps
by construction, at the cost of some recomputation).

Sign convention (this is the #1 place self-play/MCTS implementations get
a sign backwards, so it gets an explicit walkthrough):

  - `Game.encode(state)` and the network's value output are always from
    the perspective of the player to move AT that state: value close to
    +1 means "the player about to move here is expected to win".
  - A node's `Q[a]` (mean action value) must be from the perspective of
    the player to move AT THE PARENT (the one choosing action a) -- i.e.
    "how good is it for me, the mover at this node, to take action a".
  - When we expand a child by applying action a, the child's own
    perspective flips to the other player, so the value the network
    reports at the child is from the *opponent's* perspective. To fold
    that into W[a] at the parent we must negate it once per ply climbed.
  - `backup()` below starts at the leaf with `v` = network value at the
    leaf (leaf's own to-move perspective), then walks back up the path;
    at each step *before* crediting the parent's action edge, it negates
    v once -- because crediting parent-edge `a` requires the parent's
    perspective, which is the flip of the child's.
"""

from __future__ import annotations
from typing import Dict, List, Optional
import numpy as np


class Node:
    __slots__ = ("state", "prior", "children", "N", "W", "P", "legal", "is_expanded")

    def __init__(self, state):
        self.state = state
        self.children: Dict[int, "Node"] = {}
        self.N: Dict[int, int] = {}
        self.W: Dict[int, float] = {}
        self.P: Dict[int, float] = {}
        self.legal: List[int] = []
        self.is_expanded = False


class MCTS:
    def __init__(self, game, net, c_puct: float = 1.5, n_simulations: int = 200,
                 dirichlet_alpha: float = 0.3, dirichlet_eps: float = 0.25,
                 rng: Optional[np.random.Generator] = None):
        self.game = game
        self.net = net
        self.c_puct = c_puct
        self.n_simulations = n_simulations
        self.dirichlet_alpha = dirichlet_alpha
        self.dirichlet_eps = dirichlet_eps
        self.rng = rng or np.random.default_rng()

    def _evaluate(self, state):
        """Runs the network on `state`, returns (priors dict over legal
        moves summing to 1, value from state's to-move perspective)."""
        legal = self.game.legal_moves(state)
        x = self.game.encode(state)
        mask = self.game.legal_mask(state)
        probs, v = self.net.predict_one(x, mask)
        priors = {a: float(probs[a]) for a in legal}
        s = sum(priors.values())
        if s <= 1e-12:
            # degenerate: fall back to uniform (should not happen once the
            # net is even slightly trained, but must never crash or
            # silently zero out the whole policy)
            priors = {a: 1.0 / len(legal) for a in legal}
        else:
            priors = {a: p / s for a, p in priors.items()}
        return priors, v

    def _expand(self, node: Node, add_noise: bool = False):
        priors, v = self._evaluate(node.state)
        node.legal = list(priors.keys())
        if add_noise and len(node.legal) > 0:
            noise = self.rng.dirichlet([self.dirichlet_alpha] * len(node.legal))
            for a, n in zip(node.legal, noise):
                priors[a] = (1 - self.dirichlet_eps) * priors[a] + self.dirichlet_eps * n
        for a in node.legal:
            node.P[a] = priors[a]
            node.N[a] = 0
            node.W[a] = 0.0
        node.is_expanded = True
        return v

    def run(self, root_state, add_root_noise: bool = False, return_root: bool = False):
        """Runs n_simulations of PUCT search from root_state. Returns the
        visit-count dict {action: N} at the root (the raw statistic used
        both for the training policy target and for temperature-scaled
        move sampling), or (visit_counts, root_node) if return_root=True
        (used by tests that need to inspect Q(root, a) directly).
        """
        root = Node(root_state)
        if self.game.is_terminal(root_state):
            return ({}, root) if return_root else {}
        root_v = self._expand(root, add_noise=add_root_noise)

        for _ in range(self.n_simulations):
            path = [root]           # nodes visited
            actions = []            # action taken at each node in path
            node = root

            # ---- SELECT ----
            while True:
                if self.game.is_terminal(node.state):
                    leaf_value = self.game.outcome_for(node.state, self.game.current_player(node.state))
                    self._backup(path, actions, leaf_value)
                    break
                if not node.is_expanded:
                    v = self._expand(node)
                    self._backup(path, actions, v)
                    break

                a = self._select_action(node)
                actions.append(a)
                if a in node.children:
                    node = node.children[a]
                    path.append(node)
                    continue
                # create the child, expand it (this is the "leaf" case)
                child_state = self.game.apply_move(node.state, a)
                child = Node(child_state)
                node.children[a] = child
                path.append(child)
                if self.game.is_terminal(child_state):
                    leaf_value = self.game.outcome_for(child_state, self.game.current_player(child_state))
                else:
                    leaf_value = self._expand(child)
                self._backup(path, actions, leaf_value)
                break

        return (dict(root.N), root) if return_root else dict(root.N)

    def _select_action(self, node: Node) -> int:
        total_N = sum(node.N.values())
        sqrt_total = np.sqrt(max(total_N, 1))
        best_score, best_a = -1e18, None
        for a in node.legal:
            q = node.W[a] / node.N[a] if node.N[a] > 0 else 0.0
            u = self.c_puct * node.P[a] * sqrt_total / (1 + node.N[a])
            score = q + u
            if score > best_score:
                best_score, best_a = score, a
        return best_a

    def _backup(self, path: List[Node], actions: List[int], leaf_value: float):
        """path[i] is the node reached after taking actions[i-1] from
        path[i-1] (path[0] is root, len(actions) == len(path)-1). We
        credit action actions[i] taken AT path[i] using a value from
        path[i]'s own to-move perspective, which is `v` after negating
        once per level climbed from the leaf (see module docstring).
        """
        v = leaf_value
        # Walk from the deepest edge back to the root. `v` starts as the
        # leaf's value from THE LEAF's own to-move perspective. Crediting
        # the edge one ply higher requires flipping perspective FIRST
        # (players alternate every ply), THEN crediting -- flipping after
        # crediting (an earlier, wrong version of this code did that) is
        # an off-by-one-ply sign bug that silently makes every single-ply
        # backup credit the wrong side.
        for i in reversed(range(len(actions))):
            v = -v
            parent = path[i]
            a = actions[i]
            parent.N[a] += 1
            parent.W[a] += v


def visit_policy(action_size: int, visit_counts: Dict[int, int]) -> np.ndarray:
    """Normalized visit-count distribution over the full action space
    (0 at illegal/unvisited actions)."""
    pi = np.zeros(action_size, dtype=np.float64)
    total = sum(visit_counts.values())
    if total == 0:
        return pi
    for a, n in visit_counts.items():
        pi[a] = n / total
    return pi


def sample_action(visit_counts: Dict[int, int], temperature: float, rng: np.random.Generator) -> int:
    """Temperature-scaled sampling from visit counts. temperature==0 (or
    very small) means argmax (greedy/deterministic); otherwise sample
    proportional to N(a)^(1/T)."""
    actions = list(visit_counts.keys())
    counts = np.array([visit_counts[a] for a in actions], dtype=np.float64)
    if temperature <= 1e-3:
        return actions[int(np.argmax(counts))]
    logits = np.log(np.maximum(counts, 1e-12)) / temperature
    logits -= logits.max()
    probs = np.exp(logits)
    probs /= probs.sum()
    return int(rng.choice(actions, p=probs))
