package sable

import (
	"fmt"
	"sort"
)

// ---- target description ----

// Target describes the register file. Registers 0..K-1 are allocatable;
// r0..r(Caller-1) are caller-saved, the rest callee-saved. Two extra scratch
// registers (K, K+1) are reserved for spill reloads and never allocated.
type Target struct {
	K      int
	Caller int
}

func NewTarget(k int) Target {
	if k < 2 {
		panic("Target needs at least 2 allocatable registers")
	}
	callee := k / 2
	return Target{K: k, Caller: k - callee}
}
func (t Target) Scratch0() int       { return t.K }
func (t Target) Scratch1() int       { return t.K + 1 }
func (t Target) NumPhys() int        { return t.K + 2 }
func (t Target) IsCallee(r int) bool { return r >= t.Caller && r < t.K }

type Alg int

const (
	LinearScan Alg = iota
	GraphColor
)

func (a Alg) String() string {
	if a == LinearScan {
		return "linear-scan"
	}
	return "graph-color"
}

// AllocStats reports what an allocator did to one function.
type AllocStats struct {
	Alg          Alg
	Spilled      int // virtual registers living in memory
	MovesRemoved int
	CalleeSaved  int // callee-saved registers used (each costs a save + restore)
	Coalesced    int
	Rounds       int
}

// ---- bitsets & liveness ----

type bitset []uint64

func newBitset(n int) bitset       { return make(bitset, (n+63)/64) }
func (b bitset) set(i int)         { b[i>>6] |= 1 << (uint(i) & 63) }
func (b bitset) clear(i int)       { b[i>>6] &^= 1 << (uint(i) & 63) }
func (b bitset) has(i int) bool    { return b[i>>6]&(1<<(uint(i)&63)) != 0 }
func (b bitset) copyFrom(o bitset) { copy(b, o) }
func (b bitset) members() []int {
	var out []int
	for w, x := range b {
		for x != 0 {
			t := x & -x
			bit := 0
			for y := t; y > 1; y >>= 1 {
				bit++
			}
			out = append(out, w*64+bit)
			x ^= t
		}
	}
	return out
}

type liveness struct {
	in, out map[*MBlock]bitset
}

func computeLiveness(mf *MFunc) *liveness {
	n := mf.NVRegs
	use := map[*MBlock]bitset{}
	def := map[*MBlock]bitset{}
	lv := &liveness{in: map[*MBlock]bitset{}, out: map[*MBlock]bitset{}}
	for _, b := range mf.Blocks {
		u, d := newBitset(n), newBitset(n)
		for i := range b.Instrs {
			in := &b.Instrs[i]
			for _, o := range in.uses() {
				if o.K == OVReg && !d.has(int(o.V)) {
					u.set(int(o.V))
				}
			}
			if o := in.def(); o != nil && o.K == OVReg {
				d.set(int(o.V))
			}
		}
		use[b], def[b] = u, d
		lv.in[b], lv.out[b] = newBitset(n), newBitset(n)
	}
	for changed := true; changed; {
		changed = false
		for i := len(mf.Blocks) - 1; i >= 0; i-- {
			b := mf.Blocks[i]
			out := lv.out[b]
			for _, s := range b.Succs {
				for w := range out {
					out[w] |= lv.in[s][w]
				}
			}
			for w := range out {
				nw := use[b][w] | (out[w] &^ def[b][w])
				if nw != lv.in[b][w] {
					lv.in[b][w] = nw
					changed = true
				}
			}
		}
	}
	return lv
}

// ---- live intervals & linear scan ----

type Interval struct {
	V          int
	Start, End int // positions: 2*instr (read) / 2*instr+1 (write), layout order
	Crosses    bool
	Reg        int // -1 when spilled
	Slot       int
}

