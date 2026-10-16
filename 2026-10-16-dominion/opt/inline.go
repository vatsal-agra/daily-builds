package opt

import (
	"fmt"

	"dominion/ir"
)

// InlineConfig bounds the inliner.
type InlineConfig struct {
	MaxCalleeSize int // instructions (incl. phis and terminators)
	MaxCallerSize int // stop growing a function beyond this
	MaxAllocaZero int // callee allocas must total at most this many words (they are re-zeroed)
}

var DefaultInline = InlineConfig{MaxCalleeSize: 60, MaxCallerSize: 1500, MaxAllocaZero: 16}

func funcSize(f *ir.Func) int {
	n := 0
	for _, b := range f.Blocks {
		n += len(b.Phis) + len(b.Instrs) + 1
	}
	return n
}

// recursive reports functions that can (transitively) call themselves.
func recursiveSet(m *ir.Module) map[string]bool {
	calls := map[string][]string{}
	for _, f := range m.Funcs {
		f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
			if v.Op == ir.OpCall {
				calls[f.Name] = append(calls[f.Name], v.Callee)
			}
		})
	}
	rec := map[string]bool{}
	for _, f := range m.Funcs {
		seen := map[string]bool{}
		stack := append([]string(nil), calls[f.Name]...)
		for len(stack) > 0 {
			x := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			if x == f.Name {
				rec[f.Name] = true
				break
			}
			if seen[x] {
				continue
			}
			seen[x] = true
			stack = append(stack, calls[x]...)
		}
	}
	return rec
}

// Inline replaces calls to small non-recursive functions with a copy of their bodies.
func Inline(m *ir.Module, cfg InlineConfig) int {
	total := 0
	for round := 0; round < 4; round++ {
		rec := recursiveSet(m)
		n := 0
		for _, f := range m.Funcs {
			for {
				c := findInlinable(m, f, rec, cfg)
				if c == nil {
					break
				}
				inlineCall(f, c, m.Func(c.Callee))
				n++
			}
		}
		total += n
		if n == 0 {
			break
		}
	}
	return total
}

func findInlinable(m *ir.Module, f *ir.Func, rec map[string]bool, cfg InlineConfig) *ir.Value {
	if funcSize(f) > cfg.MaxCallerSize {
		return nil
	}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			if v.Op != ir.OpCall || v.Callee == f.Name || rec[v.Callee] {
				continue
			}
			cal := m.Func(v.Callee)
			if cal == nil || funcSize(cal) > cfg.MaxCalleeSize {
				continue
			}
			words := int64(0)
			for _, x := range cal.Entry().Instrs {
				if x.Op == ir.OpAlloca {
					words += x.Const
				}
			}
			if words > int64(cfg.MaxAllocaZero) {
				continue
			}
			return v
		}
	}
	return nil
}

func inlineCall(f *ir.Func, call *ir.Value, callee *ir.Func) {
	b := call.Block
	pos := 0
	for i, v := range b.Instrs {
		if v == call {
			pos = i
		}
	}
	// split b: b keeps [0,pos), cont gets (pos, end] + terminator
	cont := f.NewBlock(f.UniqueBlockName("inl.cont"))
	cont.Instrs = append(cont.Instrs, b.Instrs[pos+1:]...)
	for _, v := range cont.Instrs {
		v.Block = cont
	}
	b.Instrs = b.Instrs[:pos]
	cont.Term, cont.Ctrl, cont.Succs = b.Term, b.Ctrl, b.Succs
	for _, s := range cont.Succs {
		for i, p := range s.Preds {
			if p == b {
				s.Preds[i] = cont
			}
		}
	}
	b.Term, b.Ctrl, b.Succs = ir.TermNone, nil, nil

	// clone callee
	vmap := map[*ir.Value]*ir.Value{}
	for i, p := range callee.Params {
		vmap[p] = call.Args[i]
	}
	bmap := map[*ir.Block]*ir.Block{}
	var clones []*ir.Block
	for _, cb := range callee.Blocks {
		nb := f.NewBlock(f.UniqueBlockName(fmt.Sprintf("inl.%s.%s", callee.Name, cb.Name)))
		bmap[cb] = nb
		clones = append(clones, nb)
	}
	mapv := func(v *ir.Value) *ir.Value {
		if v.IsConst() {
			return f.Const(v.Const)
		}
		return vmap[v]
	}
	for _, cb := range callee.Blocks {
		nb := bmap[cb]
		for _, v := range append(append([]*ir.Value(nil), cb.Phis...), cb.Instrs...) {
			nv := f.NewValue(v.Op)
			nv.Const, nv.Callee = v.Const, v.Callee
			vmap[v] = nv
			nb.Append(nv)
		}
	}
	for _, cb := range callee.Blocks {
		nb := bmap[cb]
		for _, v := range append(append([]*ir.Value(nil), cb.Phis...), cb.Instrs...) {
			nv := vmap[v]
			for _, a := range v.Args {
				nv.Args = append(nv.Args, mapv(a))
			}
		}
		for _, p := range cb.Preds {
			nb.Preds = append(nb.Preds, bmap[p])
		}
		for _, s := range cb.Succs {
			nb.Succs = append(nb.Succs, bmap[s])
		}
		nb.Term = cb.Term
		if cb.Ctrl != nil {
			nb.Ctrl = mapv(cb.Ctrl)
		}
	}
	// hoist cloned allocas into the caller's entry (zeroed at the call site to keep fresh-frame semantics)
	centry := bmap[callee.Entry()]
	var zeroing []*ir.Value
	var keep []*ir.Value
	for _, v := range centry.Instrs {
		if v.Op == ir.OpAlloca {
			f.Entry().InsertAt(0, v)
			for k := int64(0); k < v.Const; k++ {
				zeroing = append(zeroing, f.NewValue(ir.OpStore, v, f.Const(k), f.Const(0)))
			}
		} else {
			keep = append(keep, v)
		}
	}
	centry.Instrs = keep
	for _, z := range zeroing {
		b.Append(z)
	}
	// returns -> branches to cont
	var rets []*ir.Block
	var retVals []*ir.Value
	for _, nb := range clones {
		if nb.Term == ir.TermRet {
			rets = append(rets, nb)
			retVals = append(retVals, nb.Ctrl)
			nb.Term, nb.Ctrl, nb.Succs = ir.TermBr, nil, []*ir.Block{cont}
			cont.Preds = append(cont.Preds, nb)
		}
	}
	b.SetBr(centry)
	// result value
	var result *ir.Value
	switch len(rets) {
	case 0:
		result = f.Const(0)
	case 1:
		result = retVals[0]
	default:
		ph := f.NewValue(ir.OpPhi, retVals...)
		cont.Append(ph) // Append routes phis to the phi list
		result = ph
	}
	f.ReplaceAllUses(call, result)
	// layout: place clones and cont right after b
	var rest []*ir.Block
	moved := map[*ir.Block]bool{cont: true}
	for _, c := range clones {
		moved[c] = true
	}
	for _, x := range f.Blocks {
		if !moved[x] {
			rest = append(rest, x)
		}
	}
	var out []*ir.Block
	for _, x := range rest {
		out = append(out, x)
		if x == b {
			out = append(out, clones...)
			out = append(out, cont)
		}
	}
	f.Blocks = out
	f.RemoveUnreachable()
}
