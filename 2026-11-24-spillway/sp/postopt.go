package sp

// Post-allocation clean-up on machine code. Spill-everywhere rewriting is
// simple and always correct but leaves obvious waste:
//
//	spill_st 3, r0      ; store …
//	r0 = spill_ld 3     ; … immediately reload what r0 already holds
//
// The three passes below (store-to-load forwarding, dead spill-store removal,
// stack-slot sharing) remove that waste. Each is checked end to end by the
// differential fuzzer.

// PostStats reports what the post-allocation passes changed.
type PostStats struct {
	LoadsDropped int // reloads deleted because the register already held the value
	LoadsToMoves int // reloads replaced by a cheaper register copy
	DeadStores   int // spill stores whose slot is never reloaded
	SlotsBefore  int
	SlotsAfter   int
}

// forwardLoads walks each block tracking which registers are known to hold the
// current value of which spill slot.
func forwardLoads(m *Function, ps *PostStats) {
	for _, b := range m.Blocks {
		holds := map[int][]int{} // slot -> registers equal to it
		kill := func(reg int) {
			for s, rs := range holds {
				out := rs[:0]
				for _, r := range rs {
					if r != reg {
						out = append(out, r)
					}
				}
				if len(out) == 0 {
					delete(holds, s)
				} else {
					holds[s] = out
				}
			}
		}
		var out []Instr
		for _, in := range b.Instrs {
			switch in.Op {
			case OpSpillSt:
				s := int(in.Args[0].Val)
				holds[s] = nil
				delete(holds, s)
				if !in.Args[1].Imm {
					holds[s] = []int{in.Args[1].Reg}
				}
				out = append(out, in)
				continue
			case OpSpillLd:
				s := int(in.Args[0].Val)
				if rs := holds[s]; len(rs) > 0 {
					have := false
					for _, r := range rs {
						if r == in.Dst {
							have = true
						}
					}
					if have {
						ps.LoadsDropped++
						continue
					}
					ps.LoadsToMoves++
					kill(in.Dst)
					holds[s] = append(holds[s], in.Dst)
					out = append(out, Instr{Op: OpMov, Dst: in.Dst, Args: []Operand{R(rs[0])}})
					continue
				}
				kill(in.Dst)
				holds[s] = []int{in.Dst}
				out = append(out, in)
				continue
			}
			if in.HasDst() {
				kill(in.Dst)
			}
			out = append(out, in)
		}
		b.Instrs = out
	}
}

// slotView builds a pseudo-function whose "registers" are the spill slots: a
// spill_st defines its slot, a spill_ld uses it, everything else disappears
// except terminators (kept so the CFG is unchanged).
func slotView(m *Function) *Function {
	v := &Function{Name: m.Name, NumRegs: m.Slots}
	for _, b := range m.Blocks {
		nb := &Block{Name: b.Name}
		for _, in := range b.Instrs {
			switch in.Op {
			case OpSpillSt:
				nb.Instrs = append(nb.Instrs, Instr{Op: OpConst, Dst: int(in.Args[0].Val), Args: []Operand{I(0)}})
			case OpSpillLd:
				nb.Instrs = append(nb.Instrs, Instr{Op: OpPrint, Dst: -1, Args: []Operand{R(int(in.Args[0].Val))}})
			case OpBr:
				nb.Instrs = append(nb.Instrs, Instr{Op: OpBr, Dst: -1, Args: []Operand{I(0)}, Targets: in.Targets})
			case OpJmp, OpRet:
				nb.Instrs = append(nb.Instrs, Instr{Op: in.Op, Dst: -1, Args: []Operand{I(0)}, Targets: in.Targets})
			default:
				// keep positions meaningful but inert
				nb.Instrs = append(nb.Instrs, Instr{Op: OpConst, Dst: -1, Args: []Operand{I(0)}})
			}
		}
		v.Blocks = append(v.Blocks, nb)
	}
	v.buildEdges()
	return v
}

// removeDeadStores deletes spill stores whose slot value is never reloaded.
func removeDeadStores(m *Function, ps *PostStats) {
	if m.Slots == 0 {
		return
	}
	v := slotView(m)
	lv := v.Liveness()
	dead := map[[2]int]bool{}
	v.LiveAfter(lv, func(bi, ii int, live Bitset) {
		in := &m.Blocks[bi].Instrs[ii]
		if in.Op == OpSpillSt && !live.Has(int(in.Args[0].Val)) {
			dead[[2]int{bi, ii}] = true
		}
	})
	if len(dead) == 0 {
		return
	}
	for bi, b := range m.Blocks {
		var out []Instr
		for ii, in := range b.Instrs {
			if dead[[2]int{bi, ii}] {
				ps.DeadStores++
				continue
			}
			out = append(out, in)
		}
		b.Instrs = out
	}
}

// compactSlots colours the slot-conflict graph so slots with disjoint
// lifetimes share a stack location, then renumbers and drops unused slots.
func compactSlots(m *Function) {
	if m.Slots == 0 {
		return
	}
	v := slotView(m)
	lv := v.Liveness()
	n := m.Slots
	conflict := make([]Bitset, n)
	for i := range conflict {
		conflict[i] = NewBitset(n)
	}
	used := make([]bool, n)
	v.LiveAfter(lv, func(bi, ii int, live Bitset) {
		in := &v.Blocks[bi].Instrs[ii]
		if in.HasDst() {
			used[in.Dst] = true
			live.each(func(l int) {
				if l != in.Dst {
					conflict[in.Dst].Set(l)
					conflict[l].Set(in.Dst)
				}
			})
		}
		for _, u := range in.Uses() {
			used[u] = true
		}
	})
	color := make([]int, n)
	next := 0
	for s := 0; s < n; s++ {
		color[s] = -1
		if !used[s] {
			continue
		}
		taken := map[int]bool{}
		conflict[s].each(func(o int) {
			if color[o] >= 0 {
				taken[color[o]] = true
			}
		})
		c := 0
		for taken[c] {
			c++
		}
		color[s] = c
		if c+1 > next {
			next = c + 1
		}
	}
	for _, b := range m.Blocks {
		for i := range b.Instrs {
			in := &b.Instrs[i]
			if in.Op == OpSpillSt || in.Op == OpSpillLd {
				in.Args[0] = I(int64(color[int(in.Args[0].Val)]))
			}
		}
	}
	m.Slots = next
}

// Optimize runs the post-allocation passes on a.Machine in place.
func (a *Allocation) Optimize() PostStats {
	ps := PostStats{SlotsBefore: a.Machine.Slots}
	forwardLoads(a.Machine, &ps)
	removeDeadStores(a.Machine, &ps)
	compactSlots(a.Machine)
	ps.SlotsAfter = a.Machine.Slots
	a.Slots = a.Machine.Slots
	a.Post = ps
	return ps
}
