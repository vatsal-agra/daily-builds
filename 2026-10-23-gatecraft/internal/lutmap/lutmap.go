// Package lutmap maps an AIG onto k-input lookup tables (FPGA-style technology
// mapping): priority-cut enumeration, depth-optimal cut selection, then
// area-flow recovery under the depth constraint, with SAT-verifiable output.
package lutmap

import (
	"bufio"
	"fmt"
	"io"
	"sort"

	"gatecraft/internal/aig"
)

// LUT is one lookup table: output node, input nodes (positive polarity) and a
// truth table indexed by the input values (input 0 is the LSB of the index).
type LUT struct {
	Out   uint32
	In    []uint32
	Truth uint64
}

// Network is a mapped design. Roots keep the AIG literals (polarity included) so
// inversions at outputs / register inputs are absorbed by their consumers.
type Network struct {
	G     *aig.AIG
	K     int
	LUTs  []LUT
	Depth int
	index map[uint32]int // node id -> LUT index
}

type cut struct {
	leaves []uint32
	depth  int     // arrival at the cut output if implemented as a LUT
	flow   float64 // area flow
}

const maxCuts = 12

// Map covers the live logic of g with k-input LUTs (2 <= k <= 6).
func Map(g *aig.AIG, k int) (*Network, error) {
	if k < 2 || k > 6 {
		return nil, fmt.Errorf("LUT size must be between 2 and 6, got %d", k)
	}
	live := g.Live()
	n := len(g.Nodes)
	cuts := make([][]cut, n)
	arrival := make([]int, n)
	flow := make([]float64, n)
	fanout := make([]float64, n)
	for id, nd := range g.Nodes {
		if nd.Kind == aig.KAnd && live[id] {
			fanout[nd.A.ID()]++
			fanout[nd.B.ID()]++
		}
	}
	for _, r := range g.Roots() {
		if r != aig.Undef {
			fanout[r.ID()]++
		}
	}
	trivial := func(id uint32) cut { return cut{leaves: []uint32{id}} }

	for pass := 0; pass < 3; pass++ { // pass 0 = depth/flow with raw fanout, later passes use mapped fanout estimates
		for id := 1; id < n; id++ {
			nd := g.Nodes[id]
			if !live[id] {
				continue
			}
			if nd.Kind != aig.KAnd {
				cuts[id] = []cut{trivial(uint32(id))}
				arrival[id], flow[id] = 0, 0
				continue
			}
			ca, cb := cuts[nd.A.ID()], cuts[nd.B.ID()]
			var cs []cut
			for _, x := range ca {
				for _, y := range cb {
					leaves, ok := merge(x.leaves, y.leaves, k)
					if !ok {
						continue
					}
					c := cut{leaves: leaves}
					d, f := 0, 1.0
					for _, l := range leaves {
						if arrival[l] > d {
							d = arrival[l]
						}
						f += flow[l] / maxf(fanout[l], 1)
					}
					c.depth, c.flow = d+1, f
					cs = append(cs, c)
				}
			}
			cs = dominanceFilter(cs)
			cs = selectCuts(cs)
			best := cs[0]
			arrival[id], flow[id] = best.depth, best.flow
			cs = append(cs, trivial(uint32(id))) // lets parents use this node as a leaf
			cuts[id] = cs
		}
		if pass < 2 {
			// refine fanout estimates from the cover implied by the current best cuts
			sel := cover(g, live, cuts, arrival, flow, nil)
			for i := range fanout {
				fanout[i] = 0
			}
			for id := range sel {
				for _, l := range cuts[id][0].leaves {
					fanout[l]++
				}
			}
			for _, r := range g.Roots() {
				if r != aig.Undef {
					fanout[r.ID()]++
				}
			}
		}
	}

	// required times, then area recovery inside the depth bound
	target := 0
	for _, r := range g.Roots() {
		if r != aig.Undef && arrival[r.ID()] > target {
			target = arrival[r.ID()]
		}
	}
	required := make([]int, n)
	for i := range required {
		required[i] = 1 << 30
	}
	for _, r := range g.Roots() {
		if r != aig.Undef {
			required[r.ID()] = target
		}
	}
	chosen := cover(g, live, cuts, arrival, flow, required)

	net := &Network{G: g, K: k, index: map[uint32]int{}}
	var ids []int
	for id := range chosen {
		ids = append(ids, int(id))
	}
	sort.Ints(ids)
	depth := make([]int, n)
	for _, id := range ids {
		c := chosen[uint32(id)]
		d := 0
		for _, l := range c.leaves {
			if depth[l] > d {
				d = depth[l]
			}
		}
		depth[id] = d + 1
		if depth[id] > net.Depth {
			net.Depth = depth[id]
		}
		net.index[uint32(id)] = len(net.LUTs)
		net.LUTs = append(net.LUTs, LUT{Out: uint32(id), In: append([]uint32(nil), c.leaves...), Truth: truthTable(g, uint32(id), c.leaves)})
	}
	return net, nil
}

