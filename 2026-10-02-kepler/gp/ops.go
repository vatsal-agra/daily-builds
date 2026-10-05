package gp

import (
	"math"
	"sort"

	"kepler/expr"
)

func (is *island) randConst() *expr.Node {
	r := is.rng.Float64()
	switch {
	case r < 0.4:
		return expr.C(float64(is.rng.Intn(9) + 1))
	case r < 0.55:
		return expr.C(0.5)
	default:
		return expr.C(math.Round(is.rng.NormFloat64()*30) / 10)
	}
}

func (is *island) terminal() *expr.Node {
	if is.rng.Float64() < 0.7 {
		return expr.V(is.rng.Intn(is.nv))
	}
	return is.randConst()
}

// randTree builds a random tree: "full" reaches the depth on every branch,
// "grow" may stop early.
func (is *island) randTree(depth int, full bool) *expr.Node {
	if depth <= 1 || (!full && is.rng.Float64() < 0.3) {
		return is.terminal()
	}
	nu := len(is.cfg.Unary)
	if nu > 0 && is.rng.Float64() < 0.25 {
		return expr.U(is.cfg.Unary[is.rng.Intn(nu)], is.randTree(depth-1, full))
	}
	op := is.cfg.Binary[is.rng.Intn(len(is.cfg.Binary))]
	l := is.randTree(depth-1, full)
	r := is.randTree(depth-1, full)
	if op == "^" && is.rng.Float64() < 0.8 { // exponents are usually small constants
		r = expr.C(float64(is.rng.Intn(5)-1) + 0.5*float64(is.rng.Intn(2)))
	}
	return expr.B(op, l, r)
}

// mk simplifies, size-checks and scores a tree; nil when it violates limits.
func (is *island) mk(t *expr.Node) *Indiv {
	t = expr.Simplify(t)
	if t.Size() > is.cfg.MaxSize || t.Depth() > is.cfg.MaxDepth {
		return nil
	}
	return is.score(t)
}

func (is *island) score(t *expr.Node) *Indiv {
	is.evals++
	e := is.pr.NMSE(t)
	// tune constants when promising, or for a random 20% of the rest
	if len(t.Consts()) > 0 && !math.IsInf(e, 0) && (e < 0.5 || is.rng.Float64() < 0.2) {
		is.evals += 120
		e = is.pr.FitConstants(t, 120, 0)
	}
	c := t.Complexity()
	return &Indiv{Tree: t, NMSE: e, Comp: c, Score: scoreOf(e, c, is.cfg.Parsimony)}
}

func scoreOf(e float64, c int, pars float64) float64 {
	if math.IsInf(e, 0) || math.IsNaN(e) {
		return math.Inf(1)
	}
	return (e + 1e-12) * (1 + pars*float64(c))
}

func (is *island) init() {
	is.pop = nil
	for len(is.pop) < is.cfg.Pop {
		d := 2 + is.rng.Intn(4)
		if ind := is.mk(is.randTree(d, is.rng.Intn(2) == 0)); ind != nil {
			is.pop = append(is.pop, ind)
		}
	}
}

func (is *island) tournament(k int) *Indiv {
	best := is.pop[is.rng.Intn(len(is.pop))]
	for i := 1; i < k; i++ {
		c := is.pop[is.rng.Intn(len(is.pop))]
		if c.Score < best.Score {
			best = c
		}
	}
	return best
}

// step advances one generation.
func (is *island) step() {
	sort.SliceStable(is.pop, func(a, b int) bool { return is.pop[a].Score < is.pop[b].Score })
	next := make([]*Indiv, 0, is.cfg.Pop)
	next = append(next, is.pop[:2]...) // elitism
	for len(next) < is.cfg.Pop {
		var ind *Indiv
		r := is.rng.Float64()
		p := is.tournament(5)
		switch {
		case r < 0.50:
			ind = is.mk(is.crossover(p.Tree, is.tournament(5).Tree))
		case r < 0.65:
			ind = is.mk(is.subtreeMut(p.Tree))
		case r < 0.75:
			ind = is.mk(is.pointMut(p.Tree))
		case r < 0.82:
			ind = is.mk(is.hoist(p.Tree))
		case r < 0.95:
			ind = is.mk(is.constPerturb(p.Tree))
		default:
			ind = is.mk(is.randTree(2+is.rng.Intn(3), false))
		}
		if ind == nil || math.IsInf(ind.Score, 0) {
			ind = p // invalid offspring: carry the parent so the population stays valid
		}
		next = append(next, ind)
	}
	is.pop = next
}

// replaceAt returns a copy of root where node #idx (pre-order) is replaced by sub.
func replaceAt(root *expr.Node, idx int, sub *expr.Node) *expr.Node {
	cnt := 0
	var walk func(*expr.Node) *expr.Node
	walk = func(n *expr.Node) *expr.Node {
		if n == nil {
			return nil
		}
		if cnt == idx {
			cnt += n.Size()
			return sub
		}
		cnt++
		c := *n
		c.L = walk(n.L)
		c.R = walk(n.R)
		return &c
	}
	return walk(root)
}

// pick chooses a node index, biased toward internal nodes so crossover swaps
// structure rather than just leaves.
func (is *island) pick(t *expr.Node) (int, *expr.Node) {
	ns := t.Nodes()
	for tries := 0; tries < 3; tries++ {
		i := is.rng.Intn(len(ns))
		if ns[i].Kind == expr.Bin || ns[i].Kind == expr.Un || is.rng.Float64() < 0.1 {
			return i, ns[i]
		}
	}
	i := is.rng.Intn(len(ns))
	return i, ns[i]
}

func (is *island) crossover(a, b *expr.Node) *expr.Node {
	i, _ := is.pick(a)
	_, sb := is.pick(b)
	return replaceAt(a, i, sb.Clone())
}

func (is *island) subtreeMut(a *expr.Node) *expr.Node {
	i, _ := is.pick(a)
	return replaceAt(a, i, is.randTree(1+is.rng.Intn(3), false))
}

func (is *island) pointMut(a *expr.Node) *expr.Node {
	t := a.Clone()
	ns := t.Nodes()
	n := ns[is.rng.Intn(len(ns))]
	switch n.Kind {
	case expr.Const:
		n.Val = is.randConst().Val
	case expr.Var:
		n.Idx = is.rng.Intn(is.nv)
	case expr.Un:
		if len(is.cfg.Unary) > 0 {
			n.Op = is.cfg.Unary[is.rng.Intn(len(is.cfg.Unary))]
		}
	case expr.Bin:
		n.Op = is.cfg.Binary[is.rng.Intn(len(is.cfg.Binary))]
	}
	return t
}

func (is *island) hoist(a *expr.Node) *expr.Node {
	_, sub := is.pick(a)
	return sub.Clone()
}

func (is *island) constPerturb(a *expr.Node) *expr.Node {
	t := a.Clone()
	cs := t.Consts()
	if len(cs) == 0 {
		return is.pointMut(a)
	}
	for _, c := range cs {
		if is.rng.Float64() < 0.5 {
			c.Val *= 1 + 0.2*is.rng.NormFloat64()
		}
	}
	return t
}
