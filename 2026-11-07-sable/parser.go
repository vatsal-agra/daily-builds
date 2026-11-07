package sable

import "fmt"

type parser struct {
	toks []Token
	i    int
	nest int
}

func (p *parser) peek() Token { return p.toks[p.i] }
func (p *parser) next() Token {
	t := p.toks[p.i]
	if t.Kind != TEOF {
		p.i++
	}
	return t
}
func (p *parser) isOp(s string) bool {
	t := p.peek()
	return t.Kind == TOp && t.Text == s
}
func (p *parser) isKw(s string) bool {
	t := p.peek()
	return t.Kind == TKeyword && t.Text == s
}
func (p *parser) fail(t Token, f string, a ...any) {
	panic(&Error{t.Pos, fmt.Sprintf(f, a...)})
}
func describe(t Token) string {
	switch t.Kind {
	case TEOF:
		return "end of file"
	case TInt:
		return "number " + t.Text
	}
	return fmt.Sprintf("%q", t.Text)
}
func (p *parser) expectOp(s string) Token {
	t := p.peek()
	if t.Kind != TOp || t.Text != s {
		p.fail(t, "expected %q, found %s", s, describe(t))
	}
	return p.next()
}
func (p *parser) expectIdent() Token {
	t := p.peek()
	if t.Kind != TIdent {
		p.fail(t, "expected identifier, found %s", describe(t))
	}
	return p.next()
}

// Parse parses and semantically checks a program.
func Parse(src string) (prog *Program, err error) {
	toks, err := Lex(src)
	if err != nil {
		return nil, err
	}
	defer func() {
		if r := recover(); r != nil {
			if e, ok := r.(*Error); ok {
				prog, err = nil, e
				return
			}
			panic(r)
		}
	}()
	p := &parser{toks: toks}
	prog = &Program{ByName: map[string]*FuncDecl{}}
	for p.peek().Kind != TEOF {
		if !p.isKw("func") {
			p.fail(p.peek(), "expected 'func' at top level, found %s", describe(p.peek()))
		}
		f := p.parseFunc()
		if _, dup := prog.ByName[f.Name]; dup {
			p.fail(Token{Pos: f.P}, "function %q declared twice", f.Name)
		}
		prog.Funcs = append(prog.Funcs, f)
		prog.ByName[f.Name] = f
	}
	check(prog)
	return prog, nil
}

func (p *parser) parseFunc() *FuncDecl {
	kw := p.next()
	name := p.expectIdent()
	f := &FuncDecl{P: kw.Pos, Name: name.Text}
	p.expectOp("(")
	for !p.isOp(")") {
		id := p.expectIdent()
		for _, q := range f.Params {
			if q == id.Text {
				p.fail(id, "duplicate parameter %q", id.Text)
			}
		}
		f.Params = append(f.Params, id.Text)
		if !p.isOp(")") {
			p.expectOp(",")
		}
	}
	p.expectOp(")")
	f.Body = p.parseBlock()
	return f
}

func (p *parser) enter(t Token) {
	p.nest++
	if p.nest > maxStmtNest {
		p.fail(t, "nesting too deep (more than %d levels of blocks)", maxStmtNest)
	}
}

func (p *parser) checkDepth(t Token, d int) int {
	if d > maxExprDepth {
		p.fail(t, "expression too deeply nested (more than %d levels)", maxExprDepth)
	}
	return d
}

func (p *parser) parseBlock() *BlockStmt {
	lb := p.expectOp("{")
	p.enter(lb)
	defer func() { p.nest-- }()
	b := &BlockStmt{P: lb.Pos}
	for !p.isOp("}") {
		if p.peek().Kind == TEOF {
			p.fail(p.peek(), "unexpected end of file, missing '}' for block opened at %s", lb.Pos)
		}
		b.Stmts = append(b.Stmts, p.parseStmt())
	}
	p.next()
	return b
}

func (p *parser) parseSimple() Stmt { // var decl / assignment / expression statement (no ';')
	t := p.peek()
	if p.isKw("var") {
		p.next()
		id := p.expectIdent()
		p.expectOp("=")
		return &VarDecl{P: t.Pos, Name: id.Text, Init: p.parseExpr()}
	}
	if t.Kind == TIdent && p.toks[p.i+1].Kind == TOp && p.toks[p.i+1].Text == "=" {
		p.next()
		p.next()
		return &Assign{P: t.Pos, Name: t.Text, X: p.parseExpr()}
	}
	e := p.parseExpr()
	if _, ok := e.(*Call); !ok {
		p.fail(t, "expression statement must be a call (did you mean an assignment?)")
	}
	return &ExprStmt{P: t.Pos, X: e}
}

