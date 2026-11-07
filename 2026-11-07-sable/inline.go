package sable

// Function inlining. A call site is replaced by a clone of the callee: the
// caller block is split at the call, the callee's parameters become the actual
// arguments, and every `ret` becomes a jump to the continuation block whose
// phi merges the returned values. Recursive functions are never inlined.

const (
	inlineSmall   = 40   // always inline callees up to this many instructions
	inlineSingle  = 300  // ...or single-call-site callees up to this size
	inlineMaxGrow = 4000 // stop growing a caller beyond this many instructions
)

func callees(f *Func) map[string]int {
	out := map[string]int{}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			if v.Op == OpCall {
				out[v.Callee]++
			}
		}
	}
	return out
}

// recursiveFuncs returns the functions that can (transitively) call themselves.
func recursiveFuncs(m *Module) map[string]bool {
	rec := map[string]bool{}
	graph := map[string]map[string]int{}
	for _, f := range m.Funcs {
		graph[f.Name] = callees(f)
	}
	for _, f := range m.Funcs {
		seen := map[string]bool{}
		stack := []string{}
		for c := range graph[f.Name] {
			stack = append(stack, c)
		}
		for len(stack) > 0 {
			n := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			if n == f.Name {
				rec[f.Name] = true
				break
			}
			if seen[n] {
				continue
			}
			seen[n] = true
			for c := range graph[n] {
				stack = append(stack, c)
			}
		}
	}
	return rec
}

// Inline inlines profitable non-recursive calls module-wide and drops functions
// that became unreachable from main. It returns the number of call sites inlined.
func Inline(m *Module) int {
	rec := recursiveFuncs(m)
	// callee-first order so bodies are already flattened when they are cloned
	var order []*Func
	state := map[string]int{}
	var visit func(f *Func)
	visit = func(f *Func) {
		if state[f.Name] != 0 {
			return
		}
		state[f.Name] = 1
		for c := range callees(f) {
			if g := m.ByName[c]; g != nil {
				visit(g)
			}
		}
		order = append(order, f)
	}
	for _, f := range m.Funcs {
		visit(f)
	}
	sites := map[string]int{}
	for _, f := range m.Funcs {
		for c, n := range callees(f) {
			sites[c] += n
		}
	}
	total := 0
	for _, f := range order {
		for guard := 0; guard < 500; guard++ {
			call := findInlinable(m, f, rec, sites)
			if call == nil {
				break
			}
			callee := m.ByName[call.Callee]
			sites[callee.Name]--
			for c, n := range callees(callee) {
				sites[c] += n
			}
			inlineCall(f, call, callee)
			total++
		}
	}
	// drop functions nobody calls any more
	live := map[string]bool{"main": true}
	work := []string{"main"}
	for len(work) > 0 {
		n := work[len(work)-1]
		work = work[:len(work)-1]
		for c := range callees(m.ByName[n]) {
			if !live[c] {
				live[c] = true
				work = append(work, c)
			}
		}
	}
	if len(live) < len(m.Funcs) {
		var keep []*Func
		for _, f := range m.Funcs {
			if live[f.Name] {
				keep = append(keep, f)
			} else {
				delete(m.ByName, f.Name)
			}
		}
		m.Funcs = keep
	}
	return total
}

func findInlinable(m *Module, f *Func, rec map[string]bool, sites map[string]int) *Value {
	if f.NumInstrs() > inlineMaxGrow {
		return nil
	}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			if v.Op != OpCall || v.Callee == f.Name || rec[v.Callee] {
				continue
			}
			g := m.ByName[v.Callee]
			if g == nil || g.Name == "main" {
				continue
			}
			n := g.NumInstrs() + len(g.Blocks)
			if n <= inlineSmall || (sites[g.Name] == 1 && n <= inlineSingle) {
				return v
			}
		}
	}
	return nil
}

// inlineCall splices a clone of callee into f in place of call.
func inlineCall(f *Func, call *Value, callee *Func) {
	b := call.Block
	idx := -1
	for i, v := range b.Instrs {
		if v == call {
			idx = i
		}
	}
	cl := callee.Clone()
	// fresh identities inside f
	for _, cb := range cl.Blocks {
		cb.ID = f.nextBlk
		f.nextBlk++
		cb.Fn = f
		for _, v := range cb.Instrs {
			v.ID = f.nextVal
			f.nextVal++
		}
	}
	// parameters -> actual arguments
	param := map[*Value]*Value{}
	for _, cb := range cl.Blocks {
		keep := cb.Instrs[:0]
		for _, v := range cb.Instrs {
			if v.Op == OpParam {
				param[v] = call.Args[v.Imm]
			} else {
				keep = append(keep, v)
			}
		}
		cb.Instrs = keep
	}
	cl.Blocks[0].Fn = f
	for _, cb := range cl.Blocks {
		for _, v := range cb.Instrs {
			for i, a := range v.Args {
				if r, ok := param[a]; ok {
					v.Args[i] = r
				}
			}
		}
		if cb.Ctrl != nil {
			if r, ok := param[cb.Ctrl]; ok {
				cb.Ctrl = r
			}
		}
	}
	// split the caller block at the call
	cont := f.NewBlock()
	cont.Instrs = append(cont.Instrs, b.Instrs[idx+1:]...)
	for _, v := range cont.Instrs {
		v.Block = cont
	}
	cont.Kind, cont.Ctrl, cont.Succs = b.Kind, b.Ctrl, b.Succs
	for _, s := range cont.Succs {
		for i, p := range s.Preds {
			if p == b {
				s.Preds[i] = cont
			}
		}
	}
	b.Instrs = b.Instrs[:idx]
	b.Ctrl, b.Succs = nil, nil
	entry := cl.Entry
	b.Kind = KJump
	link(b, entry)
	// returns become jumps to cont
	type ret struct {
		blk *Block
		val *Value
	}
	var rets []ret
	for _, cb := range cl.Blocks {
		if cb.Kind == KRet {
			rets = append(rets, ret{cb, cb.Ctrl})
			cb.Kind, cb.Ctrl = KJump, nil
			link(cb, cont)
		}
	}
	var result *Value
	switch len(rets) {
	case 0: // callee never returns: the continuation is unreachable
		result = f.newValue(OpConst)
		b.insertAt(len(b.Instrs), result)
	case 1:
		result = rets[0].val
	default:
		phi := f.newValue(OpPhi)
		for _, r := range rets {
			phi.Args = append(phi.Args, r.val)
		}
		cont.insertAt(0, phi)
		result = phi
	}
	f.Blocks = append(f.Blocks, cl.Blocks...)
	f.replaceUse(call, result)
	f.removeUnreachable()
}
