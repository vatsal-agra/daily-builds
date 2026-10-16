package opt

import (
	"fmt"

	"dominion/ir"
)

const (
	unrollMaxTrip  = 16  // iterations
	unrollMaxInstr = 160 // total instructions after unrolling
)

// Unroll fully unrolls small counted loops: loops whose only exit is the header's conditional
// branch and whose trip count can be computed at compile time from constant induction variables.
func Unroll(f *ir.Func) int {
	n := 0
	for {
		f.RemoveUnreachable()
		dom := ir.ComputeDom(f)
		did := false
		for _, l := range FindLoops(f, dom) {
			if unrollLoop(f, l) {
				n++
				did = true
				break
			}
		}
		if !did {
			return n
		}
	}
}

// tripCount returns the number of times the loop body runs, evaluating the header condition
// symbolically over the constant recurrences of the header phis.
func tripCount(l *Loop, pre, latch *ir.Block, inSucc int) (int, bool) {
	h := l.Header
	env := map[*ir.Value]int64{}
	pi, li := h.PredIndex(pre), h.PredIndex(latch)
	for _, ph := range h.Phis {
		a := ph.Args[pi]
		if !a.IsConst() {
			// non-constant initial values are fine as long as nothing the exit test needs depends on them;
			// mark as unknown by leaving them out of env
			continue
		}
		env[ph] = a.Const
	}
	var eval func(v *ir.Value, memo map[*ir.Value]int64, depth int) (int64, bool)
	eval = func(v *ir.Value, memo map[*ir.Value]int64, depth int) (int64, bool) {
		if v.IsConst() {
			return v.Const, true
		}
		if r, ok := memo[v]; ok {
			return r, true
		}
		if depth > 64 || v.Block == nil || !l.Blocks[v.Block] {
			return 0, false
		}
		if v.Op == ir.OpPhi {
			r, ok := env[v]
			return r, ok && v.Block == h
		}
		if !v.IsPure() {
			return 0, false
		}
		var a [3]int64
		for i, x := range v.Args {
			r, ok := eval(x, memo, depth+1)
			if !ok {
				return 0, false
			}
			a[i] = r
		}
		r, ok := ir.Eval(v.Op, a[0], a[1], a[2])
		if !ok {
			return 0, false
		}
		memo[v] = r
		return r, true
	}
	for k := 0; k <= unrollMaxTrip; k++ {
		memo := map[*ir.Value]int64{}
		c, ok := eval(h.Ctrl, memo, 0)
		if !ok {
			return 0, false
		}
		stay := c != 0
		if inSucc == 1 {
			stay = c == 0
		}
		if !stay {
			return k, true
		}
		next := map[*ir.Value]int64{}
		for _, ph := range h.Phis {
			if _, known := env[ph]; !known {
				continue
			}
			r, ok := eval(ph.Args[li], memo, 0)
			if ok {
				next[ph] = r
			}
		}
		env = next
	}
	return 0, false
}

