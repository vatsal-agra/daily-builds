package front

import (
	"fmt"

	"dominion/ir"
)

type sym struct {
	slot *ir.Value
	arr  bool
	size int64
}

type loopCtx struct{ brk, cont *ir.Block }

type lowerer struct {
	fns    map[string]*fnDecl
	f      *ir.Func
	entry  *ir.Block
	cur    *ir.Block
	scopes []map[string]*sym
	loops  []loopCtx
	nblk   int
}

// Compile translates Dom source to an unoptimised (alloca/load/store form) IR module.
func Compile(src string) (*ir.Module, error) {
	decls, err := parseProgram(src)
	if err != nil {
		return nil, err
	}
	l := &lowerer{fns: map[string]*fnDecl{}}
	for _, d := range decls {
		if _, dup := l.fns[d.name]; dup {
			return nil, &Error{d.line, d.col, "function " + d.name + " defined twice"}
		}
		l.fns[d.name] = d
	}
	m := &ir.Module{}
	for _, d := range decls {
		f, err := l.lowerFn(d)
		if err != nil {
			return nil, err
		}
		m.Funcs = append(m.Funcs, f)
	}
	if err := m.Verify(); err != nil {
		return nil, fmt.Errorf("internal error: lowering produced invalid IR: %w", err)
	}
	return m, nil
}

func (l *lowerer) errAt(p pos, f string, a ...any) error {
	return &Error{p.line, p.col, fmt.Sprintf(f, a...)}
}

// MaxParams is the largest parameter count the VM calling convention supports.
const MaxParams = 32

func (l *lowerer) lowerFn(d *fnDecl) (*ir.Func, error) {
	if len(d.params) > MaxParams {
		return nil, l.errAt(d.pos, "function %q has %d parameters (limit is %d)", d.name, len(d.params), MaxParams)
	}
	l.f = ir.NewFunc(d.name, len(d.params))
	l.entry = l.f.NewBlock("entry")
	l.scopes = []map[string]*sym{{}}
	l.loops = nil
	l.nblk = 0
	l.cur = l.newBlock("start")
	for i, pn := range d.params {
		if _, dup := l.scopes[0][pn]; dup {
			return nil, l.errAt(d.pos, "duplicate parameter %q", pn)
		}
		slot := l.alloca(1)
		l.entry.Append(l.f.NewValue(ir.OpStore, slot, l.f.Const(0), l.f.Params[i]))
		l.scopes[0][pn] = &sym{slot: slot}
	}
	if err := l.stmts(d.body, true); err != nil {
		return nil, err
	}
	if l.cur.Term == ir.TermNone {
		l.cur.SetRet(l.f.Const(0))
	}
	start := l.f.Blocks[1]
	l.entry.SetBr(start)
	l.f.RemoveUnreachable()
	return l.f, nil
}

func (l *lowerer) newBlock(base string) *ir.Block {
	l.nblk++
	return l.f.NewBlock(fmt.Sprintf("%s%d", base, l.nblk))
}

func (l *lowerer) alloca(n int64) *ir.Value {
	a := l.f.NewValue(ir.OpAlloca)
	a.Const = n
	l.entry.Append(a)
	return a
}

// live returns the current block, opening a fresh (dead) block if the old one is terminated.
func (l *lowerer) live() *ir.Block {
	if l.cur.Term != ir.TermNone {
		l.cur = l.newBlock("dead")
	}
	return l.cur
}

func (l *lowerer) emit(op ir.Op, args ...*ir.Value) *ir.Value {
	return l.live().Append(l.f.NewValue(op, args...))
}

func (l *lowerer) lookup(name string) *sym {
	for i := len(l.scopes) - 1; i >= 0; i-- {
		if s, ok := l.scopes[i][name]; ok {
			return s
		}
	}
	return nil
}

func (l *lowerer) stmts(ss []stmt, sameScope bool) error {
	if !sameScope {
		l.scopes = append(l.scopes, map[string]*sym{})
		defer func() { l.scopes = l.scopes[:len(l.scopes)-1] }()
	}
	for _, s := range ss {
		if err := l.stmt(s); err != nil {
			return err
		}
	}
	return nil
}

func (l *lowerer) declare(p pos, name string, s *sym) error {
	sc := l.scopes[len(l.scopes)-1]
	if _, dup := sc[name]; dup {
		return l.errAt(p, "%q already declared in this scope", name)
	}
	sc[name] = s
	return nil
}

var binOps = map[string]ir.Op{
	"+": ir.OpAdd, "-": ir.OpSub, "*": ir.OpMul, "/": ir.OpDiv, "%": ir.OpRem,
	"&": ir.OpAnd, "|": ir.OpOr, "^": ir.OpXor, "<<": ir.OpShl, ">>": ir.OpShr,
	"==": ir.OpEq, "!=": ir.OpNe, "<": ir.OpLt, "<=": ir.OpLe, ">": ir.OpGt, ">=": ir.OpGe,
}

