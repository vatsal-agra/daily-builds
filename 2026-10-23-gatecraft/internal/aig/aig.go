// Package aig implements a structurally-hashed And-Inverter Graph with
// sequential state (latches), the central netlist representation of Gatecraft.
package aig

import (
	"fmt"
	"sort"
)

// Lit is a literal: node id << 1 | complement bit.
type Lit uint32

const (
	False Lit = 0
	True  Lit = 1
	// Undef marks "no value" inside the elaborator's symbolic executor.
	Undef Lit = 0xFFFFFFFF
)

func (l Lit) ID() uint32 { return uint32(l) >> 1 }
func (l Lit) Neg() bool  { return l&1 == 1 }
func (l Lit) Not() Lit   { return l ^ 1 }
func (l Lit) Pos() Lit   { return l &^ 1 }
func (l Lit) NotIf(b bool) Lit {
	if b {
		return l ^ 1
	}
	return l
}
func (l Lit) String() string {
	switch l {
	case False:
		return "0"
	case True:
		return "1"
	case Undef:
		return "undef"
	}
	if l.Neg() {
		return fmt.Sprintf("!n%d", l.ID())
	}
	return fmt.Sprintf("n%d", l.ID())
}

// Kind of a node.
type Kind uint8

const (
	KConst Kind = iota
	KInput
	KLatch
	KAnd
)

// Node is one graph vertex. For KAnd, A <= B are the fanin literals.
// For KInput / KLatch, Idx indexes PIs / Latches.
type Node struct {
	Kind Kind
	A, B Lit
	Idx  int32
}

// PI describes one primary-input bit.
type PI struct {
	Port string // port name
	Bit  int    // bit index within the port
	Node uint32
}

// Latch is a flip-flop: Q is the node id, D the next-state literal.
type Latch struct {
	Q     uint32
	D     Lit
	Init  bool
	Clock string // name of the clock primary input
	Name  string // hierarchical register name, e.g. "u1.count[3]"
}

// Port is a named multi-bit interface signal (bit 0 = LSB).
type Port struct {
	Name string
	Bits []Lit
}

// Prop is an assert/assume predicate (true = holds).
type Prop struct {
	Name string
	Lit  Lit
}

// AIG is the netlist.
type AIG struct {
	Nodes   []Node
	hash    map[uint64]uint32
	PIs     []PI
	Latches []Latch
	Inputs  []Port // input ports (Bits are positive PI literals)
	Outputs []Port
	Asserts []Prop
	Assumes []Prop
	// Names maps every named internal/external signal to its bits (for waveforms & tracing).
	Names     map[string][]Lit
	NameOrder []string
	// Removed records latches eliminated by sequential optimisation: original name ->
	// "0"/"1" (stuck at constant), "dead" (unobservable) or the name of the surviving equal latch.
	Removed map[string]string
	// Rewrite enables 2-level local rewriting inside And().
	Rewrite bool
}

// New returns an empty AIG containing only the constant node.
func New() *AIG {
	g := &AIG{hash: map[uint64]uint32{}, Names: map[string][]Lit{}}
	g.Nodes = append(g.Nodes, Node{Kind: KConst})
	return g
}

// NumAnds counts AND nodes.
func (g *AIG) NumAnds() int {
	n := 0
	for _, nd := range g.Nodes {
		if nd.Kind == KAnd {
			n++
		}
	}
	return n
}

// AddInput creates a primary input bit.
func (g *AIG) AddInput(port string, bit int) Lit {
	id := uint32(len(g.Nodes))
	g.Nodes = append(g.Nodes, Node{Kind: KInput, Idx: int32(len(g.PIs))})
	g.PIs = append(g.PIs, PI{Port: port, Bit: bit, Node: id})
	return Lit(id << 1)
}

// AddLatch creates a latch and returns its Q literal; set D later.
func (g *AIG) AddLatch(name string, init bool) Lit {
	id := uint32(len(g.Nodes))
	g.Nodes = append(g.Nodes, Node{Kind: KLatch, Idx: int32(len(g.Latches))})
	g.Latches = append(g.Latches, Latch{Q: id, D: False, Init: init, Name: name})
	return Lit(id << 1)
}

