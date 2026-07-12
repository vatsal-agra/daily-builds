"""Genome: a recursive limb-growth grammar (body plan) plus per-joint CPG
(central pattern generator) motor parameters. A Genome expands
deterministically into a phenotype tree via body.py.

Encoding choice: each non-root node is attached to its parent by a
revolute joint at a point along the parent's length (``attach_t``,
-1..1) with a fixed rest angle plus optional bilateral mirroring
(produces symmetric leg pairs from one gene). This is a compact,
mutable, GP-style tree genotype -- not a hand-authored template -- so
bipeds, quadrupeds, and snake-like chains all fall out of the same rules
depending on what the genome happens to encode.
"""
import random

MAX_DEPTH = 4
MAX_SEGMENTS = 14  # including root; keeps simulation cost bounded

LEN_RANGE = (0.25, 1.0)
WID_RANGE = (0.12, 0.35)
ANGLE_RANGE = (-2.6, 2.6)          # rest_angle, radians
LIMIT_SPAN_RANGE = (0.3, 2.2)      # half-width of joint angle limit
AMP_RANGE = (0.0, 1.6)             # CPG amplitude, radians
FREQ_MULT_RANGE = (0.5, 2.0)       # multiplier on shared base frequency
PHASE_RANGE = (0.0, 6.283185307179586)
OFFSET_RANGE = (-0.6, 0.6)
BASE_FREQ_RANGE = (0.4, 2.2)       # Hz


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _rand_in(rng, r):
    return rng.uniform(r[0], r[1])


class CPG:
    """Per-joint oscillator: target_angle(t) = rest + offset +
    amplitude * sin(2*pi*freq_mult*base_freq*t + phase)."""

    __slots__ = ("amplitude", "freq_mult", "phase", "offset")

    def __init__(self, amplitude, freq_mult, phase, offset):
        self.amplitude = amplitude
        self.freq_mult = freq_mult
        self.phase = phase
        self.offset = offset

    @staticmethod
    def random(rng):
        return CPG(
            _rand_in(rng, AMP_RANGE),
            _rand_in(rng, FREQ_MULT_RANGE),
            _rand_in(rng, PHASE_RANGE),
            _rand_in(rng, OFFSET_RANGE),
        )

    def target_angle(self, base_freq, t, phase_shift=0.0):
        import math
        return self.offset + self.amplitude * math.sin(
            2 * math.pi * self.freq_mult * base_freq * t + self.phase + phase_shift
        )

    def clone(self):
        return CPG(self.amplitude, self.freq_mult, self.phase, self.offset)

    def to_dict(self):
        return {"amplitude": self.amplitude, "freq_mult": self.freq_mult,
                "phase": self.phase, "offset": self.offset}

    @staticmethod
    def from_dict(d):
        return CPG(d["amplitude"], d["freq_mult"], d["phase"], d["offset"])


class GenomeNode:
    """One body segment. The root node has no joint/cpg (it is the free
    torso); all others attach to a parent via a revolute joint."""

    _next_id = [0]

    def __init__(self, length, width, attach_t=0.0, attach_side=1.0,
                 rest_angle=0.0, limit_span=1.0, mirror=False, cpg=None,
                 node_id=None):
        self.id = node_id if node_id is not None else GenomeNode._alloc_id()
        self.length = length
        self.width = width
        self.attach_t = attach_t        # -1..1 along parent length
        self.attach_side = attach_side  # +1 or -1: which normal side
        self.rest_angle = rest_angle
        self.limit_span = limit_span    # joint angle in [rest-span, rest+span]
        self.mirror = mirror
        self.cpg = cpg if cpg is not None else CPG.random(random)
        self.children = []

    @staticmethod
    def _alloc_id():
        GenomeNode._next_id[0] += 1
        return GenomeNode._next_id[0]

    def clone(self):
        n = GenomeNode(self.length, self.width, self.attach_t,
                        self.attach_side, self.rest_angle, self.limit_span,
                        self.mirror, self.cpg.clone(), node_id=self.id)
        n.children = [c.clone() for c in self.children]
        return n

    def count_nodes(self):
        return 1 + sum(c.count_nodes() for c in self.children)

    def max_subdepth(self):
        if not self.children:
            return 1
        return 1 + max(c.max_subdepth() for c in self.children)

    def all_nodes(self):
        yield self
        for c in self.children:
            yield from c.all_nodes()

    def to_dict(self, is_root=False):
        d = {"length": self.length, "width": self.width,
             "children": [c.to_dict() for c in self.children]}
        if not is_root:
            d.update({"attach_t": self.attach_t, "attach_side": self.attach_side,
                       "rest_angle": self.rest_angle, "limit_span": self.limit_span,
                       "mirror": self.mirror, "cpg": self.cpg.to_dict()})
        return d

    @staticmethod
    def from_dict(d, is_root=False):
        if is_root:
            n = GenomeNode(d["length"], d["width"])
        else:
            n = GenomeNode(d["length"], d["width"], d["attach_t"],
                            d["attach_side"], d["rest_angle"], d["limit_span"],
                            d["mirror"], CPG.from_dict(d["cpg"]))
        n.children = [GenomeNode.from_dict(c) for c in d["children"]]
        return n


