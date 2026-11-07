package sable

// SCCP is Wegman–Zadeck sparse conditional constant propagation: constants are
// propagated only along edges proven executable, so it folds branches and phis
// that simple constant folding cannot.
func SCCP(f *Func) bool {
	const (
		top = iota
		cnst
		bot
	)
	type lat struct {
		k int
		c int64
	}
	val := map[*Value]lat{}
	execBlock := map[*Block]bool{}
	type edge struct{ from, to *Block }
	execEdge := map[edge]bool{}
	users := map[*Value][]*Value{}
	ctrlUsers := map[*Value][]*Block{}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			for _, a := range v.Args {
				users[a] = append(users[a], v)
			}
		}
		if b.Ctrl != nil {
			ctrlUsers[b.Ctrl] = append(ctrlUsers[b.Ctrl], b)
		}
	}
	var ssaWork []*Value
	var blockWork []*Block
	lower := func(v *Value, n lat) {
		o := val[v]
		if o.k == bot || (o.k == cnst && n.k == cnst && o.c == n.c) || n.k == top {
			return
		}
		if o.k == cnst && n.k == cnst && o.c != n.c {
			n = lat{k: bot}
		}
		val[v] = n
		ssaWork = append(ssaWork, v)
	}
	markEdge := func(from, to *Block) {
		e := edge{from, to}
		if execEdge[e] {
			return
		}
		execEdge[e] = true
		if !execBlock[to] {
			execBlock[to] = true
			blockWork = append(blockWork, to)
		} else {
			// a new edge into an already-executable block: re-evaluate its phis
			for _, v := range to.Instrs {
				if v.Op != OpPhi {
					break
				}
				ssaWork = append(ssaWork, v)
			}
		}
	}
	evalTerm := func(b *Block) {
		switch b.Kind {
		case KJump:
			markEdge(b, b.Succs[0])
		case KBr:
			c := val[b.Ctrl]
			switch c.k {
			case cnst:
				if c.c != 0 {
					markEdge(b, b.Succs[0])
				} else {
					markEdge(b, b.Succs[1])
				}
			case bot:
				markEdge(b, b.Succs[0])
				markEdge(b, b.Succs[1])
			}
		}
	}
	eval := func(v *Value) {
		if !execBlock[v.Block] {
			return
		}
		switch {
		case v.Op == OpConst:
			lower(v, lat{cnst, v.Imm})
		case v.Op == OpPhi:
			res := lat{k: top}
			for i, a := range v.Args {
				if !execEdge[edge{v.Block.Preds[i], v.Block}] {
					continue
				}
				x := val[a]
				switch {
				case x.k == top:
				case x.k == bot:
					res = lat{k: bot}
				case res.k == top:
					res = x
				case res.k == cnst && res.c != x.c:
					res = lat{k: bot}
				}
				if res.k == bot {
					break
				}
			}
			lower(v, res)
		case v.Op.IsBinary():
			a, b := val[v.Args[0]], val[v.Args[1]]
			switch {
			case a.k == bot || b.k == bot:
				// x*0, x&0 etc. are left to instcombine
				lower(v, lat{k: bot})
			case a.k == cnst && b.k == cnst:
				if (v.Op == OpDiv || v.Op == OpMod) && b.c == 0 {
					lower(v, lat{k: bot}) // would trap: keep the instruction
				} else {
					lower(v, lat{cnst, EvalBin(opSym[v.Op], a.c, b.c)})
				}
			}
		case v.Op.IsUnary():
			a := val[v.Args[0]]
			switch a.k {
			case cnst:
				lower(v, lat{cnst, EvalUn(opSym[v.Op], a.c)})
			case bot:
				lower(v, lat{k: bot})
			}
		default: // param, call, print
			lower(v, lat{k: bot})
		}
	}
	execBlock[f.Entry] = true
	blockWork = append(blockWork, f.Entry)
	for len(blockWork) > 0 || len(ssaWork) > 0 {
		for len(blockWork) > 0 {
			b := blockWork[len(blockWork)-1]
			blockWork = blockWork[:len(blockWork)-1]
			for _, v := range b.Instrs {
				eval(v)
			}
			evalTerm(b)
		}
		for len(ssaWork) > 0 {
			v := ssaWork[len(ssaWork)-1]
			ssaWork = ssaWork[:len(ssaWork)-1]
			for _, u := range users[v] {
				eval(u)
			}
			for _, b := range ctrlUsers[v] {
				if execBlock[b] {
					evalTerm(b)
				}
			}
			if v.Op == OpPhi {
				eval(v)
			}
		}
	}
	// rewrite
	changed := false
	for _, b := range f.Blocks {
		if !execBlock[b] {
			continue
		}
		for i := 0; i < len(b.Instrs); i++ {
			v := b.Instrs[i]
			l := val[v]
			if l.k != cnst || v.Op == OpConst {
				continue
			}
			if v.Op == OpCall || v.Op == OpPrint || v.Op == OpParam {
				continue
			}
			if v.Op == OpPhi {
				c := f.newValue(OpConst)
				c.Imm = l.c
				b.Instrs = append(b.Instrs[:i], b.Instrs[i+1:]...)
				b.insertAt(b.NumPhis(), c)
				f.replaceUse(v, c)
				i = -1 // restart the block scan
				changed = true
				continue
			}
			v.Op, v.Args, v.Imm = OpConst, nil, l.c
			changed = true
		}
		if b.Kind == KBr {
			if c := val[b.Ctrl]; c.k == cnst {
				// let SimplifyCFG fold it: make the condition a literal constant
				if b.Ctrl.Op != OpConst {
					k := f.newValue(OpConst)
					k.Imm = c.c
					b.insertAt(len(b.Instrs), k)
					b.Ctrl = k
					changed = true
				}
			}
		}
	}
	// blocks never proven executable are removed by SimplifyCFG once edges are folded;
	// force-fold branches whose other side is dead.
	for _, b := range f.Blocks {
		if !execBlock[b] || b.Kind != KBr {
			continue
		}
		t0, t1 := execEdge[edge{b, b.Succs[0]}], execEdge[edge{b, b.Succs[1]}]
		if t0 != t1 {
			k := f.newValue(OpConst)
			if t0 {
				k.Imm = 1
			}
			b.insertAt(len(b.Instrs), k)
			b.Ctrl = k
			changed = true
		}
	}
	return changed
}
