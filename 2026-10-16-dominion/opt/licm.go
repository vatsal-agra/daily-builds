package opt

import (
	"sort"

	"dominion/ir"
)

// Loop is a natural loop.
type Loop struct {
	Header *ir.Block
	Blocks map[*ir.Block]bool
	Depth  int
}

// FindLoops returns natural loops (one per header, back edges merged), innermost first.
func FindLoops(f *ir.Func, dom *ir.DomInfo) []*Loop {
	byHeader := map[*ir.Block]*Loop{}
	var order []*ir.Block
	for _, b := range dom.RPO {
		for _, s := range b.Succs {
			if dom.Dominates(s, b) { // back edge b -> s
				l := byHeader[s]
				if l == nil {
					l = &Loop{Header: s, Blocks: map[*ir.Block]bool{s: true}}
					byHeader[s] = l
					order = append(order, s)
				}
				// reverse reachability from the latch
				stack := []*ir.Block{b}
				for len(stack) > 0 {
					x := stack[len(stack)-1]
					stack = stack[:len(stack)-1]
					if l.Blocks[x] {
						continue
					}
					l.Blocks[x] = true
					for _, p := range x.Preds {
						if dom.Reachable(p) {
							stack = append(stack, p)
						}
					}
				}
			}
		}
	}
	var loops []*Loop
	for _, h := range order {
		loops = append(loops, byHeader[h])
	}
	for _, l := range loops {
		for _, o := range loops {
			if o.Blocks[l.Header] {
				l.Depth++
			}
		}
	}
	sort.SliceStable(loops, func(i, j int) bool { return len(loops[i].Blocks) < len(loops[j].Blocks) })
	return loops
}

// ensurePreheader returns a block that is the unique non-loop predecessor of the header
// and ends in an unconditional branch to it, creating one if needed.
func ensurePreheader(f *ir.Func, l *Loop) *ir.Block {
	h := l.Header
	var outside []*ir.Block
	for _, p := range h.Preds {
		if !l.Blocks[p] {
			outside = append(outside, p)
		}
	}
	if len(outside) == 1 && outside[0].Term == ir.TermBr {
		return outside[0]
	}
	ph := f.NewBlock(f.UniqueBlockName(h.Name + ".pre"))
	// keep entry first: NewBlock appends at the end, which is fine for layout-independent IR
	// split header phis: values arriving from outside flow through new phis in the preheader
	for _, phi := range h.Phis {
		var outIdx []int
		for i, p := range h.Preds {
			if !l.Blocks[p] {
				outIdx = append(outIdx, i)
			}
		}
		var incoming *ir.Value
		if len(outIdx) == 1 {
			incoming = phi.Args[outIdx[0]]
		} else {
			np := f.NewValue(ir.OpPhi)
			for _, i := range outIdx {
				np.Args = append(np.Args, phi.Args[i])
			}
			// np.Args order must follow ph.Preds, which we build below in the same order
			ph.Append(np)
			incoming = np
		}
		// rebuild header phi: inside args keep position, outside collapse to one entry (appended last)
		var nargs []*ir.Value
		for i, p := range h.Preds {
			if l.Blocks[p] {
				nargs = append(nargs, phi.Args[i])
			}
		}
		phi.Args = append(nargs, incoming)
	}
	var inside []*ir.Block
	for _, p := range h.Preds {
		if l.Blocks[p] {
			inside = append(inside, p)
		}
	}
	oldPreds := append([]*ir.Block(nil), h.Preds...)
	h.Preds = append(inside, ph)
	for _, p := range oldPreds {
		if l.Blocks[p] {
			continue
		}
		for i, s := range p.Succs {
			if s == h {
				p.Succs[i] = ph
			}
		}
		ph.Preds = append(ph.Preds, p)
	}
	ph.Term = ir.TermBr
	ph.Succs = []*ir.Block{h}
	// put the preheader right before the header in layout (cosmetic)
	f.Blocks = f.Blocks[:len(f.Blocks)-1]
	for i, b := range f.Blocks {
		if b == h {
			f.Blocks = append(f.Blocks[:i], append([]*ir.Block{ph}, f.Blocks[i:]...)...)
			break
		}
	}
	return ph
}

// LICM hoists loop-invariant, side-effect-free computations into a preheader.
func LICM(f *ir.Func) int {
	f.RemoveUnreachable()
	n := 0
	loops := FindLoops(f, ir.ComputeDom(f))
	headers := make([]*ir.Block, len(loops))
	for i, l := range loops {
		headers[i] = l.Header
	}
	for _, h := range headers {
		// preheader insertion changes the CFG: recompute loops, find this header's loop again
		dom := ir.ComputeDom(f)
		var l *Loop
		for _, c := range FindLoops(f, dom) {
			if c.Header == h {
				l = c
			}
		}
		if l == nil {
			continue
		}
		stored := map[*ir.Value]bool{}
		for b := range l.Blocks {
			for _, v := range b.Instrs {
				if v.Op == ir.OpStore {
					stored[v.Args[0]] = true
				}
			}
		}
		defInLoop := map[*ir.Value]bool{}
		for b := range l.Blocks {
			for _, v := range b.Phis {
				defInLoop[v] = true
			}
			for _, v := range b.Instrs {
				defInLoop[v] = true
			}
		}
		var pre *ir.Block
		hoist := func(v *ir.Value) bool {
			for _, a := range v.Args {
				if defInLoop[a] {
					return false
				}
			}
			switch {
			case v.IsPure():
			case v.Op == ir.OpLoad:
				idx := v.Args[1]
				if stored[v.Args[0]] || !idx.IsConst() || idx.Const < 0 || idx.Const >= v.Args[0].Const {
					return false
				}
			default:
				return false
			}
			return true
		}
		for _, b := range dom.RPO {
			if !l.Blocks[b] {
				continue
			}
			for i := 0; i < len(b.Instrs); i++ {
				v := b.Instrs[i]
				if !hoist(v) {
					continue
				}
				if pre == nil {
					pre = ensurePreheader(f, l)
				}
				b.Instrs = append(b.Instrs[:i], b.Instrs[i+1:]...)
				i--
				v.Block = pre
				pre.Instrs = append(pre.Instrs, v)
				delete(defInLoop, v)
				n++
			}
		}
	}
	return n
}