class Genome:
    def __init__(self, root, base_freq):
        self.root = root
        self.base_freq = base_freq

    def clone(self):
        return Genome(self.root.clone(), self.base_freq)

    def node_count(self):
        return self.root.count_nodes()

    def depth(self):
        return self.root.max_subdepth()

    def to_dict(self):
        return {"base_freq": self.base_freq, "root": self.root.to_dict(is_root=True)}

    @staticmethod
    def from_dict(d):
        return Genome(GenomeNode.from_dict(d["root"], is_root=True), d["base_freq"])

    # ---- random generation ----

    @staticmethod
    def random(rng=None, max_depth=MAX_DEPTH):
        rng = rng or random
        root = GenomeNode(_rand_in(rng, LEN_RANGE) * 1.4, _rand_in(rng, WID_RANGE) * 1.3)
        _grow(root, rng, depth=1, max_depth=max_depth)
        return Genome(root, _rand_in(rng, BASE_FREQ_RANGE))

    # ---- mutation ----

    def mutate(self, rng=None, rate=0.3):
        rng = rng or random
        g = self.clone()
        if rng.random() < 0.3:
            g.base_freq = _clamp(g.base_freq + rng.gauss(0, 0.15), *BASE_FREQ_RANGE)

        nodes = list(g.root.all_nodes())
        for node in nodes:
            if rng.random() < rate:
                _perturb(node, rng, is_root=(node is g.root))

        # structural mutations: at most one of add/remove per call, keeps steps small
        roll = rng.random()
        if roll < 0.18 and g.node_count() < MAX_SEGMENTS:
            _add_limb(g.root, rng, max_depth=MAX_DEPTH)
        elif roll < 0.30:
            _remove_limb(g.root, rng)
        return g

    # ---- crossover ----

    @staticmethod
    def crossover(a, b, rng=None):
        """Subtree-swap crossover (GP-style): clone `a`, pick a random
        non-root node in the clone, and replace its subtree with a clone
        of a random subtree from `b`. Falls back to cloning `a` if either
        parent has no non-root nodes."""
        rng = rng or random
        child = a.clone()
        a_nodes = [n for n in child.root.all_nodes()]
        b_nodes = [n for n in b.root.all_nodes() if n is not b.root]
        if not b_nodes:
            return child
        donor = rng.choice(b_nodes).clone()
        _renumber(donor)

        candidates = [n for n in a_nodes]  # includes root as attach point
        parent = rng.choice(candidates)
        parent.children.append(donor)
        _repair_bounds(child)
        child.base_freq = rng.choice([a.base_freq, b.base_freq])
        return child


def _renumber(node):
    node.id = GenomeNode._alloc_id()
    for c in node.children:
        _renumber(c)


def _grow(node, rng, depth, max_depth):
    if depth >= max_depth:
        return
    n_children = 0
    if rng.random() < 0.85:
        n_children = rng.randint(1, 2 if depth > 1 else 3)
    for _ in range(n_children):
        if node.count_nodes() >= MAX_SEGMENTS:
            break
        child = GenomeNode(
            length=_rand_in(rng, LEN_RANGE),
            width=_rand_in(rng, WID_RANGE),
            attach_t=rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0]),
            attach_side=rng.choice([-1.0, 1.0]),
            rest_angle=_rand_in(rng, ANGLE_RANGE),
            limit_span=_rand_in(rng, LIMIT_SPAN_RANGE),
            mirror=(rng.random() < 0.5),
        )
        node.children.append(child)
        _grow(child, rng, depth + 1, max_depth)


