// Package bn defines the Bayesian-network data model: discrete variables, DAG
// structure, conditional probability tables (CPTs), validation, joint
// probability and forward (ancestral) sampling.
package bn

import (
	"fmt"
	"math"
	"math/rand"
	"sort"
	"strings"

	"bayou/internal/factor"
)

// Variable is a discrete random variable with its CPT P(var | parents).
//
// CPT layout: one row of len(States) probabilities per parent configuration;
// parent configurations are ordered with Parents[0] slowest and the last
// parent fastest, the child's own state is fastest of all.
type Variable struct {
	Name    string
	States  []string
	Parents []int
	CPT     []float64
}

// Network is a set of variables whose Parents form a DAG.
type Network struct {
	Name  string
	Vars  []Variable
	index map[string]int
}

// New returns an empty network.
func New(name string) *Network { return &Network{Name: name, index: map[string]int{}} }

// Evidence maps variable id to an observed state.
type Evidence map[int]int

// AddVar appends a variable with no parents and a uniform CPT; returns its id.
func (n *Network) AddVar(name string, states []string) (int, error) {
	if name == "" {
		return 0, fmt.Errorf("variable name is empty")
	}
	if _, dup := n.index[name]; dup {
		return 0, fmt.Errorf("duplicate variable %q", name)
	}
	if len(states) < 2 {
		return 0, fmt.Errorf("variable %q needs at least 2 states, has %d", name, len(states))
	}
	seen := map[string]bool{}
	for _, s := range states {
		if s == "" || seen[s] {
			return 0, fmt.Errorf("variable %q has an empty or duplicate state %q", name, s)
		}
		seen[s] = true
	}
	id := len(n.Vars)
	n.Vars = append(n.Vars, Variable{Name: name, States: append([]string(nil), states...)})
	n.index[name] = id
	n.SetParents(id, nil)
	return id, nil
}

// ID looks up a variable by name.
func (n *Network) ID(name string) (int, bool) { id, ok := n.index[name]; return id, ok }

// MustID is ID for names known to exist.
func (n *Network) MustID(name string) int {
	id, ok := n.index[name]
	if !ok {
		panic("bn: unknown variable " + name)
	}
	return id
}

// StateID looks up a state of variable v by name.
func (n *Network) StateID(v int, state string) (int, bool) {
	for i, s := range n.Vars[v].States {
		if s == state {
			return i, true
		}
	}
	return 0, false
}

// Card returns the number of states of v.
func (n *Network) Card(v int) int { return len(n.Vars[v].States) }

// ParentConfigs is the number of parent configurations (rows of the CPT).
func (n *Network) ParentConfigs(v int) int {
	k := 1
	for _, p := range n.Vars[v].Parents {
		k *= n.Card(p)
	}
	return k
}

// SetParents sets the parent list and resets the CPT to uniform.
func (n *Network) SetParents(v int, parents []int) {
	n.Vars[v].Parents = append([]int(nil), parents...)
	n.ResetUniform(v)
}

// ResetUniform sets v's CPT to uniform rows.
func (n *Network) ResetUniform(v int) {
	rows, c := n.ParentConfigs(v), n.Card(v)
	cpt := make([]float64, rows*c)
	for i := range cpt {
		cpt[i] = 1 / float64(c)
	}
	n.Vars[v].CPT = cpt
}

// Children returns, for every variable, the ids of its children.
func (n *Network) Children() [][]int {
	ch := make([][]int, len(n.Vars))
	for v := range n.Vars {
		for _, p := range n.Vars[v].Parents {
			ch[p] = append(ch[p], v)
		}
	}
	return ch
}

