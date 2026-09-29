package main

import (
	"fmt"
	"strconv"
	"strings"
)

type tokKind int

const (
	tEOF tokKind = iota
	tIdent
	tVar
	tInt
	tStr
	tPunct
)

type token struct {
	k         tokKind
	s         string
	i         int64
	line, col int
}

type ParseError struct {
	Line, Col int
	Msg       string
}

func (e *ParseError) Error() string { return fmt.Sprintf("%d:%d: %s", e.Line, e.Col, e.Msg) }

func lex(src string) ([]token, error) {
	var toks []token
	line, col := 1, 1
	i := 0
	adv := func(n int) {
		for k := 0; k < n; k++ {
			if src[i] == '\n' {
				line++
				col = 1
			} else {
				col++
			}
			i++
		}
	}
	for i < len(src) {
		c := src[i]
		switch {
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			adv(1)
		case c == '%' || (c == '/' && i+1 < len(src) && src[i+1] == '/'):
			for i < len(src) && src[i] != '\n' {
				adv(1)
			}
		case c == '/' && i+1 < len(src) && src[i+1] == '*':
			sl, sc := line, col
			adv(2)
			for {
				if i+1 >= len(src) {
					return nil, &ParseError{sl, sc, "unterminated block comment"}
				}
				if src[i] == '*' && src[i+1] == '/' {
					adv(2)
					break
				}
				adv(1)
			}
		case c >= '0' && c <= '9':
			j := i
			for j < len(src) && src[j] >= '0' && src[j] <= '9' {
				j++
			}
			n, err := strconv.ParseInt(src[i:j], 10, 64)
			if err != nil {
				return nil, &ParseError{line, col, "integer out of range: " + src[i:j]}
			}
			toks = append(toks, token{k: tInt, i: n, s: src[i:j], line: line, col: col})
			adv(j - i)
		case c == '_' || c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z':
			j := i
			for j < len(src) && (src[j] == '_' || src[j] >= 'A' && src[j] <= 'Z' || src[j] >= 'a' && src[j] <= 'z' || src[j] >= '0' && src[j] <= '9') {
				j++
			}
			k := tIdent
			if c == '_' || c >= 'A' && c <= 'Z' {
				k = tVar
			}
			toks = append(toks, token{k: k, s: src[i:j], line: line, col: col})
			adv(j - i)
		case c == '"':
			sl, sc := line, col
			j := i + 1
			var b strings.Builder
			for {
				if j >= len(src) || src[j] == '\n' {
					return nil, &ParseError{sl, sc, "unterminated string literal"}
				}
				if src[j] == '"' {
					break
				}
				if src[j] == '\\' && j+1 < len(src) {
					j++
					switch src[j] {
					case 'n':
						b.WriteByte('\n')
					case 't':
						b.WriteByte('\t')
					default:
						b.WriteByte(src[j])
					}
				} else {
					b.WriteByte(src[j])
				}
				j++
			}
			toks = append(toks, token{k: tStr, s: b.String(), line: sl, col: sc})
			adv(j + 1 - i)
		default:
			two := ""
			if i+1 < len(src) {
				two = src[i : i+2]
			}
			switch two {
			case ":-", "?-", "<=", ">=", "!=":
				toks = append(toks, token{k: tPunct, s: two, line: line, col: col})
				adv(2)
				continue
			}
			if strings.ContainsRune("(),.<>=+-*/", rune(c)) {
				toks = append(toks, token{k: tPunct, s: string(c), line: line, col: col})
				adv(1)
				continue
			}
			return nil, &ParseError{line, col, fmt.Sprintf("unexpected character %q", c)}
		}
	}
	toks = append(toks, token{k: tEOF, line: line, col: col})
	return toks, nil
}

type parser struct {
	toks    []token
	p       int
	anonCtr int
}

