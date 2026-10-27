package infer

import (
	"fmt"
	"math"
	"sort"

	"bayou/internal/bn"
	"bayou/internal/factor"
	"bayou/internal/graph"
)

// JT is a junction-tree inference engine for one network. Build it once with
// NewJT, then Calibrate under different evidence as often as needed: one
// calibration yields every single-variable (and family) marginal.
//
// Calibration is Shafer–Shenoy message passing (sum-product on the clique
// tree, no division, so zero probabilities are harmless).
type JT struct {
	Net  *bn.Network
	Tree *graph.JunctionTree

	pot     [][]*factor.Factor // CPT factors assigned to each clique
	home    []int              // variable -> index of a smallest clique containing it
	family  []int              // variable -> clique containing its whole family
	rootOrd []int              // clique indices in DFS pre-order from clique 0
	parent  []int              // DFS parent clique (-1 for root)
	parentE []int              // edge to parent
}

// NewJT builds the junction tree and assigns every CPT to a clique that
// contains its family (guaranteed to exist because the graph is moralised).
func NewJT(net *bn.Network) (*JT, error) {
	if errs := net.Validate(); len(errs) > 0 {
		return nil, errs[0]
	}
	tree, err := graph.BuildJunctionTree(net, graph.MinFill)
	if err != nil {
		return nil, err
	}
	j := &JT{Net: net, Tree: tree}
	nv := len(net.Vars)
	j.home = make([]int, nv)
	j.family = make([]int, nv)
	j.pot = make([][]*factor.Factor, len(tree.Cliques))
	for v := 0; v < nv; v++ {
		j.home[v] = -1
		for i, c := range tree.Cliques {
			if has(c, v) && (j.home[v] < 0 || len(c) < len(tree.Cliques[j.home[v]])) {
				j.home[v] = i
			}
		}
		fam := append([]int{v}, net.Vars[v].Parents...)
		sort.Ints(fam)
		j.family[v] = -1
		for i, c := range tree.Cliques {
			if subset(fam, c) && (j.family[v] < 0 || len(c) < len(tree.Cliques[j.family[v]])) {
				j.family[v] = i
			}
		}
		if j.home[v] < 0 || j.family[v] < 0 {
			return nil, fmt.Errorf("internal error: variable %s has no clique", net.Vars[v].Name)
		}
		j.pot[j.family[v]] = append(j.pot[j.family[v]], net.CPTFactor(v))
	}
	// DFS order for message scheduling.
	nc := len(tree.Cliques)
	j.parent = make([]int, nc)
	j.parentE = make([]int, nc)
	for i := range j.parent {
		j.parent[i], j.parentE[i] = -2, -1
	}
	if nc > 0 {
		j.parent[0] = -1
		stack := []int{0}
		for len(stack) > 0 {
			c := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			j.rootOrd = append(j.rootOrd, c)
			for _, ei := range tree.Adj[c] {
				e := tree.Edges[ei]
				o := e.A
				if o == c {
					o = e.B
				}
				if j.parent[o] == -2 {
					j.parent[o], j.parentE[o] = c, ei
					stack = append(stack, o)
				}
			}
		}
	}
	return j, nil
}

func has(sorted []int, v int) bool {
	i := sort.SearchInts(sorted, v)
	return i < len(sorted) && sorted[i] == v
}

func subset(a, b []int) bool {
	for _, x := range a {
		if !has(b, x) {
			return false
		}
	}
	return true
}

// Calibrated holds clique beliefs after message passing under some evidence.
type Calibrated struct {
	jt          *JT
	Ev          bn.Evidence
	Belief      []*factor.Factor // unnormalised clique beliefs: P(clique vars, e)
	LogEvidence float64
}