// Validate checks structure and CPTs. It returns every problem found.
func (n *Network) Validate() []error {
	var errs []error
	for v, x := range n.Vars {
		seen := map[int]bool{}
		for _, p := range x.Parents {
			switch {
			case p < 0 || p >= len(n.Vars):
				errs = append(errs, fmt.Errorf("%s: parent id %d out of range", x.Name, p))
			case p == v:
				errs = append(errs, fmt.Errorf("%s: variable is its own parent", x.Name))
			case seen[p]:
				errs = append(errs, fmt.Errorf("%s: parent %s listed twice", x.Name, n.Vars[p].Name))
			}
			if p >= 0 && p < len(n.Vars) {
				seen[p] = true
			}
		}
	}
	if len(errs) > 0 {
		return errs
	}
	if cyc := n.FindCycle(); cyc != nil {
		names := make([]string, len(cyc))
		for i, v := range cyc {
			names[i] = n.Vars[v].Name
		}
		errs = append(errs, fmt.Errorf("the graph has a cycle: %s", strings.Join(names, " -> ")))
		return errs
	}
	for v, x := range n.Vars {
		want := n.ParentConfigs(v) * n.Card(v)
		if len(x.CPT) != want {
			errs = append(errs, fmt.Errorf("%s: CPT has %d entries, want %d", x.Name, len(x.CPT), want))
			continue
		}
		c := n.Card(v)
		for r := 0; r < n.ParentConfigs(v); r++ {
			sum := 0.0
			for s := 0; s < c; s++ {
				p := x.CPT[r*c+s]
				if math.IsNaN(p) || p < 0 || p > 1+1e-9 {
					errs = append(errs, fmt.Errorf("%s: probability %g in row %d is not in [0,1]", x.Name, p, r))
				}
				sum += p
			}
			if math.Abs(sum-1) > 1e-6 {
				errs = append(errs, fmt.Errorf("%s: row %s sums to %g, not 1", x.Name, n.RowLabel(v, r), sum))
			}
		}
	}
	return errs
}

// RowLabel renders parent configuration r of v as "P1=a,P2=b" (or "(no parents)").
func (n *Network) RowLabel(v, r int) string {
	ps := n.Vars[v].Parents
	if len(ps) == 0 {
		return "(no parents)"
	}
	cfg := n.DecodeRow(v, r)
	parts := make([]string, len(ps))
	for i, p := range ps {
		parts[i] = n.Vars[p].Name + "=" + n.Vars[p].States[cfg[i]]
	}
	return strings.Join(parts, ",")
}

// DecodeRow turns a CPT row index into parent states (in Parents order).
func (n *Network) DecodeRow(v, r int) []int {
	ps := n.Vars[v].Parents
	cfg := make([]int, len(ps))
	for i := len(ps) - 1; i >= 0; i-- {
		c := n.Card(ps[i])
		cfg[i] = r % c
		r /= c
	}
	return cfg
}

// RowIndex is the inverse of DecodeRow for a full assignment (indexed by variable id).
func (n *Network) RowIndex(v int, assign []int) int {
	r := 0
	for _, p := range n.Vars[v].Parents {
		r = r*n.Card(p) + assign[p]
	}
	return r
}

// FindCycle returns the variables on some directed cycle, or nil.
func (n *Network) FindCycle() []int {
	const (
		white = iota
		grey
		black
	)
	color := make([]int, len(n.Vars))
	ch := n.Children()
	var stack []int
	var found []int
	var dfs func(v int) bool
	dfs = func(v int) bool {
		color[v] = grey
		stack = append(stack, v)
		for _, c := range ch[v] {
			if color[c] == grey {
				i := len(stack) - 1
				for stack[i] != c {
					i--
				}
				found = append(append([]int(nil), stack[i:]...), c)
				return true
			}
			if color[c] == white && dfs(c) {
				return true
			}
		}
		stack = stack[:len(stack)-1]
		color[v] = black
		return false
	}
	for v := range n.Vars {
		if color[v] == white && dfs(v) {
			return found
		}
	}
	return nil
}

