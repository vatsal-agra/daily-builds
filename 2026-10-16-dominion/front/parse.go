// Package front implements the Dom source language: lexer, parser and lowering to Dominion IR.
package front

import (
	"fmt"
	"strconv"
	"unicode"
)

// Error is a source diagnostic.
type Error struct {
	Line, Col int
	Msg       string
}

func (e *Error) Error() string { return fmt.Sprintf("%d:%d: %s", e.Line, e.Col, e.Msg) }

type tokKind int

const (
	tEOF tokKind = iota
	tInt
	tIdent
	tKw
	tOp
)

type token struct {
	kind      tokKind
	s         string
	n         int64
	line, col int
}

var keywords = map[string]bool{"fn": true, "var": true, "if": true, "else": true, "while": true, "for": true,
	"return": true, "break": true, "continue": true, "print": true}

func lex(src string) ([]token, error) {
	var toks []token
	rs := []rune(src)
	line, col := 1, 1
	i := 0
	adv := func() {
		if rs[i] == '\n' {
			line++
			col = 1
		} else {
			col++
		}
		i++
	}
	for i < len(rs) {
		c := rs[i]
		switch {
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			adv()
		case c == '/' && i+1 < len(rs) && rs[i+1] == '/':
			for i < len(rs) && rs[i] != '\n' {
				adv()
			}
		case unicode.IsDigit(c):
			l, cl := line, col
			st := i
			for i < len(rs) && unicode.IsDigit(rs[i]) {
				adv()
			}
			if i < len(rs) && (unicode.IsLetter(rs[i]) || rs[i] == '_') {
				return nil, &Error{l, cl, "malformed number"}
			}
			u, err := strconv.ParseUint(string(rs[st:i]), 10, 64)
			if err != nil || u > 1<<63 {
				return nil, &Error{l, cl, "integer literal out of range"}
			}
			// 2^63 is only representable as -9223372036854775808; the parser checks the sign
			toks = append(toks, token{kind: tInt, n: int64(u), s: string(rs[st:i]), line: l, col: cl})
		case unicode.IsLetter(c) || c == '_':
			l, cl := line, col
			st := i
			for i < len(rs) && (unicode.IsLetter(rs[i]) || unicode.IsDigit(rs[i]) || rs[i] == '_') {
				adv()
			}
			w := string(rs[st:i])
			k := tIdent
			if keywords[w] {
				k = tKw
			}
			toks = append(toks, token{kind: k, s: w, line: l, col: cl})
		default:
			l, cl := line, col
			two := ""
			if i+1 < len(rs) {
				two = string(rs[i : i+2])
			}
			switch two {
			case "<<", ">>", "<=", ">=", "==", "!=", "&&", "||", "+=", "-=", "*=":
				adv()
				adv()
				toks = append(toks, token{kind: tOp, s: two, line: l, col: cl})
				continue
			}
			if containsRune("+-*/%&|^~!<>=(){}[];,", c) {
				adv()
				toks = append(toks, token{kind: tOp, s: string(c), line: l, col: cl})
				continue
			}
			return nil, &Error{l, cl, fmt.Sprintf("unexpected character %q", c)}
		}
	}
	toks = append(toks, token{kind: tEOF, line: line, col: col})
	return toks, nil
}

func containsRune(s string, r rune) bool {
	for _, c := range s {
		if c == r {
			return true
		}
	}
	return false
}

// ---------- AST ----------

type pos struct{ line, col int }

type expr interface{ position() pos }
type (
	numLit struct {
		pos
		n int64
	}
	varRef struct {
		pos
		name string
	}
	indexEx struct {
		pos
		name string
		idx  expr
	}
	callEx struct {
		pos
		name string
		args []expr
	}
	unaryEx struct {
		pos
		op string
		x  expr
	}
	binEx struct {
		pos
		op   string
		l, r expr
	}
)

func (p pos) position() pos { return p }

type stmt interface{ position() pos }
type (
	varDecl struct {
		pos
		name string
		init expr
	}
	arrDecl struct {
		pos
		name string
		size int64
	}
	assign struct {
		pos
		name string
		idx  expr
		val  expr
	} // idx nil for scalar
	ifStmt struct {
		pos
		cond      expr
		then, els []stmt
	}
	whileStmt struct {
		pos
		cond expr
		body []stmt
		post stmt
	}
	forStmt struct {
		pos
		init stmt
		cond expr
		post stmt
		body []stmt
	}
	retStmt struct {
		pos
		val expr
	}
	brkStmt   struct{ pos }
	contStmt  struct{ pos }
	printStmt struct {
		pos
		val expr
	}
	exprStmt struct {
		pos
		x expr
	}
	blockStmt struct {
		pos
		body []stmt
	}
)

type fnDecl struct {
	pos
	name   string
	params []string
	body   []stmt
}

type parser struct {
	toks []token
	i    int
}

