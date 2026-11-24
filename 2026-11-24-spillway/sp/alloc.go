package sp

import (
	"fmt"
	"math"
	"sort"
)

// Options tunes allocation.
type Options struct {
	Coalesce bool // graph colouring only: conservative (Briggs) coalescing
}

// Allocation is the outcome of register allocation.
type Allocation struct {
	Allocator   string
	K           int
	Source      *Function // the original IR
	Rewritten   *Function // IR after spill rewriting (still virtual registers)
	Assign      []int     // vreg of Rewritten -> physical register, -1 if unused
	Machine     *Function // final code over K physical registers
	Rounds      int       // allocate/rewrite iterations
	SpilledVars int       // distinct original variables sent to memory
	Slots       int
	MovesBefore int // static mov count in the source
	MovesAfter  int // static mov count in the machine code
	Coalesced   int // moves removed (coalescing + same-register elision)
}

// StaticStats are code-size counters of the machine code.
type StaticStats struct {
	Instrs, SpillLoads, SpillStores, Moves int
}

// Static counts instructions of the allocated code.
func (a *Allocation) Static() StaticStats {
	var s StaticStats
	for _, b := range a.Machine.Blocks {
		for _, in := range b.Instrs {
			s.Instrs++
			switch in.Op {
			case OpSpillLd:
				s.SpillLoads++
			case OpSpillSt:
				s.SpillStores++
			case OpMov:
				s.Moves++
			}
		}
	}
	return s
}

// spillCosts weighs each register's defs+uses by 10^loopdepth.
func spillCosts(f *Function) []float64 {
	depth := f.LoopDepth()
	cost := make([]float64, f.NumRegs)
	for bi, b := range f.Blocks {
		w := math.Pow(10, float64(min(depth[bi], 6)))
		for i := range b.Instrs {
			in := &b.Instrs[i]
			if in.HasDst() {
				cost[in.Dst] += w
			}
			for _, u := range in.Uses() {
				cost[u] += w
			}
		}
	}
	return cost
}

// rewriteSpills sends every register in spill to a stack slot. Each use gets a
// fresh short-lived temporary loaded just before; each def stores just after.
// It returns the new function and which of its registers are unspillable temps.
func rewriteSpills(f *Function, spill []int, unspillable []bool) (*Function, []bool) {
	g := f.Clone()
	slot := map[int]int{}
	for _, r := range spill {
		if _, ok := slot[r]; !ok {
			slot[r] = g.Slots
			g.Slots++
		}
	}
	unsp := append([]bool(nil), unspillable...)
	newTemp := func(of int) int {
		id := g.NumRegs
		g.NumRegs++
		g.Names = append(g.Names, g.RegName(of)+"~")
		unsp = append(unsp, true)
		return id
	}
	for _, b := range g.Blocks {
		var out []Instr
		for _, in := range b.Instrs {
			in := in
			var pre, post []Instr
			remap := map[int]int{}
			for ai, a := range in.Args {
				if a.Imm || (in.Op == OpSpillSt && ai == 0) {
					continue
				}
				s, ok := slot[a.Reg]
				if !ok {
					continue
				}
				t, seen := remap[a.Reg]
				if !seen {
					t = newTemp(a.Reg)
					remap[a.Reg] = t
					pre = append(pre, Instr{Op: OpSpillLd, Dst: t, Args: []Operand{I(int64(s))}})
				}
				in.Args[ai] = R(t)
			}
			if in.HasDst() {
				if s, ok := slot[in.Dst]; ok {
					t := newTemp(in.Dst)
					in.Dst = t
					post = append(post, Instr{Op: OpSpillSt, Dst: -1, Args: []Operand{I(int64(s)), R(t)}})
				}
			}
			out = append(out, pre...)
			out = append(out, in)
			out = append(out, post...)
		}
		b.Instrs = out
	}
	return g, unsp
}