func buildIntervals(mf *MFunc, lv *liveness) []*Interval {
	n := mf.NVRegs
	start := make([]int, n)
	end := make([]int, n)
	seen := make([]bool, n)
	touch := func(v, p int) {
		if !seen[v] {
			seen[v], start[v], end[v] = true, p, p
			return
		}
		if p < start[v] {
			start[v] = p
		}
		if p > end[v] {
			end[v] = p
		}
	}
	// position encoding: instruction i reads at 2i and writes at 2i+1, so an
	// interval ending with a read at 2i may share a register with one defined at 2i+1.
	pos := 0
	var calls []int
	for _, b := range mf.Blocks {
		from := pos
		for _, v := range lv.in[b].members() {
			touch(v, 2*from)
		}
		for i := range b.Instrs {
			in := &b.Instrs[i]
			for _, o := range in.uses() {
				if o.K == OVReg {
					touch(int(o.V), 2*pos)
				}
			}
			if o := in.def(); o != nil && o.K == OVReg {
				touch(int(o.V), 2*pos+1)
			}
			if in.Op == MCall {
				calls = append(calls, 2*pos)
			}
			pos++
		}
		to := pos - 1
		for _, v := range lv.out[b].members() {
			touch(v, 2*to+1)
		}
	}
	var ivs []*Interval
	for v := 0; v < n; v++ {
		if !seen[v] {
			continue
		}
		iv := &Interval{V: v, Start: start[v], End: end[v], Reg: -1, Slot: -1}
		for _, c := range calls {
			if iv.Start < c && iv.End > c {
				iv.Crosses = true
				break
			}
		}
		ivs = append(ivs, iv)
	}
	return ivs
}

// Assignment maps virtual registers to physical registers or frame slots.
type Assignment struct {
	Reg  map[int]int
	Slot map[int]int
}

func linearScan(mf *MFunc, t Target) (*Assignment, AllocStats, []*Interval) {
	lv := computeLiveness(mf)
	ivs := buildIntervals(mf, lv)
	sort.SliceStable(ivs, func(i, j int) bool {
		if ivs[i].Start != ivs[j].Start {
			return ivs[i].Start < ivs[j].Start
		}
		return ivs[i].V < ivs[j].V
	})
	as := &Assignment{Reg: map[int]int{}, Slot: map[int]int{}}
	st := AllocStats{Alg: LinearScan}
	free := make([]bool, t.K)
	for i := range free {
		free[i] = true
	}
	var active []*Interval // sorted by End ascending
	allowed := func(iv *Interval, r int) bool { return !iv.Crosses || t.IsCallee(r) }
	spill := func(iv *Interval) {
		iv.Reg = -1
		iv.Slot = mf.NSlots
		mf.NSlots++
		as.Slot[iv.V] = iv.Slot
		delete(as.Reg, iv.V)
		st.Spilled++
	}
	for _, cur := range ivs {
		// expire intervals that ended at or before this start
		na := active[:0]
		for _, a := range active {
			if a.End < cur.Start {
				free[a.Reg] = true
			} else {
				na = append(na, a)
			}
		}
		active = na
		reg := -1
		for r := 0; r < t.K; r++ { // caller-saved first, so callee-saved stay free for call-crossers
			if free[r] && allowed(cur, r) {
				reg = r
				break
			}
		}
		if reg >= 0 {
			cur.Reg = reg
			free[reg] = false
			as.Reg[cur.V] = reg
			active = insertByEnd(active, cur)
			continue
		}
		// no free register: spill the interval (current or active) that ends last
		var victim *Interval
		for _, a := range active {
			if allowed(cur, a.Reg) && (victim == nil || a.End > victim.End) {
				victim = a
			}
		}
		if victim != nil && victim.End > cur.End {
			cur.Reg = victim.Reg
			as.Reg[cur.V] = cur.Reg
			spill(victim)
			na := active[:0]
			for _, a := range active {
				if a != victim {
					na = append(na, a)
				}
			}
			active = insertByEnd(na, cur)
		} else {
			spill(cur)
		}
	}
	st.Rounds = 1
	return as, st, ivs
}

