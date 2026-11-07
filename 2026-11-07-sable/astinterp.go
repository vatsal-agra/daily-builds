package sable

// RunAST is the oracle: a direct tree-walking interpreter of the checked AST.
func RunAST(prog *Program, fuel int64) (out Outcome) {
	in := &astInterp{prog: prog, fuel: fuel}
	defer func() {
		if r := recover(); r != nil {
			tp, ok := r.(trapPanic)
			if !ok {
				panic(r)
			}
			out = Outcome{Output: in.out, Trap: tp.kind, Steps: fuel - in.fuel}
		}
	}()
	ret := in.call(prog.ByName["main"], nil)
	return Outcome{Output: in.out, Ret: ret, Steps: fuel - in.fuel}
}

type astInterp struct {
	prog  *Program
	out   []int64
	fuel  int64
	depth int
}

type ctrl int

const (
	cNone ctrl = iota
	cBreak
	cContinue
	cReturn
)

type frame struct {
	slots []int64
	ret   int64
}

func (in *astInterp) tick() {
	in.fuel--
	if in.fuel < 0 {
		trap(TrapFuel)
	}
}

func (in *astInterp) call(f *FuncDecl, args []int64) int64 {
	in.depth++
	if in.depth > MaxDepth {
		trap(TrapStack)
	}
	fr := &frame{slots: make([]int64, f.NSlots)}
	copy(fr.slots, args)
	in.block(fr, f.Body)
	in.depth--
	return fr.ret
}

func (in *astInterp) block(fr *frame, b *BlockStmt) ctrl {
	for _, s := range b.Stmts {
		if c := in.stmt(fr, s); c != cNone {
			return c
		}
	}
	return cNone
}

func (in *astInterp) stmt(fr *frame, s Stmt) ctrl {
	in.tick()
	switch s := s.(type) {
	case *VarDecl:
		fr.slots[s.Slot] = in.expr(fr, s.Init)
	case *Assign:
		fr.slots[s.Slot] = in.expr(fr, s.X)
	case *If:
		if in.expr(fr, s.Cond) != 0 {
			return in.block(fr, s.Then)
		} else if s.Else != nil {
			return in.stmt(fr, s.Else)
		}
	case *While:
		for in.expr(fr, s.Cond) != 0 {
			in.tick()
			c := in.block(fr, s.Body)
			if c == cBreak {
				break
			}
			if c == cReturn {
				return c
			}
		}
	case *For:
		if s.Init != nil {
			in.stmt(fr, s.Init)
		}
		for s.Cond == nil || in.expr(fr, s.Cond) != 0 {
			in.tick()
			c := in.block(fr, s.Body)
			if c == cBreak {
				break
			}
			if c == cReturn {
				return c
			}
			if s.Post != nil {
				in.stmt(fr, s.Post)
			}
		}
	case *Return:
		if s.X != nil {
			fr.ret = in.expr(fr, s.X)
		}
		return cReturn
	case *Break:
		return cBreak
	case *Continue:
		return cContinue
	case *Print:
		in.out = append(in.out, in.expr(fr, s.X))
	case *ExprStmt:
		in.expr(fr, s.X)
	case *BlockStmt:
		return in.block(fr, s)
	}
	return cNone
}

func (in *astInterp) expr(fr *frame, e Expr) int64 {
	in.tick()
	switch e := e.(type) {
	case *IntLit:
		return e.V
	case *VarRef:
		return fr.slots[e.Slot]
	case *Unary:
		return EvalUn(e.Op, in.expr(fr, e.X))
	case *Binary:
		switch e.Op {
		case "&&":
			if in.expr(fr, e.L) == 0 {
				return 0
			}
			return b2i(in.expr(fr, e.R) != 0)
		case "||":
			if in.expr(fr, e.L) != 0 {
				return 1
			}
			return b2i(in.expr(fr, e.R) != 0)
		}
		l := in.expr(fr, e.L)
		r := in.expr(fr, e.R)
		return EvalBin(e.Op, l, r)
	case *Call:
		args := make([]int64, len(e.Args))
		for i, a := range e.Args {
			args[i] = in.expr(fr, a)
		}
		return in.call(in.prog.ByName[e.Name], args)
	}
	panic("unreachable expr")
}