// finalize maps virtual to physical registers and drops self-moves.
func finalize(name string, src, rw *Function, assign []int, K, rounds, spilledVars int) *Allocation {
	m := rw.Clone()
	m.Names = nil
	m.NumRegs = K
	phys := func(o Operand) Operand {
		if o.Imm {
			return o
		}
		return R(assign[o.Reg])
	}
	for _, b := range m.Blocks {
		var out []Instr
		for _, in := range b.Instrs {
			in := in
			for ai := range in.Args {
				if in.Op == OpSpillSt && ai == 0 {
					continue
				}
				in.Args[ai] = phys(in.Args[ai])
			}
			if in.HasDst() {
				in.Dst = assign[in.Dst]
			}
			if in.Op == OpMov && !in.Args[0].Imm && in.Args[0].Reg == in.Dst {
				continue
			}
			out = append(out, in)
		}
		b.Instrs = out
	}
	countMoves := func(f *Function) int {
		n := 0
		for _, b := range f.Blocks {
			for _, in := range b.Instrs {
				if in.Op == OpMov && !in.Args[0].Imm {
					n++
				}
			}
		}
		return n
	}
	a := &Allocation{Allocator: name, K: K, Source: src, Rewritten: rw, Assign: assign, Machine: m,
		Rounds: rounds, SpilledVars: spilledVars, Slots: m.Slots}
	a.MovesBefore = countMoves(src)
	a.MovesAfter = countMoves(m)
	a.Coalesced = a.MovesBefore - a.MovesAfter
	return a
}

// Allocators names accepted by Allocate.
var Allocators = []string{"color", "linear", "naive"}

// MinK is the smallest register file the spill-rewriting scheme supports.
const MinK = 3

// Allocate compiles f for a K-register machine with the named allocator.
func Allocate(f *Function, name string, K int, opt Options) (*Allocation, error) {
	if K < MinK {
		return nil, fmt.Errorf("K must be at least %d (an instruction can need two sources and a destination)", MinK)
	}
	if err := f.Validate(); err != nil {
		return nil, err
	}
	cur := f.Clone()
	unsp := make([]bool, cur.NumRegs)
	spilledOrig := map[int]bool{}
	origN := f.NumRegs
	naiveFirst := name == "naive"
	for round := 1; round <= 60; round++ {
		var assign []int
		var spills []int
		var err error
		switch name {
		case "color":
			assign, spills = colorRound(cur, K, unsp, opt.Coalesce)
		case "linear", "naive":
			if naiveFirst {
				naiveFirst = false
				seen := map[int]bool{}
				for _, b := range cur.Blocks {
					for i := range b.Instrs {
						in := &b.Instrs[i]
						if in.HasDst() {
							seen[in.Dst] = true
						}
						for _, u := range in.Uses() {
							seen[u] = true
						}
					}
				}
				for r := range seen {
					spills = append(spills, r)
				}
				sort.Ints(spills)
			} else {
				assign, spills, err = linearRound(cur, K, unsp)
			}
		default:
			return nil, fmt.Errorf("unknown allocator %q (want color, linear or naive)", name)
		}
		if err != nil {
			return nil, err
		}
		if len(spills) == 0 {
			if err := CheckAssignment(cur, assign, K); err != nil {
				return nil, fmt.Errorf("internal: %s produced an invalid assignment: %w", name, err)
			}
			return finalize(name, f, cur, assign, K, round, len(spilledOrig)), nil
		}
		for _, r := range spills {
			if r < origN {
				spilledOrig[r] = true
			}
		}
		cur, unsp = rewriteSpills(cur, spills, unsp)
	}
	return nil, fmt.Errorf("%s: no fixed point after 60 spill rounds (K=%d too small?)", name, K)
}

// CheckAssignment independently verifies that no two registers holding live,
// distinct values share a physical register. It recomputes liveness itself and
// does not trust the allocator's data structures.
func CheckAssignment(f *Function, assign []int, K int) error {
	lv := f.Liveness()
	if lv.In[0].count() > 0 {
		return fmt.Errorf("registers live into entry")
	}
	var bad error
	rc := f.Reachable()
	f.LiveAfter(lv, func(bi, ii int, live Bitset) {
		if bad != nil || !rc[bi] {
			return
		}
		in := &f.Blocks[bi].Instrs[ii]
		if in.HasDst() {
			d := in.Dst
			if assign[d] < 0 || assign[d] >= K {
				bad = fmt.Errorf("%s has no valid register (%d)", f.RegName(d), assign[d])
				return
			}
			mvSrc := -1
			if in.Op == OpMov && !in.Args[0].Imm {
				mvSrc = in.Args[0].Reg
			}
			live.each(func(l int) {
				if bad == nil && l != d && l != mvSrc && assign[l] == assign[d] {
					bad = fmt.Errorf("%s and %s are simultaneously live but share r%d (block %s, instr %d)",
						f.RegName(d), f.RegName(l), assign[d], f.Blocks[bi].Name, ii)
				}
			})
		}
	})
	return bad
}