func (p *parser) peek() token { return p.toks[p.i] }
func (p *parser) next() token { t := p.toks[p.i]; p.i++; return t }
func (p *parser) errAt(t token, f string, a ...any) error {
	return &Error{t.line, t.col, fmt.Sprintf(f, a...)}
}
func (p *parser) isOp(s string) bool { t := p.peek(); return t.kind == tOp && t.s == s }
func (p *parser) isKw(s string) bool { t := p.peek(); return t.kind == tKw && t.s == s }
func (p *parser) expectOp(s string) (token, error) {
	t := p.peek()
	if t.kind != tOp || t.s != s {
		return t, p.errAt(t, "expected %q, found %s", s, desc(t))
	}
	p.i++
	return t, nil
}
func desc(t token) string {
	switch t.kind {
	case tEOF:
		return "end of file"
	case tInt:
		return "number " + t.s
	}
	return fmt.Sprintf("%q", t.s)
}
func (p *parser) ident() (token, error) {
	t := p.peek()
	if t.kind != tIdent {
		return t, p.errAt(t, "expected identifier, found %s", desc(t))
	}
	p.i++
	return t, nil
}

func parseProgram(src string) ([]*fnDecl, error) {
	toks, err := lex(src)
	if err != nil {
		return nil, err
	}
	p := &parser{toks: toks}
	var fns []*fnDecl
	for p.peek().kind != tEOF {
		if !p.isKw("fn") {
			return nil, p.errAt(p.peek(), "expected 'fn', found %s", desc(p.peek()))
		}
		kw := p.next()
		name, err := p.ident()
		if err != nil {
			return nil, err
		}
		if _, err := p.expectOp("("); err != nil {
			return nil, err
		}
		var params []string
		for !p.isOp(")") {
			id, err := p.ident()
			if err != nil {
				return nil, err
			}
			params = append(params, id.s)
			if p.isOp(",") {
				p.next()
			} else if !p.isOp(")") {
				return nil, p.errAt(p.peek(), "expected ',' or ')' in parameter list")
			}
		}
		p.next()
		body, err := p.block()
		if err != nil {
			return nil, err
		}
		fns = append(fns, &fnDecl{pos{kw.line, kw.col}, name.s, params, body})
	}
	return fns, nil
}