// SetName registers a named signal (first registration wins ordering).
func (g *AIG) SetName(name string, bits []Lit) {
	if _, ok := g.Names[name]; !ok {
		g.NameOrder = append(g.NameOrder, name)
	}
	g.Names[name] = append([]Lit(nil), bits...)
}

func key(a, b Lit) uint64 { return uint64(a)<<32 | uint64(b) }

// And builds (or finds) a & b.
func (g *AIG) And(a, b Lit) Lit {
	if a == False || b == False {
		return False
	}
	if a == True {
		return b
	}
	if b == True {
		return a
	}
	if a == b {
		return a
	}
	if a == b.Not() {
		return False
	}
	if g.Rewrite {
		if r, ok := g.rewrite2(a, b); ok {
			return r
		}
	}
	if a > b {
		a, b = b, a
	}
	k := key(a, b)
	if id, ok := g.hash[k]; ok {
		return Lit(id << 1)
	}
	id := uint32(len(g.Nodes))
	g.Nodes = append(g.Nodes, Node{Kind: KAnd, A: a, B: b})
	g.hash[k] = id
	return Lit(id << 1)
}

func (g *AIG) isAnd(l Lit) bool { return g.Nodes[l.ID()].Kind == KAnd }

// rewrite2 applies Brummayer–Biere style two-level simplification rules.
func (g *AIG) rewrite2(a, b Lit) (Lit, bool) {
	for pass := 0; pass < 2; pass++ {
		if g.isAnd(a) {
			na := g.Nodes[a.ID()]
			x, y := na.A, na.B
			if !a.Neg() {
				// a = x&y
				if b == x || b == y {
					return a, true
				}
				if b == x.Not() || b == y.Not() {
					return False, true
				}
				if g.isAnd(b) {
					nb := g.Nodes[b.ID()]
					u, v := nb.A, nb.B
					if !b.Neg() {
						if x == u.Not() || x == v.Not() || y == u.Not() || y == v.Not() {
							return False, true
						}
						// shared conjunct: (x&y)&(x&v) = a & v
						switch {
						case x == u || y == u:
							return g.And(a, v), true
						case x == v || y == v:
							return g.And(a, u), true
						}
					} else {
						// a & !(u&v)
						switch {
						case u == x || u == y:
							return g.And(a, v.Not()), true
						case v == x || v == y:
							return g.And(a, u.Not()), true
						case u == x.Not() || u == y.Not() || v == x.Not() || v == y.Not():
							return a, true // a implies one of u,v false => !(u&v) true
						}
					}
				}
			} else {
				// a = !(x&y)
				if b == x.Not() || b == y.Not() {
					return b, true // b implies !(x&y)
				}
				if b == x {
					return g.And(b, y.Not()), true
				}
				if b == y {
					return g.And(b, x.Not()), true
				}
			}
		}
		a, b = b, a
	}
	return 0, false
}

// Or, Xor, Mux, etc.
func (g *AIG) Or(a, b Lit) Lit   { return g.And(a.Not(), b.Not()).Not() }
func (g *AIG) Xor(a, b Lit) Lit  { return g.Or(g.And(a, b.Not()), g.And(a.Not(), b)) }
func (g *AIG) Xnor(a, b Lit) Lit { return g.Xor(a, b).Not() }
func (g *AIG) Mux(c, t, f Lit) Lit {
	if t == f {
		return t
	}
	if c == True {
		return t
	}
	if c == False {
		return f
	}
	return g.Or(g.And(c, t), g.And(c.Not(), f))
}

// Levels returns the unit-delay level of every node (inputs/latches/const = 0).
func (g *AIG) Levels() []int {
	lv := make([]int, len(g.Nodes))
	for i, n := range g.Nodes {
		if n.Kind == KAnd {
			a, b := lv[n.A.ID()], lv[n.B.ID()]
			if b > a {
				a = b
			}
			lv[i] = a + 1
		}
	}
	return lv
}