func unrollLoop(f *ir.Func, l *Loop) bool {
	h := l.Header
	if h == f.Entry() || h.Term != ir.TermCondBr || len(l.Blocks) < 2 {
		return false
	}
	// shape: exactly one exit edge, from the header; exactly one latch
	inSucc := -1
	for i, s := range h.Succs {
		if l.Blocks[s] {
			if inSucc >= 0 {
				return false
			}
			inSucc = i
		}
	}
	if inSucc < 0 {
		return false
	}
	exit := h.Succs[1-inSucc]
	if l.Blocks[exit] {
		return false
	}
	var latch, outsidePred *ir.Block
	for _, p := range h.Preds {
		if l.Blocks[p] {
			if latch != nil {
				return false
			}
			latch = p
		} else {
			if outsidePred != nil {
				return false
			}
			outsidePred = p
		}
	}
	if latch == nil || latch == h || outsidePred == nil {
		return false
	}
	size := 0
	for b := range l.Blocks {
		if b != h {
			for _, s := range b.Succs {
				if !l.Blocks[s] {
					return false // another exit
				}
			}
		}
		if b.Term == ir.TermRet {
			return false
		}
		size += len(b.Phis) + len(b.Instrs) + 1
	}
	trip, ok := tripCount(l, outsidePred, latch, inSucc)
	if !ok || trip == 0 || trip > unrollMaxTrip || trip*size > unrollMaxInstr {
		return false
	}
	pre := outsidePred
	if pre.Term != ir.TermBr { // entry edge is a conditional branch: give the loop a dedicated preheader
		pre = ensurePreheader(f, l)
	}
	pi, li := h.PredIndex(pre), h.PredIndex(latch)

	// blocks in a stable order
	var order []*ir.Block
	for _, b := range f.Blocks {
		if l.Blocks[b] {
			order = append(order, b)
		}
	}
	type copyInfo struct {
		vmap map[*ir.Value]*ir.Value
		bmap map[*ir.Block]*ir.Block
	}
	headerPhiVal := func(prev *copyInfo, ph *ir.Value) *ir.Value {
		if prev == nil {
			return ph.Args[pi]
		}
		a := ph.Args[li]
		if m, ok := prev.vmap[a]; ok {
			return m
		}
		return a
	}
	var prev *copyInfo
	var copies []*copyInfo
	// clone one iteration; if final, only the header's non-phi part (the failing test) is cloned
	cloneIter := func(k int, final bool) *copyInfo {
		ci := &copyInfo{vmap: map[*ir.Value]*ir.Value{}, bmap: map[*ir.Block]*ir.Block{}}
		for _, ph := range h.Phis {
			ci.vmap[ph] = headerPhiVal(prev, ph)
		}
		blocks := order
		if final {
			blocks = []*ir.Block{h}
		}
		for _, b := range blocks {
			ci.bmap[b] = f.NewBlock(f.UniqueBlockName(fmt.Sprintf("%s.u%d", b.Name, k)))
		}
		mapArg := func(a *ir.Value) *ir.Value {
			if m, ok := ci.vmap[a]; ok {
				return m
			}
			return a
		}
		// create values first (operands may refer forward within a copy, via phis)
		for _, b := range blocks {
			nb := ci.bmap[b]
			if b != h {
				for _, v := range b.Phis {
					nv := f.NewValue(ir.OpPhi)
					ci.vmap[v] = nv
					nb.Append(nv)
				}
			}
			for _, v := range b.Instrs {
				nv := f.NewValue(v.Op)
				nv.Const, nv.Callee = v.Const, v.Callee
				ci.vmap[v] = nv
				nb.Append(nv)
			}
		}
		for _, b := range blocks {
			if b != h {
				for _, v := range b.Phis {
					nv := ci.vmap[v]
					for _, a := range v.Args {
						nv.Args = append(nv.Args, mapArg(a))
					}
				}
			}
			for _, v := range b.Instrs {
				nv := ci.vmap[v]
				for _, a := range v.Args {
					nv.Args = append(nv.Args, mapArg(a))
				}
			}
		}
		return ci
	}
	for k := 0; k < trip; k++ {
		ci := cloneIter(k, false)
		copies = append(copies, ci)
		prev = ci
	}
	fin := cloneIter(trip, true)

	// ---- wire the CFG of the unrolled chain: pre -> H0 -> body0 -> ... -> latch0 -> H1 -> ... -> Hfinal -> exit
	headerOf := func(k int) *ir.Block {
		if k < len(copies) {
			return copies[k].bmap[h]
		}
		return fin.bmap[h]
	}
	for k, ci := range copies {
		hb := ci.bmap[h]
		hb.Term = ir.TermBr
		hb.Succs = []*ir.Block{ci.bmap[h.Succs[inSucc]]}
		if k == 0 {
			hb.Preds = []*ir.Block{pre}
		} else {
			hb.Preds = []*ir.Block{copies[k-1].bmap[latch]}
		}
		for _, b := range order {
			if b == h {
				continue
			}
			nb := ci.bmap[b]
			nb.Term = b.Term
			if b.Ctrl != nil {
				nb.Ctrl = ci.vmap[b.Ctrl]
				if nb.Ctrl == nil {
					nb.Ctrl = b.Ctrl
				}
			}
			for _, s := range b.Succs {
				if s == h {
					nb.Succs = append(nb.Succs, headerOf(k+1)) // back edge becomes the next iteration's entry
				} else {
					nb.Succs = append(nb.Succs, ci.bmap[s])
				}
			}
			for _, p := range b.Preds { // same order as the original, so cloned phi operands still line up
				nb.Preds = append(nb.Preds, ci.bmap[p])
			}
		}
	}
	fb := fin.bmap[h]
	fb.Term, fb.Succs = ir.TermBr, []*ir.Block{exit}
	fb.Preds = []*ir.Block{copies[len(copies)-1].bmap[latch]}
	pre.Succs[0] = copies[0].bmap[h]
	// exit: the predecessor h is replaced by the final header copy
	xi := exit.PredIndex(h)
	exit.Preds[xi] = fb
	// uses of header-defined values outside the loop (including the exit block's phi operands) now
	// refer to the final iteration's copies
	var cloned []*ir.Block
	for _, ci := range copies {
		for _, b := range order {
			cloned = append(cloned, ci.bmap[b])
		}
	}
	cloned = append(cloned, fb)
	repl := ir.NewReplacer()
	for v, m := range fin.vmap {
		if v.Block == h {
			repl.Add(v, m)
		}
	}
	for _, b := range f.Blocks {
		if l.Blocks[b] || isIn(cloned, b) {
			continue
		}
		for _, v := range b.Phis {
			repl.ResolveArgs(v)
		}
		for _, v := range b.Instrs {
			repl.ResolveArgs(v)
		}
		if b.Ctrl != nil {
			b.Ctrl = repl.Resolve(b.Ctrl)
		}
	}
	// the original loop is now unreachable
	f.RemoveUnreachable()
	return true
}

func isIn(bs []*ir.Block, b *ir.Block) bool {
	for _, x := range bs {
		if x == b {
			return true
		}
	}
	return false
}