func (p *parser) block() ([]stmt, error) {
	if _, err := p.expectOp("{"); err != nil {
		return nil, err
	}
	var out []stmt
	for !p.isOp("}") {
		if p.peek().kind == tEOF {
			return nil, p.errAt(p.peek(), "unterminated block (missing '}')")
		}
		s, err := p.stmt()
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	p.next()
	return out, nil
}

func (p *parser) stmt() (stmt, error) {
	t := p.peek()
	ps := pos{t.line, t.col}
	semi := func() error { _, e := p.expectOp(";"); return e }
	switch {
	case t.kind == tOp && t.s == "{":
		b, err := p.block()
		return &blockStmt{ps, b}, err
	case t.kind == tKw:
		switch t.s {
		case "if":
			return p.ifStmt()
		case "while":
			p.next()
			c, err := p.expr(0)
			if err != nil {
				return nil, err
			}
			b, err := p.block()
			return &whileStmt{ps, c, b, nil}, err
		case "for":
			p.next()
			var init, post stmt
			var err error
			if !p.isOp(";") {
				if init, err = p.simple(); err != nil {
					return nil, err
				}
			}
			if err = semi(); err != nil {
				return nil, err
			}
			var cond expr = &numLit{ps, 1}
			if !p.isOp(";") {
				if cond, err = p.expr(0); err != nil {
					return nil, err
				}
			}
			if err = semi(); err != nil {
				return nil, err
			}
			if !p.isOp("{") {
				if post, err = p.simple(); err != nil {
					return nil, err
				}
			}
			b, err := p.block()
			return &forStmt{ps, init, cond, post, b}, err
		case "return":
			p.next()
			var v expr
			if !p.isOp(";") {
				var err error
				if v, err = p.expr(0); err != nil {
					return nil, err
				}
			}
			return &retStmt{ps, v}, semi()
		case "break":
			p.next()
			return &brkStmt{ps}, semi()
		case "continue":
			p.next()
			return &contStmt{ps}, semi()
		case "print":
			p.next()
			if _, err := p.expectOp("("); err != nil {
				return nil, err
			}
			v, err := p.expr(0)
			if err != nil {
				return nil, err
			}
			if _, err := p.expectOp(")"); err != nil {
				return nil, err
			}
			return &printStmt{ps, v}, semi()
		case "var":
			s, err := p.simple()
			if err != nil {
				return nil, err
			}
			return s, semi()
		}
		return nil, p.errAt(t, "unexpected keyword %q", t.s)
	}
	s, err := p.simple()
	if err != nil {
		return nil, err
	}
	return s, semi()
}

func (p *parser) ifStmt() (stmt, error) {
	t := p.next()
	c, err := p.expr(0)
	if err != nil {
		return nil, err
	}
	th, err := p.block()
	if err != nil {
		return nil, err
	}
	s := &ifStmt{pos{t.line, t.col}, c, th, nil}
	if p.isKw("else") {
		p.next()
		if p.isKw("if") {
			e, err := p.ifStmt()
			if err != nil {
				return nil, err
			}
			s.els = []stmt{e}
		} else if s.els, err = p.block(); err != nil {
			return nil, err
		}
	}
	return s, nil
}

// simple parses var decls, assignments and expression statements (no trailing ';').
func (p *parser) simple() (stmt, error) {
	t := p.peek()
	ps := pos{t.line, t.col}
	if p.isKw("var") {
		p.next()
		id, err := p.ident()
		if err != nil {
			return nil, err
		}
		if p.isOp("[") {
			p.next()
			n := p.next()
			if n.kind != tInt || n.n < 1 || n.n > 4096 {
				return nil, p.errAt(n, "array size must be an integer in 1..4096")
			}
			if _, err := p.expectOp("]"); err != nil {
				return nil, err
			}
			return &arrDecl{ps, id.s, n.n}, nil
		}
		if _, err := p.expectOp("="); err != nil {
			return nil, err
		}
		e, err := p.expr(0)
		return &varDecl{ps, id.s, e}, err
	}
	if t.kind == tIdent {
		// assignment forms need lookahead
		save := p.i
		p.next()
		var idx expr
		if p.isOp("[") {
			p.next()
			e, err := p.expr(0)
			if err != nil {
				return nil, err
			}
			if _, err := p.expectOp("]"); err != nil {
				return nil, err
			}
			idx = e
		}
		if nt := p.peek(); nt.kind == tOp && (nt.s == "=" || nt.s == "+=" || nt.s == "-=" || nt.s == "*=") {
			p.next()
			v, err := p.expr(0)
			if err != nil {
				return nil, err
			}
			if nt.s != "=" {
				var cur expr = &varRef{ps, t.s}
				if idx != nil {
					cur = &indexEx{ps, t.s, idx}
				}
				v = &binEx{pos{nt.line, nt.col}, nt.s[:1], cur, v}
			}
			return &assign{ps, t.s, idx, v}, nil
		}
		p.i = save
	}
	e, err := p.expr(0)
	if err != nil {
		return nil, err
	}
	if _, ok := e.(*callEx); !ok {
		return nil, &Error{ps.line, ps.col, "expression statement must be a call"}
	}
	return &exprStmt{ps, e}, nil
}

var prec = map[string]int{
	"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
	"<": 7, "<=": 7, ">": 7, ">=": 7, "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10,
}

func (p *parser) expr(minPrec int) (expr, error) {
	l, err := p.unary()
	if err != nil {
		return nil, err
	}
	for {
		t := p.peek()
		pr, ok := prec[t.s]
		if t.kind != tOp || !ok || pr <= minPrec {
			return l, nil
		}
		p.next()
		r, err := p.expr(pr)
		if err != nil {
			return nil, err
		}
		l = &binEx{pos{t.line, t.col}, t.s, l, r}
	}
}

func (p *parser) unary() (expr, error) {
	t := p.peek()
	if t.kind == tOp && (t.s == "-" || t.s == "!" || t.s == "~") {
		p.next()
		if nt := p.peek(); t.s == "-" && nt.kind == tInt { // negative literal, including -2^63
			p.next()
			return &numLit{pos{t.line, t.col}, -nt.n}, nil
		}
		x, err := p.unary()
		if err != nil {
			return nil, err
		}
		if n, ok := x.(*numLit); ok && t.s == "-" {
			return &numLit{pos{t.line, t.col}, -n.n}, nil // -(-2^63) wraps to itself, as intended
		}
		return &unaryEx{pos{t.line, t.col}, t.s, x}, nil
	}
	return p.primary()
}

func (p *parser) primary() (expr, error) {
	t := p.next()
	ps := pos{t.line, t.col}
	switch {
	case t.kind == tInt:
		if t.n == -1<<63 { // literal 2^63 without a preceding minus
			return nil, p.errAt(t, "integer literal out of range (only -9223372036854775808 may use 2^63)")
		}
		return &numLit{ps, t.n}, nil
	case t.kind == tOp && t.s == "(":
		e, err := p.expr(0)
		if err != nil {
			return nil, err
		}
		_, err = p.expectOp(")")
		return e, err
	case t.kind == tIdent:
		if p.isOp("(") {
			p.next()
			var args []expr
			for !p.isOp(")") {
				a, err := p.expr(0)
				if err != nil {
					return nil, err
				}
				args = append(args, a)
				if p.isOp(",") {
					p.next()
				} else if !p.isOp(")") {
					return nil, p.errAt(p.peek(), "expected ',' or ')' in argument list")
				}
			}
			p.next()
			return &callEx{ps, t.s, args}, nil
		}
		if p.isOp("[") {
			p.next()
			i, err := p.expr(0)
			if err != nil {
				return nil, err
			}
			_, err = p.expectOp("]")
			return &indexEx{ps, t.s, i}, err
		}
		return &varRef{ps, t.s}, nil
	}
	return nil, p.errAt(t, "expected expression, found %s", desc(t))
}