func Parse(src string) (*Program, error) {
	toks, err := lex(src)
	if err != nil {
		return nil, err
	}
	ps := &parser{toks: toks}
	prog := &Program{}
	for ps.peek().k != tEOF {
		if ps.isP("?-") {
			q, err := ps.parseQuery()
			if err != nil {
				return nil, err
			}
			prog.Queries = append(prog.Queries, q)
			continue
		}
		r, err := ps.parseRule()
		if err != nil {
			return nil, err
		}
		prog.Rules = append(prog.Rules, r)
	}
	return prog, nil
}

func (ps *parser) peek() token { return ps.toks[ps.p] }
func (ps *parser) peekN(n int) token {
	if ps.p+n < len(ps.toks) {
		return ps.toks[ps.p+n]
	}
	return ps.toks[len(ps.toks)-1]
}
func (ps *parser) next() token { t := ps.toks[ps.p]; ps.p++; return t }
func (ps *parser) isP(s string) bool {
	t := ps.peek()
	return t.k == tPunct && t.s == s
}
func (ps *parser) errf(t token, f string, a ...any) error {
	return &ParseError{t.line, t.col, fmt.Sprintf(f, a...)}
}
func (ps *parser) expectP(s string) (token, error) {
	t := ps.peek()
	if t.k != tPunct || t.s != s {
		return t, ps.errf(t, "expected %q, found %s", s, describe(t))
	}
	return ps.next(), nil
}

func describe(t token) string {
	switch t.k {
	case tEOF:
		return "end of input"
	case tStr:
		return strconv.Quote(t.s)
	}
	return fmt.Sprintf("%q", t.s)
}

func (ps *parser) parseRule() (*Rule, error) {
	start := ps.peek()
	head, err := ps.parseAtom(true)
	if err != nil {
		return nil, err
	}
	r := &Rule{Head: head, Line: start.line, Col: start.col}
	if ps.isP(":-") {
		ps.next()
		r.Body, err = ps.parseBody()
		if err != nil {
			return nil, err
		}
	}
	if _, err := ps.expectP("."); err != nil {
		return nil, err
	}
	return r, nil
}

func (ps *parser) parseQuery() (*Query, error) {
	t := ps.next()
	body, err := ps.parseBody()
	if err != nil {
		return nil, err
	}
	if _, err := ps.expectP("."); err != nil {
		return nil, err
	}
	return &Query{Body: body, Line: t.line}, nil
}

func (ps *parser) parseBody() ([]Literal, error) {
	var out []Literal
	for {
		l, err := ps.parseLiteral()
		if err != nil {
			return nil, err
		}
		out = append(out, l)
		if ps.isP(",") {
			ps.next()
			continue
		}
		return out, nil
	}
}

func (ps *parser) parseLiteral() (Literal, error) {
	t := ps.peek()
	if t.k == tIdent && t.s == "not" {
		ps.next()
		a, err := ps.parseAtom(false)
		return Literal{Kind: LNeg, Atom: a}, err
	}
	if t.k == tIdent {
		n := ps.peekN(1)
		if (n.k == tPunct && (n.s == "(" || n.s == "," || n.s == ".")) || n.k == tEOF {
			a, err := ps.parseAtom(false)
			return Literal{Kind: LPos, Atom: a}, err
		}
	}
	l, err := ps.parseExpr()
	if err != nil {
		return Literal{}, err
	}
	op := ps.peek()
	if op.k != tPunct || !strings.Contains(" = != < <= > >= ", " "+op.s+" ") {
		return Literal{}, ps.errf(op, "expected comparison operator (=, !=, <, <=, >, >=), found %s", describe(op))
	}
	ps.next()
	r, err := ps.parseExpr()
	if err != nil {
		return Literal{}, err
	}
	return Literal{Kind: LCmp, Op: op.s, L: l, R: r}, nil
}