// selectCuts keeps a diverse set: the best cuts by depth (element 0 is always the
// depth-optimal one) plus the cheapest by area flow, which area recovery needs
// for nodes with timing slack.
func selectCuts(cs []cut) []cut {
	byDepth := append([]cut(nil), cs...)
	sort.Slice(byDepth, func(i, j int) bool {
		if byDepth[i].depth != byDepth[j].depth {
			return byDepth[i].depth < byDepth[j].depth
		}
		if byDepth[i].flow != byDepth[j].flow {
			return byDepth[i].flow < byDepth[j].flow
		}
		return len(byDepth[i].leaves) < len(byDepth[j].leaves)
	})
	byFlow := append([]cut(nil), cs...)
	sort.Slice(byFlow, func(i, j int) bool {
		if byFlow[i].flow != byFlow[j].flow {
			return byFlow[i].flow < byFlow[j].flow
		}
		return byFlow[i].depth < byFlow[j].depth
	})
	out := make([]cut, 0, maxCuts)
	seen := map[string]bool{}
	add := func(c cut) {
		key := fmt.Sprint(c.leaves)
		if !seen[key] && len(out) < maxCuts {
			seen[key] = true
			out = append(out, c)
		}
	}
	for i := 0; i < len(byDepth) && i < maxCuts/2; i++ {
		add(byDepth[i])
	}
	for i := 0; i < len(byFlow) && len(out) < maxCuts; i++ {
		add(byFlow[i])
	}
	return out
}

func maxf(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}

// cover selects, from the roots backwards, one cut per needed node. With
// required == nil it simply follows each node's best (first) cut; otherwise it
// re-chooses among cuts that meet the required time, minimising area flow.
func cover(g *aig.AIG, live []bool, cuts [][]cut, arrival []int, flow []float64, required []int) map[uint32]cut {
	chosen := map[uint32]cut{}
	n := len(g.Nodes)
	req := make([]int, n)
	for i := range req {
		req[i] = 1 << 30
	}
	need := make([]bool, n)
	for _, r := range g.Roots() {
		if r == aig.Undef {
			continue
		}
		need[r.ID()] = true
		if required != nil {
			req[r.ID()] = required[r.ID()]
		}
	}
	for id := n - 1; id >= 1; id-- {
		if !need[id] || !live[id] || g.Nodes[id].Kind != aig.KAnd {
			continue
		}
		pick := cuts[id][0]
		if required != nil {
			bestFlow := 1e18
			for _, c := range cuts[id] {
				if len(c.leaves) == 1 && c.leaves[0] == uint32(id) {
					continue
				}
				d := 0
				for _, l := range c.leaves {
					if arrival[l] > d {
						d = arrival[l]
					}
				}
				if d+1 > req[id] {
					continue
				}
				// area cost: this LUT plus the (estimated) cones of leaves nobody needs yet
				cost := 1.0
				for _, l := range c.leaves {
					if g.Nodes[l].Kind == aig.KAnd && !need[l] {
						cost += flow[l]
					}
				}
				if cost < bestFlow {
					bestFlow, pick = cost, c
				}
			}
		}
		chosen[uint32(id)] = pick
		for _, l := range pick.leaves {
			need[l] = true
			if required != nil && req[id]-1 < req[l] {
				req[l] = req[id] - 1
			}
		}
	}
	return chosen
}