func (p *parser) parseStmt() Stmt {
	t := p.peek()
	switch {
	case p.isOp("{"):
		return p.parseBlock()
	case p.isKw("if"):
		return p.parseIf()
	case p.isKw("while"):
		p.next()
		c := p.parseExpr()
		return &While{P: t.Pos, Cond: c, Body: p.parseBlock()}
	case p.isKw("for"):
		p.next()
		f := &For{P: t.Pos}
		if !p.isOp(";") {
			f.Init = p.parseSimple()
		}
		p.expectOp(";")
		if !p.isOp(";") {
			f.Cond = p.parseExpr()
		}
		p.expectOp(";")
		if !p.isOp("{") {
			f.Post = p.parseSimple()
			if _, ok := f.Post.(*VarDecl); ok {
				p.fail(t, "cannot declare a variable in a for-loop post statement")
			}
		}
		f.Body = p.parseBlock()
		return f
	case p.isKw("return"):
		p.next()
		r := &Return{P: t.Pos}
		if !p.isOp(";") {
			r.X = p.parseExpr()
		}
		p.expectOp(";")
		return r
	case p.isKw("break"):
		p.next()
		p.expectOp(";")
		return &Break{t.Pos}
	case p.isKw("continue"):
		p.next()
		p.expectOp(";")
		return &Continue{t.Pos}
	case p.isKw("print"):
		p.next()
		p.expectOp("(")
		x := p.parseExpr()
		p.expectOp(")")
		p.expectOp(";")
		return &Print{P: t.Pos, X: x}
	}
	s := p.parseSimple()
	p.expectOp(";")
	return s
}

func (p *parser) parseIf() Stmt {
	t := p.next()
	p.enter(t)
	defer func() { p.nest-- }()
	c := p.parseExpr()
	s := &If{P: t.Pos, Cond: c, Then: p.parseBlock()}
	if p.isKw("else") {
		p.next()
		if p.isKw("if") {
			s.Else = p.parseIf()
		} else {
			s.Else = p.parseBlock()
		}
	}
	return s
}

var binPrec = map[string]int{
	"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5,
	"==": 6, "!=": 6, "<": 7, "<=": 7, ">": 7, ">=": 7,
	"<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10,
}

func (p *parser) parseExpr() Expr { return p.parseBin(1) }

func (p *parser) parseBin(min int) Expr {
	l := p.parseUnary()
	for {
		t := p.peek()
		prec, ok := binPrec[t.Text]
		if t.Kind != TOp || !ok || prec < min {
			return l
		}
		p.next()
		r := p.parseBin(prec + 1)
		d := p.checkDepth(t, 1+max(exprDepth(l), exprDepth(r)))
		l = &Binary{P: t.Pos, Op: t.Text, L: l, R: r, d: d}
	}
}

func (p *parser) parseUnary() Expr {
	t := p.peek()
	if t.Kind == TOp && (t.Text == "-" || t.Text == "!" || t.Text == "~") {
		p.next()
		p.nest++
		defer func() { p.nest-- }()
		if p.nest > maxExprDepth {
			p.fail(t, "expression too deeply nested (more than %d levels)", maxExprDepth)
		}
		x := p.parseUnary()
		return &Unary{P: t.Pos, Op: t.Text, X: x, d: p.checkDepth(t, 1+exprDepth(x))}
	}
	return p.parsePrimary()
}

func (p *parser) parsePrimary() Expr {
	t := p.next()
	switch {
	case t.Kind == TInt:
		return &IntLit{P: t.Pos, V: t.Val}
	case t.Kind == TIdent:
		if p.isOp("(") {
			p.next()
			c := &Call{P: t.Pos, Name: t.Text}
			p.nest++
			defer func() { p.nest-- }()
			if p.nest > maxExprDepth {
				p.fail(t, "expression too deeply nested (more than %d levels)", maxExprDepth)
			}
			d := 1
			for !p.isOp(")") {
				a := p.parseExpr()
				d = max(d, 1+exprDepth(a))
				c.Args = append(c.Args, a)
				if !p.isOp(")") {
					p.expectOp(",")
				}
			}
			p.next()
			c.d = p.checkDepth(t, d)
			return c
		}
		return &VarRef{P: t.Pos, Name: t.Text}
	case t.Kind == TOp && t.Text == "(":
		p.nest++
		defer func() { p.nest-- }()
		if p.nest > maxExprDepth {
			p.fail(t, "expression too deeply nested (more than %d levels)", maxExprDepth)
		}
		e := p.parseExpr()
		p.expectOp(")")
		return e
	}
	p.fail(t, "expected expression, found %s", describe(t))
	return nil
}