// Calibrate runs two-pass message passing under the given evidence.
func (j *JT) Calibrate(ev bn.Evidence) (cal *Calibrated, err error) {
	defer guard(&err)
	if err := checkQuery(j.Net, nil, ev); err != nil {
		return nil, err
	}
	nc := len(j.Tree.Cliques)
	psi := make([]*factor.Factor, nc)
	for i, c := range j.Tree.Cliques {
		card := make([]int, len(c))
		for k, v := range c {
			card[k] = j.Net.Card(v)
		}
		fs := append([]*factor.Factor{factor.New(c, card, nil)}, j.pot[i]...)
		psi[i] = factor.ProductAll(fs)
	}
	for v, s := range ev {
		ind := make([]float64, j.Net.Card(v))
		ind[s] = 1
		c := j.home[v]
		psi[c] = factor.Product(psi[c], factor.New([]int{v}, []int{len(ind)}, ind))
	}
	// msg[e][dir]: dir 0 = A->B, dir 1 = B->A
	msg := make([][2]*factor.Factor, len(j.Tree.Edges))
	send := func(from, ei int) *factor.Factor {
		e := j.Tree.Edges[ei]
		dir := 0
		if e.B == from {
			dir = 1
		}
		acc := psi[from]
		for _, oi := range j.Tree.Adj[from] {
			if oi == ei {
				continue
			}
			oe := j.Tree.Edges[oi]
			// message into `from` along edge oi
			odir := 1
			if oe.B == from {
				odir = 0
			}
			acc = factor.Product(acc, msg[oi][odir])
		}
		m := acc.Marginal(e.Sep...)
		msg[ei][dir] = m
		return m
	}
	// collect: children before parents (reverse pre-order)
	for k := len(j.rootOrd) - 1; k >= 0; k-- {
		c := j.rootOrd[k]
		if j.parent[c] >= 0 {
			send(c, j.parentE[c])
		}
	}
	// distribute: parents before children
	for _, c := range j.rootOrd {
		for _, ei := range j.Tree.Adj[c] {
			e := j.Tree.Edges[ei]
			o := e.A
			if o == c {
				o = e.B
			}
			if j.parent[o] == c && j.parentE[o] == ei {
				send(c, ei)
			}
		}
	}
	cal = &Calibrated{jt: j, Ev: ev, Belief: make([]*factor.Factor, nc)}
	for c := 0; c < nc; c++ {
		b := psi[c]
		for _, ei := range j.Tree.Adj[c] {
			e := j.Tree.Edges[ei]
			dir := 1
			if e.B == c {
				dir = 0
			}
			b = factor.Product(b, msg[ei][dir])
		}
		cal.Belief[c] = b
	}
	cal.LogEvidence = math.Inf(1)
	for _, b := range cal.Belief {
		if t := b.LogTotal(); t < cal.LogEvidence {
			cal.LogEvidence = t
		}
	}
	if nc == 0 {
		cal.LogEvidence = 0
	}
	if math.IsInf(cal.LogEvidence, -1) {
		return nil, ErrImpossible
	}
	return cal, nil
}

// Marginal returns P(v | e), normalised.
func (c *Calibrated) Marginal(v int) *factor.Factor {
	m := c.Belief[c.jt.home[v]].Marginal(v)
	n, _ := m.Normalized()
	return n
}

// Family returns P(v, parents(v) | e), normalised.
func (c *Calibrated) Family(v int) *factor.Factor {
	fam := append([]int{v}, c.jt.Net.Vars[v].Parents...)
	m := c.Belief[c.jt.family[v]].Marginal(fam...)
	n, _ := m.Normalized()
	return n
}

// Joint returns P(vs | e) if vs fit inside one clique, else an error
// (use VE for arbitrary joints).
func (c *Calibrated) Joint(vs ...int) (*factor.Factor, error) {
	sorted := append([]int(nil), vs...)
	sort.Ints(sorted)
	for i, cl := range c.jt.Tree.Cliques {
		if subset(sorted, cl) {
			m := c.Belief[i].Marginal(vs...)
			n, _ := m.Normalized()
			return n, nil
		}
	}
	return nil, fmt.Errorf("variables are not contained in a single clique; use variable elimination")
}

// Marginals calibrates and returns every variable's posterior (nil for observed ones
// is NOT used: observed variables get a point mass).
func (j *JT) Marginals(ev bn.Evidence) ([]*factor.Factor, float64, error) {
	cal, err := j.Calibrate(ev)
	if err != nil {
		return nil, 0, err
	}
	out := make([]*factor.Factor, len(j.Net.Vars))
	for v := range out {
		out[v] = cal.Marginal(v)
	}
	return out, cal.LogEvidence, nil
}

// Reparam recomputes the clique potentials after the network's CPT values
// changed (structure must be unchanged). EM uses it once per iteration.
func (j *JT) Reparam() {
	for i := range j.pot {
		j.pot[i] = j.pot[i][:0]
	}
	for v := range j.Net.Vars {
		j.pot[j.family[v]] = append(j.pot[j.family[v]], j.Net.CPTFactor(v))
	}
}