func (l *lowerer) stmt(s stmt) error {
	zero := l.f.Const(0)
	switch s := s.(type) {
	case *varDecl:
		v, err := l.expr(s.init)
		if err != nil {
			return err
		}
		slot := l.alloca(1)
		if err := l.declare(s.pos, s.name, &sym{slot: slot}); err != nil {
			return err
		}
		l.emit(ir.OpStore, slot, zero, v)
	case *arrDecl:
		slot := l.alloca(s.size)
		if err := l.declare(s.pos, s.name, &sym{slot: slot, arr: true, size: s.size}); err != nil {
			return err
		}
		l.zeroFill(slot, s.size)
	case *assign:
		sy := l.lookup(s.name)
		if sy == nil {
			return l.errAt(s.pos, "undefined variable %q", s.name)
		}
		if s.idx == nil {
			if sy.arr {
				return l.errAt(s.pos, "cannot assign to array %q without an index", s.name)
			}
			v, err := l.expr(s.val)
			if err != nil {
				return err
			}
			l.emit(ir.OpStore, sy.slot, zero, v)
			return nil
		}
		if !sy.arr {
			return l.errAt(s.pos, "%q is not an array", s.name)
		}
		i, err := l.expr(s.idx)
		if err != nil {
			return err
		}
		v, err := l.expr(s.val)
		if err != nil {
			return err
		}
		l.emit(ir.OpStore, sy.slot, i, v)
	case *printStmt:
		v, err := l.expr(s.val)
		if err != nil {
			return err
		}
		l.emit(ir.OpPrint, v)
	case *exprStmt:
		_, err := l.expr(s.x)
		return err
	case *retStmt:
		v := zero
		if s.val != nil {
			var err error
			if v, err = l.expr(s.val); err != nil {
				return err
			}
		}
		l.live().SetRet(v)
	case *blockStmt:
		return l.stmts(s.body, false)
	case *ifStmt:
		tb, eb, jb := l.newBlock("then"), l.newBlock("else"), l.newBlock("endif")
		if s.els == nil {
			eb = jb
		}
		if err := l.cond(s.cond, tb, eb); err != nil {
			return err
		}
		l.cur = tb
		if err := l.stmts(s.then, false); err != nil {
			return err
		}
		l.jump(jb)
		if s.els != nil {
			l.cur = eb
			if err := l.stmts(s.els, false); err != nil {
				return err
			}
			l.jump(jb)
		}
		l.cur = jb
	case *whileStmt:
		return l.loop(nil, s.cond, nil, s.body)
	case *forStmt:
		l.scopes = append(l.scopes, map[string]*sym{})
		defer func() { l.scopes = l.scopes[:len(l.scopes)-1] }()
		if s.init != nil {
			if err := l.stmt(s.init); err != nil {
				return err
			}
		}
		return l.loop(nil, s.cond, s.post, s.body)
	case *brkStmt:
		if len(l.loops) == 0 {
			return l.errAt(s.pos, "'break' outside of a loop")
		}
		l.jump(l.loops[len(l.loops)-1].brk)
	case *contStmt:
		if len(l.loops) == 0 {
			return l.errAt(s.pos, "'continue' outside of a loop")
		}
		l.jump(l.loops[len(l.loops)-1].cont)
	default:
		return fmt.Errorf("internal: unhandled statement %T", s)
	}
	return nil
}

// jump terminates the current block with a branch unless it is already terminated.
func (l *lowerer) jump(t *ir.Block) {
	if l.cur.Term == ir.TermNone {
		l.cur.SetBr(t)
	}
}

func (l *lowerer) loop(_ stmt, cond expr, post stmt, body []stmt) error {
	hdr, bb, exit := l.newBlock("loop"), l.newBlock("body"), l.newBlock("exit")
	cont := hdr
	var pb *ir.Block
	if post != nil {
		pb = l.newBlock("step")
		cont = pb
	}
	l.jump(hdr)
	l.cur = hdr
	if err := l.cond(cond, bb, exit); err != nil {
		return err
	}
	l.cur = bb
	l.loops = append(l.loops, loopCtx{exit, cont})
	err := l.stmts(body, false)
	l.loops = l.loops[:len(l.loops)-1]
	if err != nil {
		return err
	}
	l.jump(cont)
	if pb != nil {
		l.cur = pb
		if err := l.stmt(post); err != nil {
			return err
		}
		l.jump(hdr)
	}
	l.cur = exit
	return nil
}