func (ps *parser) parseAtom(head bool) (Atom, error) {
	t := ps.next()
	if t.k != tIdent || t.s == "not" {
		return Atom{}, ps.errf(t, "expected predicate name, found %s", describe(t))
	}
	a := Atom{Pred: t.s}
	if !ps.isP("(") {
		return a, nil
	}
	ps.next()
	if ps.isP(")") {
		return a, ps.errf(ps.peek(), "empty argument list; write %s without parentheses", t.s)
	}
	for {
		term, err := ps.parseTerm(head)
		if err != nil {
			return a, err
		}
		a.Args = append(a.Args, term)
		if ps.isP(",") {
			ps.next()
			continue
		}
		break
	}
	_, err := ps.expectP(")")
	return a, err
}

func (ps *parser) parseTerm(head bool) (Term, error) {
	t := ps.next()
	switch t.k {
	case tInt:
		return Term{C: Int(t.i)}, nil
	case tStr:
		return Term{C: Str(t.s)}, nil
	case tVar:
		if t.s == "_" {
			ps.anonCtr++
			return Term{Var: true, Name: fmt.Sprintf("_#%d", ps.anonCtr)}, nil
		}
		return Term{Var: true, Name: t.s}, nil
	case tIdent:
		if head && ps.isP("(") && (t.s == "count" || t.s == "sum" || t.s == "min" || t.s == "max") {
			ps.next()
			agg := Term{Agg: t.s}
			if ps.isP("*") {
				if t.s != "count" {
					return agg, ps.errf(ps.peek(), "%s needs a variable argument", t.s)
				}
				ps.next()
			} else {
				v := ps.next()
				if v.k != tVar || v.s == "_" {
					return agg, ps.errf(v, "aggregate argument must be a variable, found %s", describe(v))
				}
				agg.AggOf = v.s
			}
			_, err := ps.expectP(")")
			return agg, err
		}
		return Term{C: Str(t.s)}, nil
	case tPunct:
		if t.s == "-" && ps.peek().k == tInt {
			n := ps.next()
			return Term{C: Int(-n.i)}, nil
		}
	}
	return Term{}, ps.errf(t, "expected a term, found %s", describe(t))
}

func (ps *parser) parseExpr() (*Expr, error) {
	l, err := ps.parseMul()
	if err != nil {
		return nil, err
	}
	for ps.isP("+") || ps.isP("-") {
		op := ps.next().s
		r, err := ps.parseMul()
		if err != nil {
			return nil, err
		}
		l = &Expr{Op: op, L: l, R: r}
	}
	return l, nil
}

func (ps *parser) parseMul() (*Expr, error) {
	l, err := ps.parseUnary()
	if err != nil {
		return nil, err
	}
	for {
		t := ps.peek()
		if t.k == tPunct && (t.s == "*" || t.s == "/") || t.k == tIdent && t.s == "mod" {
			ps.next()
			r, err := ps.parseUnary()
			if err != nil {
				return nil, err
			}
			l = &Expr{Op: t.s, L: l, R: r}
			continue
		}
		return l, nil
	}
}

func (ps *parser) parseUnary() (*Expr, error) {
	if ps.isP("-") {
		ps.next()
		e, err := ps.parseUnary()
		if err != nil {
			return nil, err
		}
		if e.Op == "" && !e.T.Var && !e.T.C.IsStr {
			return &Expr{T: Term{C: Int(-e.T.C.I)}}, nil
		}
		return &Expr{Op: "-", L: &Expr{T: Term{C: Int(0)}}, R: e}, nil
	}
	if ps.isP("(") {
		ps.next()
		e, err := ps.parseExpr()
		if err != nil {
			return nil, err
		}
		_, err = ps.expectP(")")
		return e, err
	}
	t := ps.peek()
	if t.k == tPunct || t.k == tEOF {
		return nil, ps.errf(t, "expected an expression, found %s", describe(t))
	}
	term, err := ps.parseTerm(false)
	if err != nil {
		return nil, err
	}
	return &Expr{T: term}, nil
}