// TopoOrder returns parents-before-children order (ties broken by id). It
// panics on cyclic graphs; call Validate first.
func (n *Network) TopoOrder() []int {
	indeg := make([]int, len(n.Vars))
	for v := range n.Vars {
		indeg[v] = len(n.Vars[v].Parents)
	}
	ch := n.Children()
	var ready, order []int
	for v := range n.Vars {
		if indeg[v] == 0 {
			ready = append(ready, v)
		}
	}
	for len(ready) > 0 {
		sort.Ints(ready)
		v := ready[0]
		ready = ready[1:]
		order = append(order, v)
		for _, c := range ch[v] {
			if indeg[c]--; indeg[c] == 0 {
				ready = append(ready, c)
			}
		}
	}
	if len(order) != len(n.Vars) {
		panic("bn: TopoOrder on cyclic network")
	}
	return order
}

// Ancestors returns the set of ancestors of the given variables, including them.
func (n *Network) Ancestors(vs []int) map[int]bool {
	out := map[int]bool{}
	var walk func(v int)
	walk = func(v int) {
		if out[v] {
			return
		}
		out[v] = true
		for _, p := range n.Vars[v].Parents {
			walk(p)
		}
	}
	for _, v := range vs {
		walk(v)
	}
	return out
}

// CPTFactor returns P(v | parents) as a factor over {v} ∪ parents.
func (n *Network) CPTFactor(v int) *factor.Factor {
	x := n.Vars[v]
	vars := append([]int{v}, x.Parents...)
	card := make([]int, len(vars))
	for i, u := range vars {
		card[i] = n.Card(u)
	}
	// Build in (parents..., child) order, then permute into sorted order.
	order := append(append([]int(nil), x.Parents...), v)
	ocard := make([]int, len(order))
	for i, u := range order {
		ocard[i] = n.Card(u)
	}
	sorted := append([]int(nil), order...)
	sort.Ints(sorted)
	scard := make([]int, len(sorted))
	pos := map[int]int{}
	for i, u := range sorted {
		scard[i] = n.Card(u)
		pos[u] = i
	}
	// stride in the sorted layout for each variable
	sst := make([]int, len(sorted))
	acc := 1
	for i := len(sorted) - 1; i >= 0; i-- {
		sst[i] = acc
		acc *= scard[i]
	}
	vals := make([]float64, acc)
	cnt := make([]int, len(order))
	for idx := 0; idx < len(x.CPT); idx++ {
		// idx enumerates (parents..., child) with child fastest: matches CPT layout.
		t := 0
		for i, u := range order {
			t += cnt[i] * sst[pos[u]]
		}
		vals[t] = x.CPT[idx]
		for k := len(order) - 1; k >= 0; k-- {
			cnt[k]++
			if cnt[k] < ocard[k] {
				break
			}
			cnt[k] = 0
		}
	}
	return factor.New(sorted, scard, vals)
}

// LogJoint returns log P(assign) for a complete assignment (indexed by variable id).
func (n *Network) LogJoint(assign []int) float64 {
	lp := 0.0
	for v := range n.Vars {
		p := n.Vars[v].CPT[n.RowIndex(v, assign)*n.Card(v)+assign[v]]
		if p <= 0 {
			return math.Inf(-1)
		}
		lp += math.Log(p)
	}
	return lp
}

// Sample draws one complete assignment by ancestral sampling.
func (n *Network) Sample(rng *rand.Rand) []int {
	return n.SampleOrdered(rng, n.TopoOrder())
}

// SampleOrdered is Sample with a precomputed topological order.
func (n *Network) SampleOrdered(rng *rand.Rand, order []int) []int {
	a := make([]int, len(n.Vars))
	for _, v := range order {
		c := n.Card(v)
		row := n.Vars[v].CPT[n.RowIndex(v, a)*c : (n.RowIndex(v, a)+1)*c]
		a[v] = Categorical(rng, row)
	}
	return a
}

// Categorical draws an index from a (not necessarily normalised) weight vector.
func Categorical(rng *rand.Rand, w []float64) int {
	tot := 0.0
	for _, x := range w {
		tot += x
	}
	u := rng.Float64() * tot
	acc := 0.0
	last := 0
	for i, x := range w {
		if x > 0 {
			last = i
		}
		acc += x
		if u < acc {
			return i
		}
	}
	return last
}