func insertByEnd(l []*Interval, iv *Interval) []*Interval {
	i := sort.Search(len(l), func(i int) bool { return l[i].End > iv.End })
	l = append(l, nil)
	copy(l[i+1:], l[i:])
	l[i] = iv
	return l
}

// ---- applying an allocation ----

// applyAssignment rewrites vregs to physical registers, expands spilled values
// through the scratch registers, saves/restores used callee-saved registers and
// deletes copies that became no-ops.
func applyAssignment(mf *MFunc, t Target, as *Assignment, st *AllocStats) {
	for _, b := range mf.Blocks {
		var out []MInstr
		for _, in := range b.Instrs {
			scratch := 0
			loaded := map[int]int{}
			var after []MInstr
			us := in.uses()
			for _, o := range us {
				if o.K != OVReg {
					continue
				}
				v := int(o.V)
				if r, ok := as.Reg[v]; ok {
					*o = PReg(r)
					continue
				}
				slot, ok := as.Slot[v]
				if !ok {
					panic(fmt.Sprintf("regalloc: %s: vreg %%%d has no location", mf.Name, v))
				}
				if s, done := loaded[v]; done {
					*o = PReg(s)
					continue
				}
				sr := t.K + scratch
				scratch++
				out = append(out, MInstr{Op: MLd, D: PReg(sr), Slot: slot})
				loaded[v] = sr
				*o = PReg(sr)
			}
			if d := in.def(); d != nil && d.K == OVReg {
				v := int(d.V)
				if r, ok := as.Reg[v]; ok {
					*d = PReg(r)
				} else if slot, ok := as.Slot[v]; ok {
					*d = PReg(t.Scratch0())
					after = append(after, MInstr{Op: MSt, A: PReg(t.Scratch0()), Slot: slot})
				} else {
					panic(fmt.Sprintf("regalloc: %s: dead vreg %%%d has no location", mf.Name, v))
				}
			}
			if in.Op == MMov && in.A.K == OReg && in.D.K == OReg && in.A.V == in.D.V {
				st.MovesRemoved++
				out = append(out, after...) // a spilled destination still needs its store
				continue
			}
			out = append(out, in)
			out = append(out, after...)
		}
		b.Instrs = out
	}
	// callee-saved registers actually written
	used := map[int]bool{}
	for _, b := range mf.Blocks {
		for i := range b.Instrs {
			if d := b.Instrs[i].def(); d != nil && d.K == OReg && t.IsCallee(int(d.V)) {
				used[int(d.V)] = true
			}
		}
	}
	var regs []int
	for r := range used {
		regs = append(regs, r)
	}
	sort.Ints(regs)
	mf.UsedCallee = regs
	st.CalleeSaved = len(regs)
	if len(regs) > 0 {
		slots := map[int]int{}
		var prologue []MInstr
		for _, r := range regs {
			slots[r] = mf.NSlots
			mf.NSlots++
			prologue = append(prologue, MInstr{Op: MSt, A: PReg(r), Slot: slots[r]})
		}
		entry := mf.Blocks[0]
		entry.Instrs = append(prologue, entry.Instrs...)
		for _, b := range mf.Blocks {
			var out []MInstr
			for _, in := range b.Instrs {
				if in.Op == MRet {
					// capture the result first: it may live in a register about to be restored
					out = append(out, MInstr{Op: MSetRet, A: in.A})
					for _, r := range regs {
						out = append(out, MInstr{Op: MLd, D: PReg(r), Slot: slots[r]})
					}
					in.A = Opd{}
				}
				out = append(out, in)
			}
			b.Instrs = out
		}
	}
	mf.K = t.K
}

// Allocate runs the chosen allocator on mf (in place) and returns its statistics.
func Allocate(mf *MFunc, t Target, alg Alg) AllocStats {
	var as *Assignment
	var st AllocStats
	switch alg {
	case LinearScan:
		as, st, _ = linearScan(mf, t)
	default:
		as, st = graphColor(mf, t)
	}
	st.Alg = alg
	for v := range as.Slot {
		_ = v
	}
	applyAssignment(mf, t, as, &st)
	return st
}
