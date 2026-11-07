package sable

// Lower translates a checked AST into pre-SSA IR: every source variable lives
// in a numbered slot accessed with load/store; Mem2Reg later promotes slots.
func Lower(prog *Program) *Module {
	m := &Module{ByName: map[string]*Func{}}
	for _, fd := range prog.Funcs {
		f := lowerFunc(fd)
		m.Funcs = append(m.Funcs, f)
		m.ByName[f.Name] = f
	}
	return m
}

type lowerer struct {
	f      *Func
	cur    *Block
	breaks []*Block
	conts  []*Block
}

func lowerFunc(fd *FuncDecl) *Func {
	f := NewFunc(fd.Name, len(fd.Params))
	f.NSlots = fd.NSlots
	l := &lowerer{f: f, cur: f.Entry}
	for i := range fd.Params {
		p := l.cur.Emit(OpParam)
		p.Imm = int64(i)
		st := l.cur.Emit(OpStore, p)
		st.Imm = int64(i)
	}
	l.block(fd.Body)
	if l.cur != nil {
		l.cur.SetRet(l.cur.EmitConst(0))
	}
	f.removeUnreachable()
	f.renumber()
	return f
}

func (l *lowerer) newSlot() int {
	s := l.f.NSlots
	l.f.NSlots++
	return s
}

// fresh starts a new block for code that follows a terminator (it will be unreachable).
func (l *lowerer) dead() { l.cur = l.f.NewBlock() }

func (l *lowerer) block(b *BlockStmt) {
	for _, s := range b.Stmts {
		l.stmt(s)
	}
}

func (l *lowerer) store(slot int, v *Value) {
	st := l.cur.Emit(OpStore, v)
	st.Imm = int64(slot)
}

func (l *lowerer) stmt(s Stmt) {
	switch s := s.(type) {
	case *VarDecl:
		l.store(s.Slot, l.expr(s.Init))
	case *Assign:
		l.store(s.Slot, l.expr(s.X))
	case *If:
		thenB, joinB := l.f.NewBlock(), l.f.NewBlock()
		elseB := joinB
		if s.Else != nil {
			elseB = l.f.NewBlock()
		}
		l.cond(s.Cond, thenB, elseB)
		l.cur = thenB
		l.block(s.Then)
		l.jump(joinB)
		if s.Else != nil {
			l.cur = elseB
			l.stmt(s.Else)
			l.jump(joinB)
		}
		l.cur = joinB
	case *While:
		l.loop(nil, s.Cond, nil, s.Body)
	case *For:
		if s.Init != nil {
			l.stmt(s.Init)
		}
		l.loop(nil, s.Cond, s.Post, s.Body)
	case *Return:
		var v *Value
		if s.X != nil {
			v = l.expr(s.X)
		} else {
			v = l.cur.EmitConst(0)
		}
		l.cur.SetRet(v)
		l.dead()
	case *Break:
		l.cur.SetJump(l.breaks[len(l.breaks)-1])
		l.dead()
	case *Continue:
		l.cur.SetJump(l.conts[len(l.conts)-1])
		l.dead()
	case *Print:
		l.cur.Emit(OpPrint, l.expr(s.X))
	case *ExprStmt:
		l.expr(s.X)
	case *BlockStmt:
		l.block(s)
	}
}

// jump terminates the current block with a jump unless it already ended.
func (l *lowerer) jump(to *Block) {
	if l.cur != nil && l.cur.Succs == nil && l.cur.Ctrl == nil && !l.terminated(l.cur) {
		l.cur.SetJump(to)
	}
}

// terminated is true when the block already received a terminator. Blocks start as
// KJump with no successors; a block that returned has Kind KRet.
func (l *lowerer) terminated(b *Block) bool { return b.Kind == KRet || len(b.Succs) > 0 }

func (l *lowerer) loop(_ Stmt, cond Expr, post Stmt, body *BlockStmt) {
	head, bodyB, postB, exit := l.f.NewBlock(), l.f.NewBlock(), l.f.NewBlock(), l.f.NewBlock()
	l.jump(head)
	l.cur = head
	if cond == nil {
		head.SetJump(bodyB)
	} else {
		l.cond(cond, bodyB, exit)
	}
	l.breaks = append(l.breaks, exit)
	l.conts = append(l.conts, postB)
	l.cur = bodyB
	l.block(body)
	l.jump(postB)
	l.breaks = l.breaks[:len(l.breaks)-1]
	l.conts = l.conts[:len(l.conts)-1]
	l.cur = postB
	if post != nil {
		l.stmt(post)
	}
	l.jump(head)
	l.cur = exit
}

// cond lowers a branch on e, short-circuiting && / || into control flow.
func (l *lowerer) cond(e Expr, t, f *Block) {
	if b, ok := e.(*Binary); ok {
		switch b.Op {
		case "&&":
			mid := l.f.NewBlock()
			l.cond(b.L, mid, f)
			l.cur = mid
			l.cond(b.R, t, f)
			return
		case "||":
			mid := l.f.NewBlock()
			l.cond(b.L, t, mid)
			l.cur = mid
			l.cond(b.R, t, f)
			return
		}
	}
	if u, ok := e.(*Unary); ok && u.Op == "!" {
		l.cond(u.X, f, t)
		return
	}
	v := l.expr(e)
	l.cur.SetBr(v, t, f)
}

func (l *lowerer) expr(e Expr) *Value {
	switch e := e.(type) {
	case *IntLit:
		return l.cur.EmitConst(e.V)
	case *VarRef:
		v := l.cur.Emit(OpLoad)
		v.Imm = int64(e.Slot)
		return v
	case *Unary:
		x := l.expr(e.X)
		switch e.Op {
		case "-":
			return l.cur.Emit(OpNeg, x)
		case "!":
			return l.cur.Emit(OpNot, x)
		}
		return l.cur.Emit(OpBNot, x)
	case *Binary:
		if e.Op == "&&" || e.Op == "||" {
			tmp := l.newSlot()
			tB, fB, join := l.f.NewBlock(), l.f.NewBlock(), l.f.NewBlock()
			l.cond(e, tB, fB)
			l.cur = tB
			l.store(tmp, l.cur.EmitConst(1))
			l.cur.SetJump(join)
			l.cur = fB
			l.store(tmp, l.cur.EmitConst(0))
			l.cur.SetJump(join)
			l.cur = join
			v := l.cur.Emit(OpLoad)
			v.Imm = int64(tmp)
			return v
		}
		a := l.expr(e.L)
		b := l.expr(e.R)
		return l.cur.Emit(binOpOf[e.Op], a, b)
	case *Call:
		args := make([]*Value, len(e.Args))
		for i, a := range e.Args {
			args[i] = l.expr(a)
		}
		c := l.cur.Emit(OpCall, args...)
		c.Callee = e.Name
		return c
	}
	panic("lower: bad expr")
}