func (l *lowerer) zeroFill(slot *ir.Value, n int64) {
	zero := l.f.Const(0)
	if n <= 4 {
		for i := int64(0); i < n; i++ {
			l.emit(ir.OpStore, slot, l.f.Const(i), zero)
		}
		return
	}
	ctr := l.alloca(1)
	l.emit(ir.OpStore, ctr, zero, zero)
	hdr, body, exit := l.newBlock("zfill"), l.newBlock("zbody"), l.newBlock("zdone")
	l.jump(hdr)
	l.cur = hdr
	i := l.emit(ir.OpLoad, ctr, zero)
	c := l.emit(ir.OpLt, i, l.f.Const(n))
	l.cur.SetCondBr(c, body, exit)
	l.cur = body
	i2 := l.emit(ir.OpLoad, ctr, zero)
	l.emit(ir.OpStore, slot, i2, zero)
	n2 := l.emit(ir.OpAdd, i2, l.f.Const(1))
	l.emit(ir.OpStore, ctr, zero, n2)
	l.jump(hdr)
	l.cur = exit
}

// cond lowers a boolean context with short-circuiting directly into control flow.
func (l *lowerer) cond(e expr, tb, fb *ir.Block) error {
	switch e := e.(type) {
	case *binEx:
		switch e.op {
		case "&&":
			mid := l.newBlock("and")
			if err := l.cond(e.l, mid, fb); err != nil {
				return err
			}
			l.cur = mid
			return l.cond(e.r, tb, fb)
		case "||":
			mid := l.newBlock("or")
			if err := l.cond(e.l, tb, mid); err != nil {
				return err
			}
			l.cur = mid
			return l.cond(e.r, tb, fb)
		}
	case *unaryEx:
		if e.op == "!" {
			return l.cond(e.x, fb, tb)
		}
	}
	v, err := l.expr(e)
	if err != nil {
		return err
	}
	b := l.live()
	if tb == fb {
		b.SetBr(tb)
	} else {
		b.SetCondBr(v, tb, fb)
	}
	return nil
}

func (l *lowerer) expr(e expr) (*ir.Value, error) {
	switch e := e.(type) {
	case *numLit:
		return l.f.Const(e.n), nil
	case *varRef:
		sy := l.lookup(e.name)
		if sy == nil {
			return nil, l.errAt(e.pos, "undefined variable %q", e.name)
		}
		if sy.arr {
			return nil, l.errAt(e.pos, "array %q used without an index", e.name)
		}
		return l.emit(ir.OpLoad, sy.slot, l.f.Const(0)), nil
	case *indexEx:
		sy := l.lookup(e.name)
		if sy == nil {
			return nil, l.errAt(e.pos, "undefined variable %q", e.name)
		}
		if !sy.arr {
			return nil, l.errAt(e.pos, "%q is not an array", e.name)
		}
		i, err := l.expr(e.idx)
		if err != nil {
			return nil, err
		}
		return l.emit(ir.OpLoad, sy.slot, i), nil
	case *callEx:
		d, ok := l.fns[e.name]
		if !ok {
			return nil, l.errAt(e.pos, "call to undefined function %q", e.name)
		}
		if len(d.params) != len(e.args) {
			return nil, l.errAt(e.pos, "%s expects %d argument(s), got %d", e.name, len(d.params), len(e.args))
		}
		var args []*ir.Value
		for _, a := range e.args {
			v, err := l.expr(a)
			if err != nil {
				return nil, err
			}
			args = append(args, v)
		}
		c := l.f.NewValue(ir.OpCall, args...)
		c.Callee = e.name
		return l.live().Append(c), nil
	case *unaryEx:
		x, err := l.expr(e.x)
		if err != nil {
			return nil, err
		}
		switch e.op {
		case "-":
			return l.emit(ir.OpNeg, x), nil
		case "~":
			return l.emit(ir.OpNot, x), nil
		default:
			return l.emit(ir.OpEq, x, l.f.Const(0)), nil
		}
	case *binEx:
		if e.op == "&&" || e.op == "||" {
			return l.shortCircuit(e)
		}
		a, err := l.expr(e.l)
		if err != nil {
			return nil, err
		}
		b, err := l.expr(e.r)
		if err != nil {
			return nil, err
		}
		return l.emit(binOps[e.op], a, b), nil
	}
	return nil, fmt.Errorf("internal: unhandled expression %T", e)
}

// shortCircuit materialises && / || as a 0/1 value through a scratch slot.
func (l *lowerer) shortCircuit(e *binEx) (*ir.Value, error) {
	zero := l.f.Const(0)
	slot := l.alloca(1)
	tb, fb, jb := l.newBlock("sc.t"), l.newBlock("sc.f"), l.newBlock("sc.end")
	if err := l.cond(e, tb, fb); err != nil {
		return nil, err
	}
	l.cur = tb
	l.emit(ir.OpStore, slot, zero, l.f.Const(1))
	l.jump(jb)
	l.cur = fb
	l.emit(ir.OpStore, slot, zero, zero)
	l.jump(jb)
	l.cur = jb
	return l.emit(ir.OpLoad, slot, zero), nil
}
