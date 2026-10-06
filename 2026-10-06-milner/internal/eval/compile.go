package eval

import (
	"fmt"

	"milner/internal/syntax"
	"milner/internal/types"
)

// Cell is a top-level variable slot. A new cell is created for every top-level binding so later
// redefinitions do not affect closures compiled earlier (static scoping).
type Cell struct {
	Name string
	V    Value
}

type node interface{}

type (
	nConst  struct{ V Value }
	nLocal  struct{ Idx int }
	nGlobal struct{ C *Cell }
	nFun    struct{ F *cFun }
	nApp    struct {
		Fn   node
		Args []node
		Sp   syntax.Span
	}
	nLet struct {
		Rec   bool
		Binds []nBind
		Body  node
	}
	nIf    struct{ C, T, E node }
	nMatch struct {
		Scrut node
		Arms  []nArm
		Sp    syntax.Span
	}
	nTuple struct{ Elems []node }
	nSeq   struct{ A, B node }
	nAnd   struct{ L, R node }
	nOr    struct{ L, R node }
	nCon   struct {
		Name string
		Idx  int
		Arg  node
	}
)

type cFun struct {
	Params []cPat
	Simple bool // all params are plain variables
	Body   node
	Sp     syntax.Span
}

type nBind struct {
	Pat cPat // nil for rec bindings (single variable)
	E   node
}

type nArm struct {
	Pat   cPat
	Guard node
	Body  node
}

// ---------- compiled patterns ----------

// cPat matches a value, writing variable bindings into slots (indexed by pattern-local slot number).
type cPat struct {
	Kind  pk
	Slot  int
	Int   int64
	Str   string
	Bool  bool
	Idx   int
	Subs  []cPat // tuple elems, or the single constructor argument
	Slots []string
}

type pk int

const (
	pkWild pk = iota
	pkVar
	pkInt
	pkStr
	pkBool
	pkUnit
	pkTuple
	pkCon
	pkOr
	pkAs
)

// NSlots returns how many variables the pattern binds.
func (p *cPat) nslots() int { return len(p.Slots) }

// ---------- compiler ----------

// Compiler turns type-checked AST into nodes. Globals maps top-level names to cells.
type Compiler struct {
	Globals map[string]*Cell
	Cons    map[string]*types.ConInfo
	scope   []string
}

func (c *Compiler) push(name string) { c.scope = append(c.scope, name) }
func (c *Compiler) pop(n int)        { c.scope = c.scope[:len(c.scope)-n] }

func (c *Compiler) lookup(name string, sp syntax.Span) node {
	for i := len(c.scope) - 1; i >= 0; i-- {
		if c.scope[i] == name {
			return &nLocal{Idx: len(c.scope) - 1 - i}
		}
	}
	if cell, ok := c.Globals[name]; ok {
		return &nGlobal{C: cell}
	}
	panic(&RuntimeError{Msg: "internal error: unresolved variable " + name, Span: sp})
}

// compilePat compiles p, assigning slots by first appearance; returns the pattern and its slot names.
func (c *Compiler) compilePat(p syntax.Pat) cPat {
	var names []string
	cp := c.pat(p, &names)
	cp.Slots = names
	return cp
}

func slotOf(names *[]string, n string) int {
	for i, x := range *names {
		if x == n {
			return i
		}
	}
	*names = append(*names, n)
	return len(*names) - 1
}

func (c *Compiler) pat(p syntax.Pat, names *[]string) cPat {
	switch x := p.(type) {
	case *syntax.PWild:
		return cPat{Kind: pkWild}
	case *syntax.PVar:
		return cPat{Kind: pkVar, Slot: slotOf(names, x.Name)}
	case *syntax.PInt:
		return cPat{Kind: pkInt, Int: x.Val}
	case *syntax.PStr:
		return cPat{Kind: pkStr, Str: x.Val}
	case *syntax.PBool:
		return cPat{Kind: pkBool, Bool: x.Val}
	case *syntax.PUnit:
		return cPat{Kind: pkUnit}
	case *syntax.PTuple:
		subs := make([]cPat, len(x.Elems))
		for i, e := range x.Elems {
			subs[i] = c.pat(e, names)
		}
		return cPat{Kind: pkTuple, Subs: subs}
	case *syntax.PCon:
		ci := c.Cons[x.Name]
		cp := cPat{Kind: pkCon, Idx: ci.Index}
		if x.Arg != nil {
			cp.Subs = []cPat{c.pat(x.Arg, names)}
		}
		return cp
	case *syntax.POr:
		l := c.pat(x.L, names)
		r := c.pat(x.R, names)
		return cPat{Kind: pkOr, Subs: []cPat{l, r}}
	case *syntax.PAs:
		inner := c.pat(x.P, names)
		return cPat{Kind: pkAs, Slot: slotOf(names, x.Name), Subs: []cPat{inner}}
	case *syntax.PAnnot:
		return c.pat(x.P, names)
	}
	panic(fmt.Sprintf("compile: unhandled pattern %T", p))
}

