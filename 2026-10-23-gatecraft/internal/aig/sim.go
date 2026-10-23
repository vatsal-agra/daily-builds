package aig

// Simulator evaluates an AIG on 64 parallel pattern lanes.
type Simulator struct {
	G     *AIG
	Val   []uint64 // per-node value (positive polarity)
	State []uint64 // per-latch current value
}

// NewSimulator creates a simulator with latches at their init values.
func NewSimulator(g *AIG) *Simulator {
	s := &Simulator{G: g, Val: make([]uint64, len(g.Nodes)), State: make([]uint64, len(g.Latches))}
	s.Reset()
	return s
}

// Reset sets every latch to its initial value in all lanes.
func (s *Simulator) Reset() {
	for i, l := range s.G.Latches {
		if l.Init {
			s.State[i] = ^uint64(0)
		} else {
			s.State[i] = 0
		}
	}
}

// Lit returns the lane word of literal l (valid after Eval).
func (s *Simulator) Lit(l Lit) uint64 {
	v := s.Val[l.ID()]
	if l.Neg() {
		return ^v
	}
	return v
}

// SetPI sets primary input node values (by PI index).
func (s *Simulator) SetPI(idx int, w uint64) { s.Val[s.G.PIs[idx].Node] = w }

// Eval propagates PI and latch values through the combinational logic.
func (s *Simulator) Eval() {
	g := s.G
	for i, l := range g.Latches {
		s.Val[l.Q] = s.State[i]
	}
	s.Val[0] = 0
	for i := range g.Nodes {
		n := &g.Nodes[i]
		if n.Kind == KAnd {
			a := s.Val[n.A.ID()]
			if n.A.Neg() {
				a = ^a
			}
			b := s.Val[n.B.ID()]
			if n.B.Neg() {
				b = ^b
			}
			s.Val[i] = a & b
		}
	}
}

// Clock latches the D values of every latch whose Clock is in the set (nil = all).
func (s *Simulator) Clock(only func(l *Latch) bool) {
	next := make([]uint64, len(s.State))
	copy(next, s.State)
	for i := range s.G.Latches {
		l := &s.G.Latches[i]
		if only == nil || only(l) {
			next[i] = s.Lit(l.D)
		}
	}
	s.State = next
}
