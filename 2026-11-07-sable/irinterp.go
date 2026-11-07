package sable

// RunIR executes IR (pre-SSA or SSA) directly. Steps counts executed
// instructions + terminators, which is the "dynamic IR instruction" metric.
func RunIR(m *Module, fuel int64) (out Outcome) {
	in := &irInterp{m: m, fuel: fuel}
	defer func() {
		if r := recover(); r != nil {
			tp, ok := r.(trapPanic)
			if !ok {
				panic(r)
			}
			out = Outcome{Output: in.out, Trap: tp.kind, Steps: fuel - in.fuel}
		}
	}()
	ret := in.call(m.ByName["main"], nil)
	return Outcome{Output: in.out, Ret: ret, Steps: fuel - in.fuel}
}

type irInterp struct {
	m     *Module
	out   []int64
	fuel  int64
	depth int
}

func (in *irInterp) call(f *Func, args []int64) int64 {
	in.depth++
	if in.depth > MaxDepth {
		trap(TrapStack)
	}
	defer func() { in.depth-- }()
	vals := make([]int64, f.nextVal)
	slots := make([]int64, f.NSlots)
	b := f.Entry
	var prev *Block
	for {
		// phis evaluate simultaneously from the incoming edge
		np := b.NumPhis()
		if np > 0 {
			pi := b.predIndex(prev)
			tmp := make([]int64, np)
			for i := 0; i < np; i++ {
				tmp[i] = vals[b.Instrs[i].Args[pi].ID]
			}
			for i := 0; i < np; i++ {
				vals[b.Instrs[i].ID] = tmp[i]
			}
			in.tick(int64(np))
		}
		for _, v := range b.Instrs[np:] {
			in.tick(1)
			switch {
			case v.Op == OpConst:
				vals[v.ID] = v.Imm
			case v.Op == OpParam:
				vals[v.ID] = args[v.Imm]
			case v.Op == OpLoad:
				vals[v.ID] = slots[v.Imm]
			case v.Op == OpStore:
				slots[v.Imm] = vals[v.Args[0].ID]
			case v.Op.IsBinary():
				vals[v.ID] = EvalBin(opSym[v.Op], vals[v.Args[0].ID], vals[v.Args[1].ID])
			case v.Op.IsUnary():
				vals[v.ID] = EvalUn(opSym[v.Op], vals[v.Args[0].ID])
			case v.Op == OpPrint:
				in.out = append(in.out, vals[v.Args[0].ID])
			case v.Op == OpCall:
				a := make([]int64, len(v.Args))
				for i, x := range v.Args {
					a[i] = vals[x.ID]
				}
				callee := in.m.ByName[v.Callee]
				if callee == nil {
					panic("RunIR: unknown callee " + v.Callee)
				}
				vals[v.ID] = in.call(callee, a)
			default:
				panic("RunIR: bad op " + v.Op.String())
			}
		}
		in.tick(1)
		switch b.Kind {
		case KRet:
			return vals[b.Ctrl.ID]
		case KJump:
			prev, b = b, b.Succs[0]
		case KBr:
			prev = b
			if vals[b.Ctrl.ID] != 0 {
				b = b.Succs[0]
			} else {
				b = b.Succs[1]
			}
		}
	}
}

func (in *irInterp) tick(n int64) {
	in.fuel -= n
	if in.fuel < 0 {
		trap(TrapFuel)
	}
}