// Roots returns every literal the design observably depends on (live latches' D included).
func (g *AIG) Roots() []Lit {
	var r []Lit
	for _, p := range g.Outputs {
		r = append(r, p.Bits...)
	}
	for _, p := range g.Asserts {
		r = append(r, p.Lit)
	}
	for _, p := range g.Assumes {
		r = append(r, p.Lit)
	}
	_, ll := g.liveInfo()
	for i, l := range g.Latches {
		if ll[i] {
			r = append(r, l.D)
		}
	}
	return r
}

// Depth is the maximum level over all roots.
func (g *AIG) Depth() int {
	lv := g.Levels()
	d := 0
	for _, r := range g.Roots() {
		if r == Undef {
			continue
		}
		if lv[r.ID()] > d {
			d = lv[r.ID()]
		}
	}
	return d
}

// liveInfo marks nodes and latches reachable from outputs/properties, following latch D inputs.
func (g *AIG) liveInfo() (nodes []bool, latches []bool) {
	nodes = make([]bool, len(g.Nodes))
	latches = make([]bool, len(g.Latches))
	var stack []uint32
	push := func(l Lit) {
		if l == Undef {
			return
		}
		if id := l.ID(); !nodes[id] {
			nodes[id] = true
			stack = append(stack, id)
		}
	}
	for _, p := range g.Outputs {
		for _, b := range p.Bits {
			push(b)
		}
	}
	for _, p := range g.Asserts {
		push(p.Lit)
	}
	for _, p := range g.Assumes {
		push(p.Lit)
	}
	for len(stack) > 0 {
		id := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		n := g.Nodes[id]
		switch n.Kind {
		case KAnd:
			push(n.A)
			push(n.B)
		case KLatch:
			latches[n.Idx] = true
			push(g.Latches[n.Idx].D)
		}
	}
	return
}

// Live returns the nodes reachable from outputs and properties.
func (g *AIG) Live() []bool { n, _ := g.liveInfo(); return n }

// LiveLatches marks latches that can influence an output or property.
func (g *AIG) LiveLatches() []bool { _, l := g.liveInfo(); return l }

// Stats summarises a netlist.
type Stats struct {
	Inputs, InputBits   int
	Outputs, OutputBits int
	Latches             int
	Ands                int // live AND nodes
	Depth               int
}

// Stats counts live logic.
func (g *AIG) Stats() Stats {
	live := g.Live()
	s := Stats{Inputs: len(g.Inputs), Outputs: len(g.Outputs), Depth: g.Depth()}
	for _, b := range g.LiveLatches() {
		if b {
			s.Latches++
		}
	}
	for _, p := range g.Inputs {
		s.InputBits += len(p.Bits)
	}
	for _, p := range g.Outputs {
		s.OutputBits += len(p.Bits)
	}
	for i, n := range g.Nodes {
		if n.Kind == KAnd && live[i] {
			s.Ands++
		}
	}
	return s
}

func (s Stats) String() string {
	return fmt.Sprintf("inputs=%d(%db) outputs=%d(%db) latches=%d ands=%d depth=%d",
		s.Inputs, s.InputBits, s.Outputs, s.OutputBits, s.Latches, s.Ands, s.Depth)
}

// Clocks returns the sorted distinct clock names.
func (g *AIG) Clocks() []string {
	set := map[string]bool{}
	for _, l := range g.Latches {
		set[l.Clock] = true
	}
	var cs []string
	for c := range set {
		cs = append(cs, c)
	}
	sort.Strings(cs)
	return cs
}

// FindInput returns the input port by name.
func (g *AIG) FindInput(name string) *Port {
	for i := range g.Inputs {
		if g.Inputs[i].Name == name {
			return &g.Inputs[i]
		}
	}
	return nil
}

// FindOutput returns the output port by name.
func (g *AIG) FindOutput(name string) *Port {
	for i := range g.Outputs {
		if g.Outputs[i].Name == name {
			return &g.Outputs[i]
		}
	}
	return nil
}
