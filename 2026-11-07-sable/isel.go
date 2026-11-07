package sable

// splitCriticalEdges inserts an empty block on every edge B->S where B has
// several successors and S has phis, so phi copies have a home.
func splitCriticalEdges(f *Func) {
	for _, b := range append([]*Block(nil), f.Blocks...) {
		if len(b.Succs) < 2 {
			continue
		}
		for i, s := range b.Succs {
			if s.NumPhis() == 0 || len(s.Preds) < 2 {
				continue
			}
			nb := f.NewBlock()
			nb.Kind = KJump
			nb.Succs = []*Block{s}
			nb.Preds = []*Block{b}
			b.Succs[i] = nb
			s.Preds[s.predIndex(b)] = nb
		}
	}
}

type pcopy struct {
	dst int
	src Opd
}

// selector lowers one SSA function to machine IR.
type selector struct {
	f    *Func
	mf   *MFunc
	vr   map[*Value]int
	blk  map[*Block]*MBlock
	cur  *MBlock
	uses map[*Value]int
}

func (s *selector) emit(in MInstr) { s.cur.Instrs = append(s.cur.Instrs, in) }

// reg returns v in a register, rematerialising constants right before use.
func (s *selector) reg(v *Value) Opd {
	if v.Op == OpConst {
		r := s.mf.newVReg()
		s.emit(MInstr{Op: MLi, D: VReg(r), A: Imm(v.Imm)})
		return VReg(r)
	}
	return VReg(s.vr[v])
}

// opd returns v as a register or an immediate.
func (s *selector) opd(v *Value) Opd {
	if v.Op == OpConst {
		return Imm(v.Imm)
	}
	return VReg(s.vr[v])
}

// Select converts SSA IR into machine IR with virtual registers. The input
// function is cloned, so the caller's SSA is untouched.
func Select(orig *Func) *MFunc {
	f := orig.Clone()
	splitCriticalEdges(f)
	f.removeUnreachable()
	an := Analyze(f)
	depth := map[*Block]int{}
	for _, lp := range an.Loops() {
		for b := range lp.Blocks {
			depth[b]++
		}
	}
	s := &selector{f: f, mf: &MFunc{Name: f.Name, NParams: f.NParams}, vr: map[*Value]int{},
		blk: map[*Block]*MBlock{}, uses: map[*Value]int{}}
	for _, b := range f.Blocks {
		for _, v := range b.Instrs {
			for _, a := range v.Args {
				s.uses[a]++
			}
		}
		if b.Ctrl != nil {
			s.uses[b.Ctrl]++
		}
	}
	for i, b := range an.RPO {
		mb := &MBlock{ID: i, Depth: depth[b]}
		s.blk[b] = mb
		s.mf.Blocks = append(s.mf.Blocks, mb)
	}
	for _, b := range an.RPO {
		for _, v := range b.Instrs {
			if v.Op != OpConst {
				s.vr[v] = s.mf.newVReg()
			}
		}
	}
	for _, b := range an.RPO {
		s.cur = s.blk[b]
		for _, t := range b.Succs {
			s.blk[b].Succs = append(s.blk[b].Succs, s.blk[t])
		}
		for _, v := range b.Instrs {
			s.instr(v)
		}
		switch b.Kind {
		case KJump:
			t := b.Succs[0]
			if np := t.NumPhis(); np > 0 {
				pi := t.predIndex(b)
				var cs []pcopy
				for k := 0; k < np; k++ {
					phi := t.Instrs[k]
					cs = append(cs, pcopy{s.vr[phi], s.opd(phi.Args[pi])})
				}
				s.parallelCopy(cs)
			}
			s.emit(MInstr{Op: MJmp, T: s.blk[t]})
		case KBr:
			c := s.reg(b.Ctrl)
			s.emit(MInstr{Op: MBr, A: c, T: s.blk[b.Succs[0]], F: s.blk[b.Succs[1]]})
		case KRet:
			s.emit(MInstr{Op: MRet, A: s.opd(b.Ctrl)})
		}
	}
	return s.mf
}

func (s *selector) instr(v *Value) {
	switch {
	case v.Op == OpConst, v.Op == OpPhi:
	case v.Op == OpParam:
		s.emit(MInstr{Op: MParam, D: VReg(s.vr[v]), Idx: int(v.Imm)})
	case v.Op.IsBinary():
		a, b := v.Args[0], v.Args[1]
		if a.Op == OpConst && b.Op != OpConst && v.Op.Commutative() {
			a, b = b, a
		}
		A := s.reg(a)
		B := s.opd(b)
		s.emit(MInstr{Op: MBin, Alu: v.Op, D: VReg(s.vr[v]), A: A, B: B})
	case v.Op.IsUnary():
		A := s.reg(v.Args[0])
		s.emit(MInstr{Op: MUn, Alu: v.Op, D: VReg(s.vr[v]), A: A})
	case v.Op == OpPrint:
		s.emit(MInstr{Op: MPrint, A: s.opd(v.Args[0])})
	case v.Op == OpCall:
		ops := make([]Opd, len(v.Args))
		for i, a := range v.Args {
			ops[i] = s.opd(a)
		}
		for i, o := range ops {
			s.emit(MInstr{Op: MArg, Idx: i, A: o})
		}
		s.emit(MInstr{Op: MCall, Callee: v.Callee})
		if s.uses[v] > 0 {
			s.emit(MInstr{Op: MGetRet, D: VReg(s.vr[v])})
		}
	default:
		panic("isel: unexpected op " + v.Op.String())
	}
}

// parallelCopy sequentialises simultaneous copies, breaking cycles with a temporary.
func (s *selector) parallelCopy(cs []pcopy) {
	emitCopy := func(c pcopy) {
		if c.src.K == OImm {
			s.emit(MInstr{Op: MLi, D: VReg(c.dst), A: c.src})
		} else {
			s.emit(MInstr{Op: MMov, D: VReg(c.dst), A: c.src})
		}
	}
	var pending []pcopy
	for _, c := range cs {
		if c.src.K == OVReg && int(c.src.V) == c.dst {
			continue
		}
		pending = append(pending, c)
	}
	for len(pending) > 0 {
		progress := false
		for i, c := range pending {
			blocked := false
			for j, d := range pending {
				if j != i && d.src.K == OVReg && int(d.src.V) == c.dst {
					blocked = true
					break
				}
			}
			if !blocked {
				emitCopy(c)
				pending = append(pending[:i], pending[i+1:]...)
				progress = true
				break
			}
		}
		if progress {
			continue
		}
		c := pending[0]
		tmp := s.mf.newVReg()
		s.emit(MInstr{Op: MMov, D: VReg(tmp), A: VReg(c.dst)})
		for j := range pending {
			if pending[j].src.K == OVReg && int(pending[j].src.V) == c.dst {
				pending[j].src = VReg(tmp)
			}
		}
	}
}
