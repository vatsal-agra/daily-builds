package opt

import "dominion/ir"

type latKind uint8

const (
	latTop latKind = iota // not yet known (optimistic)
	latConst
	latBot
)

type lat struct {
	k latKind
	c int64
}

// SCCP is Wegman & Zadeck's sparse conditional constant propagation: constants are propagated
// optimistically along only the CFG edges proven executable, so it also finds constants through
// loops and prunes branches whose condition becomes constant.
func SCCP(f *ir.Func) int {
	state := make([]lat, f.NumIDs())
	for _, p := range f.Params {
		state[p.ID] = lat{k: latBot}
	}
	get := func(v *ir.Value) lat {
		if v.IsConst() {
			return lat{latConst, v.Const}
		}
		return state[v.ID]
	}
	users := map[*ir.Value][]*ir.Value{}
	ctrlUsers := map[*ir.Value][]*ir.Block{}
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		for _, a := range v.Args {
			users[a] = append(users[a], v)
		}
	})
	for _, b := range f.Blocks {
		if b.Ctrl != nil && b.Term == ir.TermCondBr {
			ctrlUsers[b.Ctrl] = append(ctrlUsers[b.Ctrl], b)
		}
	}
	execBlock := map[*ir.Block]bool{}
	execEdge := map[[2]*ir.Block]bool{}
	var flow [][2]*ir.Block
	var ssa []*ir.Value
	var blkWork []*ir.Block

	set := func(v *ir.Value, l lat) {
		if state[v.ID] == l {
			return
		}
		state[v.ID] = l
		ssa = append(ssa, v)
	}
	meet := func(a, b lat) lat {
		switch {
		case a.k == latTop:
			return b
		case b.k == latTop:
			return a
		case a.k == latConst && b.k == latConst && a.c == b.c:
			return a
		}
		return lat{k: latBot}
	}
	visitPhi := func(ph *ir.Value) {
		res := lat{k: latTop}
		for i, a := range ph.Args {
			if execEdge[[2]*ir.Block{ph.Block.Preds[i], ph.Block}] {
				res = meet(res, get(a))
			}
		}
		set(ph, res)
	}
	visitInstr := func(v *ir.Value) {
		switch v.Op {
		case ir.OpAlloca, ir.OpLoad, ir.OpCall:
			set(v, lat{k: latBot})
			return
		case ir.OpStore, ir.OpPrint:
			return
		}
		var ls [3]lat
		anyTop, anyBot := false, false
		for i, a := range v.Args {
			ls[i] = get(a)
			anyTop = anyTop || ls[i].k == latTop
			anyBot = anyBot || ls[i].k == latBot
		}
		// absorbing elements
		if v.Op == ir.OpMul || v.Op == ir.OpAnd {
			for i := 0; i < 2; i++ {
				if ls[i].k == latConst && ls[i].c == 0 {
					set(v, lat{latConst, 0})
					return
				}
			}
		}
		if v.Op == ir.OpSelect && ls[0].k == latConst {
			arm := ls[1]
			if ls[0].c == 0 {
				arm = ls[2]
			}
			set(v, arm)
			return
		}
		if anyTop {
			return // stays optimistic
		}
		if anyBot {
			set(v, lat{k: latBot})
			return
		}
		r, ok := ir.Eval(v.Op, ls[0].c, ls[1].c, ls[2].c)
		if !ok {
			set(v, lat{k: latBot}) // keep the trap
			return
		}
		set(v, lat{latConst, r})
	}
	markEdge := func(from, to *ir.Block) {
		e := [2]*ir.Block{from, to}
		if execEdge[e] {
			return
		}
		execEdge[e] = true
		flow = append(flow, e)
	}
	visitTerm := func(b *ir.Block) {
		switch b.Term {
		case ir.TermBr:
			markEdge(b, b.Succs[0])
		case ir.TermCondBr:
			c := get(b.Ctrl)
			switch c.k {
			case latBot:
				markEdge(b, b.Succs[0])
				markEdge(b, b.Succs[1])
			case latConst:
				if c.c != 0 {
					markEdge(b, b.Succs[0])
				} else {
					markEdge(b, b.Succs[1])
				}
			}
		}
	}
	execBlock[f.Entry()] = true
	blkWork = append(blkWork, f.Entry())
	for len(blkWork) > 0 || len(flow) > 0 || len(ssa) > 0 {
		for len(blkWork) > 0 {
			b := blkWork[len(blkWork)-1]
			blkWork = blkWork[:len(blkWork)-1]
			for _, ph := range b.Phis {
				visitPhi(ph)
			}
			for _, v := range b.Instrs {
				visitInstr(v)
			}
			visitTerm(b)
		}
		for len(flow) > 0 {
			e := flow[len(flow)-1]
			flow = flow[:len(flow)-1]
			to := e[1]
			if !execBlock[to] {
				execBlock[to] = true
				blkWork = append(blkWork, to)
			} else {
				for _, ph := range to.Phis {
					visitPhi(ph)
				}
			}
		}
		for len(ssa) > 0 {
			v := ssa[len(ssa)-1]
			ssa = ssa[:len(ssa)-1]
			for _, u := range users[v] {
				if !execBlock[u.Block] {
					continue
				}
				if u.Op == ir.OpPhi {
					visitPhi(u)
				} else {
					visitInstr(u)
				}
			}
			for _, b := range ctrlUsers[v] {
				if execBlock[b] {
					visitTerm(b)
				}
			}
		}
	}
	// rewrite
	n := 0
	repl := ir.NewReplacer()
	f.ForEachInstr(func(b *ir.Block, v *ir.Value) {
		if !execBlock[b] || !v.HasResult() || v.Op == ir.OpAlloca {
			return
		}
		if l := state[v.ID]; l.k == latConst {
			repl.Add(v, f.Const(l.c))
			n++
		}
	})
	f.Apply(repl)
	for _, b := range f.Blocks {
		if !execBlock[b] {
			continue
		}
		if b.Term == ir.TermCondBr {
			if c := get(b.Ctrl); c.k == latConst {
				keep, drop := b.Succs[0], b.Succs[1]
				if c.c == 0 {
					keep, drop = drop, keep
				}
				drop.RemovePredEdge(b)
				b.Term, b.Ctrl, b.Succs = ir.TermBr, nil, []*ir.Block{keep}
				n++
			}
		}
	}
	if f.RemoveUnreachable() {
		n++
	}
	// edges from non-executable (now deleted) blocks were removed; phis in executable blocks that
	// referenced values of dead blocks lose those args via RemovePredEdge.
	return n
}
