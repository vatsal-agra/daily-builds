// Package equiv holds Gatecraft's formal engines: SAT-based combinational and
// bounded-sequential equivalence checking, bounded model checking and
// k-induction, all with counterexamples that are replayed in the simulator.
package equiv

import (
	"fmt"
	"math/big"

	"gatecraft/internal/aig"
	"gatecraft/internal/sat"
)

// Unroller encodes successive time frames of an AIG into one SAT solver.
type Unroller struct {
	G      *aig.AIG
	S      *sat.Solver
	Frames []*aig.Encoder
	Init   bool // frame 0 starts from the reset state (else a free state)
	// PIHook lets a caller share input variables between machines.
	PIHook func(t int, pi aig.PI) (sat.Lit, bool)
	tt     sat.Lit
}

func NewUnroller(g *aig.AIG, s *sat.Solver, init bool) *Unroller {
	u := &Unroller{G: g, S: s, Init: init}
	u.tt = sat.MkLit(s.NewVar(), false)
	s.AddClause(u.tt)
	return u
}

// True returns a SAT literal fixed to true.
func (u *Unroller) True() sat.Lit { return u.tt }

// Frame returns (building if necessary) the encoder for time frame t.
func (u *Unroller) Frame(t int) *aig.Encoder {
	for len(u.Frames) <= t {
		k := len(u.Frames)
		e := aig.NewEncoder(u.G, u.S)
		e.FreeVar = func(id uint32) sat.Lit {
			n := u.G.Nodes[id]
			if n.Kind == aig.KInput && u.PIHook != nil {
				if l, ok := u.PIHook(k, u.G.PIs[n.Idx]); ok {
					return l
				}
			}
			return sat.MkLit(u.S.NewVar(), false)
		}
		live := u.G.LiveLatches()
		for i, l := range u.G.Latches {
			if !live[i] {
				continue
			}
			switch {
			case k == 0 && u.Init:
				e.Bind(l.Q, u.tt.NotIf(!l.Init))
			case k > 0:
				e.Bind(l.Q, u.Frames[k-1].Lit(l.D))
			}
		}
		u.Frames = append(u.Frames, e)
	}
	return u.Frames[t]
}

// Inputs reads the input port values of frame t from the current model.
func (u *Unroller) Inputs(t int) map[string]*big.Int {
	e := u.Frame(t)
	m := map[string]*big.Int{}
	for _, p := range u.G.Inputs {
		v := new(big.Int)
		for i, b := range p.Bits {
			if u.S.LitValue(e.Lit(b)) {
				v.SetBit(v, i, 1)
			}
		}
		m[p.Name] = v
	}
	return m
}

// State reads the latch values (by name) of frame t from the current model.
func (u *Unroller) State(t int) map[string]bool {
	e := u.Frame(t)
	m := map[string]bool{}
	for _, l := range u.G.Latches {
		m[l.Name] = u.S.LitValue(e.Lit(aig.Lit(l.Q << 1)))
	}
	return m
}

func singleClock(gs ...*aig.AIG) error {
	for _, g := range gs {
		if cs := g.Clocks(); len(cs) > 1 {
			return fmt.Errorf("sequential analysis assumes one clock domain, but the design has %d (%v)", len(cs), cs)
		}
	}
	return nil
}