def _perturb(node, rng, is_root):
    node.length = _clamp(node.length + rng.gauss(0, 0.06), *LEN_RANGE)
    node.width = _clamp(node.width + rng.gauss(0, 0.03), *WID_RANGE)
    if is_root:
        return
    node.rest_angle = _clamp(node.rest_angle + rng.gauss(0, 0.25), *ANGLE_RANGE)
    node.limit_span = _clamp(node.limit_span + rng.gauss(0, 0.15), *LIMIT_SPAN_RANGE)
    if rng.random() < 0.1:
        node.attach_t = rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0])
    if rng.random() < 0.05:
        node.mirror = not node.mirror
    c = node.cpg
    c.amplitude = _clamp(c.amplitude + rng.gauss(0, 0.2), *AMP_RANGE)
    c.freq_mult = _clamp(c.freq_mult + rng.gauss(0, 0.15), *FREQ_MULT_RANGE)
    c.phase = (c.phase + rng.gauss(0, 0.4)) % PHASE_RANGE[1]
    c.offset = _clamp(c.offset + rng.gauss(0, 0.1), *OFFSET_RANGE)


def _nodes_with_depth(node, depth=1):
    yield node, depth
    for c in node.children:
        yield from _nodes_with_depth(c, depth + 1)


def _add_limb(root, rng, max_depth):
    # A node at depth-from-root `depth` can safely gain a child only if
    # that child (at depth+1) doesn't exceed max_depth -- max_subdepth()
    # (a *local* subtree-height measure) is the wrong quantity here since
    # every leaf reports 1 regardless of how deep it already sits.
    nodes = [n for n, depth in _nodes_with_depth(root) if depth < max_depth]
    if not nodes:
        return
    parent = rng.choice(nodes)
    child = GenomeNode(
        length=_rand_in(rng, LEN_RANGE),
        width=_rand_in(rng, WID_RANGE),
        attach_t=rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0]),
        attach_side=rng.choice([-1.0, 1.0]),
        rest_angle=_rand_in(rng, ANGLE_RANGE),
        limit_span=_rand_in(rng, LIMIT_SPAN_RANGE),
        mirror=(rng.random() < 0.5),
    )
    parent.children.append(child)


def _remove_limb(root, rng):
    # a "leaf-bearing" node is any node with children whose own children
    # (grandchildren of root through it) are themselves leaves; we simply
    # remove one whole child subtree from a random node that has children.
    parents = [n for n in root.all_nodes() if n.children]
    if not parents:
        return
    parent = rng.choice(parents)
    parent.children.pop(rng.randrange(len(parent.children)))


def _deepest_leaf_chain(node, depth=1):
    """Returns (depth_of_deepest_descendant_leaf, [node, ..., leaf])."""
    if not node.children:
        return depth, [node]
    best_depth, best_chain = depth, [node]
    for c in node.children:
        d, chain = _deepest_leaf_chain(c, depth + 1)
        if d > best_depth:
            best_depth, best_chain = d, [node] + chain
    return best_depth, best_chain


def _repair_bounds(genome):
    """After crossover, trim depth/segment-count back within bounds by
    pruning the deepest/most-recently-attached subtrees first.

    Note: root.max_subdepth() is, by construction, always the largest
    max_subdepth() value in the whole tree (it strictly decreases going
    down any path), so picking "the node with the largest max_subdepth"
    always returns the root itself -- that is not a useful way to find
    where to prune. We instead walk the actual deepest root-to-leaf
    chain and remove that leaf from its immediate parent.
    """
    while genome.depth() > MAX_DEPTH:
        _, chain = _deepest_leaf_chain(genome.root)
        if len(chain) < 2:
            break
        parent, leaf = chain[-2], chain[-1]
        parent.children.remove(leaf)
    while genome.node_count() > MAX_SEGMENTS:
        candidates = [n for n in genome.root.all_nodes() if n.children]
        if not candidates:
            break
        parent = max(candidates, key=lambda n: n.max_subdepth())
        parent.children.pop()