// Clone deep-copies the network.
func (n *Network) Clone() *Network {
	m := New(n.Name)
	for _, v := range n.Vars {
		id := len(m.Vars)
		m.Vars = append(m.Vars, Variable{Name: v.Name, States: append([]string(nil), v.States...),
			Parents: append([]int(nil), v.Parents...), CPT: append([]float64(nil), v.CPT...)})
		m.index[v.Name] = id
	}
	return m
}

// NumParams is the number of free parameters (for BIC).
func (n *Network) NumParams() int {
	k := 0
	for v := range n.Vars {
		k += n.ParentConfigs(v) * (n.Card(v) - 1)
	}
	return k
}

// ParseEvidence turns "A=x,B=y" style pairs into Evidence, with good errors.
func (n *Network) ParseEvidence(pairs []string) (Evidence, error) {
	ev := Evidence{}
	for _, p := range pairs {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		k := strings.IndexByte(p, '=')
		if k < 0 {
			return nil, fmt.Errorf("evidence %q: expected VAR=state", p)
		}
		name, st := strings.TrimSpace(p[:k]), strings.TrimSpace(p[k+1:])
		v, ok := n.ID(name)
		if !ok {
			return nil, fmt.Errorf("evidence %q: unknown variable %q%s", p, name, n.suggest(name))
		}
		s, ok := n.StateID(v, st)
		if !ok {
			return nil, fmt.Errorf("evidence %q: variable %s has no state %q (states: %s)", p, name, st, strings.Join(n.Vars[v].States, ", "))
		}
		if old, dup := ev[v]; dup && old != s {
			return nil, fmt.Errorf("evidence sets %s to both %s and %s", name, n.Vars[v].States[old], st)
		}
		ev[v] = s
	}
	return ev, nil
}

// ParseVarList resolves comma separated variable names.
func (n *Network) ParseVarList(s string) ([]int, error) {
	var out []int
	seen := map[int]bool{}
	for _, name := range strings.Split(s, ",") {
		name = strings.TrimSpace(name)
		if name == "" {
			continue
		}
		v, ok := n.ID(name)
		if !ok {
			return nil, fmt.Errorf("unknown variable %q%s", name, n.suggest(name))
		}
		if !seen[v] {
			seen[v] = true
			out = append(out, v)
		}
	}
	return out, nil
}

func (n *Network) suggest(name string) string {
	best, bd := "", 1<<30
	for _, v := range n.Vars {
		if d := editDistance(strings.ToLower(name), strings.ToLower(v.Name)); d < bd {
			best, bd = v.Name, d
		}
	}
	if best != "" && bd <= 2+len(name)/4 {
		return fmt.Sprintf(" (did you mean %q?)", best)
	}
	return ""
}

func editDistance(a, b string) int {
	prev := make([]int, len(b)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(a); i++ {
		cur := make([]int, len(b)+1)
		cur[0] = i
		for j := 1; j <= len(b); j++ {
			c := 1
			if a[i-1] == b[j-1] {
				c = 0
			}
			cur[j] = min(prev[j]+1, cur[j-1]+1, prev[j-1]+c)
		}
		prev = cur
	}
	return prev[len(b)]
}

// EvidenceString renders evidence deterministically.
func (n *Network) EvidenceString(ev Evidence) string {
	var ks []int
	for k := range ev {
		ks = append(ks, k)
	}
	sort.Ints(ks)
	parts := make([]string, len(ks))
	for i, k := range ks {
		parts[i] = n.Vars[k].Name + "=" + n.Vars[k].States[ev[k]]
	}
	return strings.Join(parts, ",")
}

func pow(x, y float64) float64 { return math.Pow(x, y) }
func sqrt(x float64) float64   { return math.Sqrt(x) }
func ln(x float64) float64     { return math.Log(x) }
