package sable

import "fmt"

type checker struct {
	prog   *Program
	fn     *FuncDecl
	scopes []map[string]int
	loops  int
}

func check(prog *Program) {
	main, ok := prog.ByName["main"]
	if !ok {
		panic(&Error{Pos{1, 1}, "program has no 'main' function"})
	}
	if len(main.Params) != 0 {
		panic(&Error{main.P, "'main' must take no parameters"})
	}
	for _, f := range prog.Funcs {
		c := &checker{prog: prog, fn: f}
		c.push()
		for _, p := range f.Params {
			c.declare(f.P, p)
		}
		c.block(f.Body, false)
	}
}

func (c *checker) push() { c.scopes = append(c.scopes, map[string]int{}) }
func (c *checker) pop()  { c.scopes = c.scopes[:len(c.scopes)-1] }
func (c *checker) declare(p Pos, name string) int {
	top := c.scopes[len(c.scopes)-1]
	if _, dup := top[name]; dup {
		panic(&Error{p, fmt.Sprintf("variable %q already declared in this scope", name)})
	}
	slot := c.fn.NSlots
	c.fn.NSlots++
	top[name] = slot
	return slot
}
func (c *checker) lookup(p Pos, name string) int {
	for i := len(c.scopes) - 1; i >= 0; i-- {
		if s, ok := c.scopes[i][name]; ok {
			return s
		}
	}
	panic(&Error{p, fmt.Sprintf("undefined variable %q", name)})
}

func (c *checker) block(b *BlockStmt, newScope bool) {
	if newScope {
		c.push()
		defer c.pop()
	}
	for _, s := range b.Stmts {
		c.stmt(s)
	}
}

func (c *checker) stmt(s Stmt) {
	switch s := s.(type) {
	case *VarDecl:
		c.expr(s.Init) // the initialiser cannot see the new variable
		s.Slot = c.declare(s.P, s.Name)
	case *Assign:
		c.expr(s.X)
		s.Slot = c.lookup(s.P, s.Name)
	case *If:
		c.expr(s.Cond)
		c.block(s.Then, true)
		if s.Else != nil {
			c.stmt(s.Else)
		}
	case *While:
		c.expr(s.Cond)
		c.loops++
		c.block(s.Body, true)
		c.loops--
	case *For:
		c.push()
		if s.Init != nil {
			c.stmt(s.Init)
		}
		if s.Cond != nil {
			c.expr(s.Cond)
		}
		if s.Post != nil {
			c.stmt(s.Post)
		}
		c.loops++
		c.block(s.Body, true)
		c.loops--
		c.pop()
	case *Return:
		if s.X != nil {
			c.expr(s.X)
		}
	case *Break:
		if c.loops == 0 {
			panic(&Error{s.P, "'break' outside a loop"})
		}
	case *Continue:
		if c.loops == 0 {
			panic(&Error{s.P, "'continue' outside a loop"})
		}
	case *Print:
		c.expr(s.X)
	case *ExprStmt:
		c.expr(s.X)
	case *BlockStmt:
		c.block(s, true)
	}
}

func (c *checker) expr(e Expr) {
	switch e := e.(type) {
	case *VarRef:
		e.Slot = c.lookup(e.P, e.Name)
	case *Unary:
		c.expr(e.X)
	case *Binary:
		c.expr(e.L)
		c.expr(e.R)
	case *Call:
		f, ok := c.prog.ByName[e.Name]
		if !ok {
			panic(&Error{e.P, fmt.Sprintf("call to undefined function %q", e.Name)})
		}
		if len(f.Params) != len(e.Args) {
			panic(&Error{e.P, fmt.Sprintf("function %q takes %d argument(s), got %d", e.Name, len(f.Params), len(e.Args))})
		}
		for _, a := range e.Args {
			c.expr(a)
		}
	}
}