func merge(a, b []uint32, k int) ([]uint32, bool) {
	out := make([]uint32, 0, k)
	i, j := 0, 0
	for i < len(a) || j < len(b) {
		var v uint32
		switch {
		case j >= len(b) || (i < len(a) && a[i] < b[j]):
			v = a[i]
			i++
		case i >= len(a) || b[j] < a[i]:
			v = b[j]
			j++
		default:
			v = a[i]
			i++
			j++
		}
		if len(out) == k {
			return nil, false
		}
		out = append(out, v)
	}
	return out, true
}

func isSubset(a, b []uint32) bool { // a ⊆ b, both sorted
	i := 0
	for _, x := range b {
		if i < len(a) && a[i] == x {
			i++
		}
	}
	return i == len(a)
}

func dominanceFilter(cs []cut) []cut {
	sort.Slice(cs, func(i, j int) bool { return len(cs[i].leaves) < len(cs[j].leaves) })
	var out []cut
	for _, c := range cs {
		dom := false
		for _, o := range out {
			if isSubset(o.leaves, c.leaves) {
				dom = true
				break
			}
		}
		if !dom {
			out = append(out, c)
		}
	}
	return out
}

// truthTable evaluates the cone of root over all assignments of the leaves.
func truthTable(g *aig.AIG, root uint32, leaves []uint32) uint64 {
	k := len(leaves)
	var tt uint64
	pos := map[uint32]int{}
	for i, l := range leaves {
		pos[l] = i
	}
	for m := 0; m < 1<<uint(k); m++ {
		memo := map[uint32]bool{}
		var eval func(id uint32) bool
		eval = func(id uint32) bool {
			if p, ok := pos[id]; ok {
				return m>>uint(p)&1 == 1
			}
			if v, ok := memo[id]; ok {
				return v
			}
			nd := g.Nodes[id]
			var v bool
			switch nd.Kind {
			case aig.KConst:
				v = false
			case aig.KAnd:
				v = (eval(nd.A.ID()) != nd.A.Neg()) && (eval(nd.B.ID()) != nd.B.Neg())
			default:
				panic("lutmap: cut does not cover the cone")
			}
			memo[id] = v
			return v
		}
		if eval(root) {
			tt |= 1 << uint(m)
		}
	}
	return tt
}

// ------------------------------------------------------------------ analysis

// Histogram counts LUTs by number of used inputs.
func (n *Network) Histogram() map[int]int {
	h := map[int]int{}
	for _, l := range n.LUTs {
		h[len(l.In)]++
	}
	return h
}

// Eval computes every LUT output for 64 parallel lanes given node values for
// inputs/latches in val (indexed by AIG node id); results are stored in val.
func (n *Network) Eval(val []uint64) {
	for _, l := range n.LUTs { // LUTs are ordered by node id, which is topological
		var out uint64
		for m := 0; m < 1<<uint(len(l.In)); m++ {
			if l.Truth>>uint(m)&1 == 0 {
				continue
			}
			sel := ^uint64(0)
			for i, in := range l.In {
				if m>>uint(i)&1 == 1 {
					sel &= val[in]
				} else {
					sel &= ^val[in]
				}
			}
			out |= sel
		}
		val[l.Out] = out
	}
}