// bindPat pushes a pattern's variables on the compile-time scope.
func (c *Compiler) bindPat(p *cPat) {
	for _, n := range p.Slots {
		c.push(n)
	}
}

// Compile compiles an expression in the current global scope.
func (c *Compiler) Compile(e syntax.Expr) node {
	c.scope = c.scope[:0]
	return c.expr(e)
}

func (c *Compiler) expr(e syntax.Expr) node {
	switch x := e.(type) {
	case *syntax.EInt:
		return &nConst{V: x.Val}
	case *syntax.EStr:
		return &nConst{V: x.Val}
	case *syntax.EBool:
		return &nConst{V: x.Val}
	case *syntax.EUnit:
		return &nConst{V: Unit{}}
	case *syntax.EHole:
		panic(&RuntimeError{Msg: "internal error: hole reached the evaluator", Span: x.Sp})
	case *syntax.EVar:
		return c.lookup(x.Name, x.Sp)
	case *syntax.ECon:
		ci := c.Cons[x.Name]
		if ci.Arity == 0 {
			return &nConst{V: &Con{Name: ci.Name, Idx: ci.Index}}
		}
		if x.Arg == nil {
			return &nConst{V: &ConFn{Name: ci.Name, Idx: ci.Index}}
		}
		return &nCon{Name: ci.Name, Idx: ci.Index, Arg: c.expr(x.Arg)}
	case *syntax.EFun:
		return &nFun{F: c.fun(x)}
	case *syntax.EApp:
		// flatten curried applications
		var args []node
		var fn syntax.Expr = x
		var rev []syntax.Expr
		for {
			a, ok := fn.(*syntax.EApp)
			if !ok {
				break
			}
			rev = append(rev, a.Arg)
			fn = a.Fn
		}
		fnode := c.expr(fn)
		for i := len(rev) - 1; i >= 0; i-- {
			args = append(args, c.expr(rev[i]))
		}
		return &nApp{Fn: fnode, Args: args, Sp: x.Sp}
	case *syntax.ELet:
		return c.let(x)
	case *syntax.EIf:
		return &nIf{C: c.expr(x.Cond), T: c.expr(x.Then), E: c.expr(x.Else)}
	case *syntax.EMatch:
		m := &nMatch{Scrut: c.expr(x.Scrut), Sp: x.Sp}
		for _, arm := range x.Arms {
			cp := c.compilePat(arm.Pat)
			c.bindPat(&cp)
			var g node
			if arm.Guard != nil {
				g = c.expr(arm.Guard)
			}
			b := c.expr(arm.Body)
			c.pop(len(cp.Slots))
			m.Arms = append(m.Arms, nArm{Pat: cp, Guard: g, Body: b})
		}
		return m
	case *syntax.ETuple:
		t := &nTuple{}
		for _, el := range x.Elems {
			t.Elems = append(t.Elems, c.expr(el))
		}
		return t
	case *syntax.ESeq:
		return &nSeq{A: c.expr(x.A), B: c.expr(x.B)}
	case *syntax.EAnd:
		return &nAnd{L: c.expr(x.L), R: c.expr(x.R)}
	case *syntax.EOr:
		return &nOr{L: c.expr(x.L), R: c.expr(x.R)}
	case *syntax.EAnnot:
		return c.expr(x.E)
	}
	panic(fmt.Sprintf("compile: unhandled expression %T", e))
}

func (c *Compiler) fun(x *syntax.EFun) *cFun {
	f := &cFun{Sp: x.Sp, Simple: true}
	pushed := 0
	for _, p := range x.Params {
		cp := c.compilePat(p)
		if cp.Kind != pkVar {
			f.Simple = false
		}
		f.Params = append(f.Params, cp)
		c.bindPat(&cp)
		pushed += len(cp.Slots)
	}
	f.Body = c.expr(x.Body)
	c.pop(pushed)
	return f
}

func (c *Compiler) let(x *syntax.ELet) node {
	l := &nLet{Rec: x.Rec}
	if x.Rec {
		for _, b := range x.Bindings {
			c.push(b.Pat.(*syntax.PVar).Name)
		}
		for _, b := range x.Bindings {
			l.Binds = append(l.Binds, nBind{E: c.expr(b.Expr)})
		}
		l.Body = c.expr(x.Body)
		c.pop(len(x.Bindings))
		return l
	}
	total := 0
	var pats []cPat
	for _, b := range x.Bindings {
		l.Binds = append(l.Binds, nBind{E: c.expr(b.Expr)}) // RHS sees only the outer scope
		pats = append(pats, c.compilePat(b.Pat))
	}
	for i := range pats {
		l.Binds[i].Pat = pats[i]
		c.bindPat(&pats[i])
		total += len(pats[i].Slots)
	}
	l.Body = c.expr(x.Body)
	c.pop(total)
	return l
}