// ToAIG rebuilds an AIG from the LUT network (Shannon decomposition of each
// table) preserving ports and register names, for formal verification of the mapping.
func (n *Network) ToAIG() *aig.AIG {
	g := n.G
	out := aig.New()
	m := make([]aig.Lit, len(g.Nodes))
	for i := range m {
		m[i] = aig.Undef
	}
	m[0] = aig.False
	for _, pi := range g.PIs {
		m[pi.Node] = out.AddInput(pi.Port, pi.Bit)
	}
	live := g.LiveLatches()
	for i, l := range g.Latches {
		if live[i] {
			m[l.Q] = out.AddLatch(l.Name, l.Init)
			out.Latches[len(out.Latches)-1].Clock = l.Clock
		}
	}
	var lutLit func(id uint32) aig.Lit
	lutLit = func(id uint32) aig.Lit {
		if m[id] != aig.Undef {
			return m[id]
		}
		l := n.LUTs[n.index[id]]
		in := make([]aig.Lit, len(l.In))
		for i, x := range l.In {
			in[i] = lutLit(x)
		}
		m[id] = shannon(out, l.Truth, in)
		return m[id]
	}
	tr := func(l aig.Lit) aig.Lit { return lutLit(l.ID()).NotIf(l.Neg()) }
	for _, p := range g.Inputs {
		bits := make([]aig.Lit, len(p.Bits))
		for i, b := range p.Bits {
			bits[i] = m[b.ID()].NotIf(b.Neg())
		}
		out.Inputs = append(out.Inputs, aig.Port{Name: p.Name, Bits: bits})
	}
	for _, p := range g.Outputs {
		bits := make([]aig.Lit, len(p.Bits))
		for i, b := range p.Bits {
			bits[i] = tr(b)
		}
		out.Outputs = append(out.Outputs, aig.Port{Name: p.Name, Bits: bits})
	}
	k := 0
	for i, l := range g.Latches {
		if live[i] {
			out.Latches[k].D = tr(l.D)
			k++
		}
	}
	for _, p := range g.Asserts {
		out.Asserts = append(out.Asserts, aig.Prop{Name: p.Name, Lit: tr(p.Lit)})
	}
	for _, p := range g.Assumes {
		out.Assumes = append(out.Assumes, aig.Prop{Name: p.Name, Lit: tr(p.Lit)})
	}
	out.Removed = map[string]string{}
	for i, l := range g.Latches {
		if !live[i] {
			out.Removed[l.Name] = "dead"
		}
	}
	return out
}

func shannon(g *aig.AIG, tt uint64, in []aig.Lit) aig.Lit {
	k := len(in)
	if k == 0 {
		if tt&1 == 1 {
			return aig.True
		}
		return aig.False
	}
	half := uint(1) << uint(k-1)
	mask := uint64(1)<<half - 1
	lo, hi := tt&mask, (tt>>half)&mask // variable k-1 = 0 / 1
	return g.Mux(in[k-1], shannon(g, hi, in[:k-1]), shannon(g, lo, in[:k-1]))
}

// ------------------------------------------------------------------ BLIF

func netName(g *aig.AIG, id uint32) string {
	nd := g.Nodes[id]
	switch nd.Kind {
	case aig.KInput:
		pi := g.PIs[nd.Idx]
		if p := g.FindInput(pi.Port); p != nil && len(p.Bits) > 1 {
			return fmt.Sprintf("%s[%d]", pi.Port, pi.Bit)
		}
		return pi.Port
	case aig.KLatch:
		return fmt.Sprintf("r%d", nd.Idx)
	case aig.KConst:
		return "zero"
	}
	return fmt.Sprintf("n%d", id)
}

// WriteBLIF writes the LUT network as BLIF (.names per LUT, .latch per register).
func (n *Network) WriteBLIF(w io.Writer, model string) error {
	bw := bufio.NewWriter(w)
	g := n.G
	fmt.Fprintf(bw, ".model %s\n.inputs", model)
	for _, pi := range g.PIs {
		fmt.Fprintf(bw, " %s", netName(g, pi.Node))
	}
	fmt.Fprintf(bw, "\n.outputs")
	var outs []string
	for _, p := range g.Outputs {
		for i := range p.Bits {
			nm := p.Name
			if len(p.Bits) > 1 {
				nm = fmt.Sprintf("%s[%d]", p.Name, i)
			}
			outs = append(outs, nm)
			fmt.Fprintf(bw, " %s", nm)
		}
	}
	fmt.Fprintln(bw)
	fmt.Fprintf(bw, ".names zero\n")
	live := g.LiveLatches()
	for i, l := range g.Latches {
		if live[i] {
			iv := 0
			if l.Init {
				iv = 1
			}
			fmt.Fprintf(bw, ".latch d%d r%d re %s %d\n", i, i, l.Clock, iv)
		}
	}
	for _, l := range n.LUTs {
		fmt.Fprintf(bw, ".names")
		for _, in := range l.In {
			fmt.Fprintf(bw, " %s", netName(g, in))
		}
		fmt.Fprintf(bw, " %s\n", netName(g, l.Out))
		for m := 0; m < 1<<uint(len(l.In)); m++ {
			if l.Truth>>uint(m)&1 == 1 {
				for i := range l.In {
					fmt.Fprintf(bw, "%d", m>>uint(i)&1)
				}
				fmt.Fprintf(bw, " 1\n")
			}
		}
	}
	buf := func(dst string, l aig.Lit) {
		switch l {
		case aig.False:
			fmt.Fprintf(bw, ".names %s\n", dst)
		case aig.True:
			fmt.Fprintf(bw, ".names %s\n1\n", dst)
		default:
			if l.Neg() {
				fmt.Fprintf(bw, ".names %s %s\n0 1\n", netName(g, l.ID()), dst)
			} else {
				fmt.Fprintf(bw, ".names %s %s\n1 1\n", netName(g, l.ID()), dst)
			}
		}
	}
	k := 0
	for _, p := range g.Outputs {
		for _, b := range p.Bits {
			buf(outs[k], b)
			k++
		}
	}
	for i, l := range g.Latches {
		if live[i] {
			buf(fmt.Sprintf("d%d", i), l.D)
		}
	}
	fmt.Fprintf(bw, ".end\n")
	return bw.Flush()
}

// Verify cross-checks the network against the AIG by 64-lane random simulation of
// every output and every live register's next-state function.
func (n *Network) Verify(cycles int, seed uint64) error {
	g := n.G
	sim := aig.NewSimulator(g)
	val := make([]uint64, len(g.Nodes))
	live := g.LiveLatches()
	x := seed | 1
	rnd := func() uint64 { // xorshift64
		x ^= x << 13
		x ^= x >> 7
		x ^= x << 17
		return x
	}
	value := func(l aig.Lit) uint64 {
		v := val[l.ID()]
		if l.Neg() {
			return ^v
		}
		return v
	}
	for c := 0; c < cycles; c++ {
		for i := range g.PIs {
			sim.SetPI(i, rnd())
		}
		sim.Eval()
		for i := range val {
			val[i] = 0
		}
		for _, pi := range g.PIs {
			val[pi.Node] = sim.Val[pi.Node]
		}
		for i, l := range g.Latches {
			val[l.Q] = sim.State[i]
		}
		n.Eval(val)
		for _, p := range g.Outputs {
			for i, b := range p.Bits {
				if value(b) != sim.Lit(b) {
					return fmt.Errorf("cycle %d: output %s[%d] differs between LUT network and AIG", c, p.Name, i)
				}
			}
		}
		for i, l := range g.Latches {
			if live[i] && value(l.D) != sim.Lit(l.D) {
				return fmt.Errorf("cycle %d: next-state of register %s differs", c, l.Name)
			}
		}
		sim.Clock(nil)
	}
	return nil
}

// Summary describes the mapping in one line.
func (n *Network) Summary() string {
	h := n.Histogram()
	var ks []int
	for k := range h {
		ks = append(ks, k)
	}
	sort.Ints(ks)
	s := fmt.Sprintf("%d-LUT mapping: %d LUTs, depth %d, %d flip-flops; LUT fan-in histogram:", n.K, len(n.LUTs), n.Depth, countLive(n.G))
	for _, k := range ks {
		s += fmt.Sprintf(" %d×%d", h[k], k)
	}
	return s
}

func countLive(g *aig.AIG) int {
	c := 0
	for _, l := range g.LiveLatches() {
		if l {
			c++
		}
	}
	return c
}
