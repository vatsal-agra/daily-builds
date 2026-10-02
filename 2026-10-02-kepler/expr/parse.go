package expr

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode"
)

// Parse reads an infix formula. Identifiers are looked up in names (variable
// index); "pi" and "e" are constants. Precedence: ^ (right assoc) > unary -
// > * / > + -.   Note: -x^2 parses as -(x^2).
func Parse(src string, names []string) (*Node, error) {
	p := &parser{src: src, names: names}
	p.next()
	n, err := p.expr()
	if err != nil {
		return nil, err
	}
	if p.tok.kind != tEOF {
		return nil, fmt.Errorf("unexpected %q at position %d", p.tok.text, p.tok.pos)
	}
	return n, nil
}

type tkind int

const (
	tEOF tkind = iota
	tNum
	tIdent
	tSym
)

type token struct {
	kind tkind
	text string
	pos  int
}

type parser struct {
	src   string
	i     int
	tok   token
	names []string
	err   error
}

func (p *parser) next() {
	for p.i < len(p.src) && unicode.IsSpace(rune(p.src[p.i])) {
		p.i++
	}
	if p.i >= len(p.src) {
		p.tok = token{tEOF, "end of input", p.i}
		return
	}
	start := p.i
	c := p.src[p.i]
	switch {
	case c >= '0' && c <= '9' || c == '.':
		for p.i < len(p.src) && (p.src[p.i] >= '0' && p.src[p.i] <= '9' || p.src[p.i] == '.') {
			p.i++
		}
		if p.i < len(p.src) && (p.src[p.i] == 'e' || p.src[p.i] == 'E') {
			j := p.i + 1
			if j < len(p.src) && (p.src[j] == '+' || p.src[j] == '-') {
				j++
			}
			if j < len(p.src) && p.src[j] >= '0' && p.src[j] <= '9' {
				for j < len(p.src) && p.src[j] >= '0' && p.src[j] <= '9' {
					j++
				}
				p.i = j
			}
		}
		p.tok = token{tNum, p.src[start:p.i], start}
	case unicode.IsLetter(rune(c)) || c == '_':
		for p.i < len(p.src) && (unicode.IsLetter(rune(p.src[p.i])) || unicode.IsDigit(rune(p.src[p.i])) || p.src[p.i] == '_') {
			p.i++
		}
		p.tok = token{tIdent, p.src[start:p.i], start}
	default:
		p.i++
		p.tok = token{tSym, string(c), start}
	}
}

func (p *parser) expr() (*Node, error) {
	l, err := p.term()
	if err != nil {
		return nil, err
	}
	for p.tok.kind == tSym && (p.tok.text == "+" || p.tok.text == "-") {
		op := p.tok.text
		p.next()
		r, err := p.term()
		if err != nil {
			return nil, err
		}
		l = B(op, l, r)
	}
	return l, nil
}

func (p *parser) term() (*Node, error) {
	l, err := p.unary()
	if err != nil {
		return nil, err
	}
	for p.tok.kind == tSym && (p.tok.text == "*" || p.tok.text == "/") {
		op := p.tok.text
		p.next()
		r, err := p.unary()
		if err != nil {
			return nil, err
		}
		l = B(op, l, r)
	}
	return l, nil
}

func (p *parser) unary() (*Node, error) {
	if p.tok.kind == tSym && p.tok.text == "-" {
		p.next()
		a, err := p.unary()
		if err != nil {
			return nil, err
		}
		return U("neg", a), nil
	}
	if p.tok.kind == tSym && p.tok.text == "+" {
		p.next()
		return p.unary()
	}
	return p.power()
}

func (p *parser) power() (*Node, error) {
	b, err := p.atom()
	if err != nil {
		return nil, err
	}
	if p.tok.kind == tSym && (p.tok.text == "^") {
		p.next()
		e, err := p.unary() // right assoc, allows 2^-1
		if err != nil {
			return nil, err
		}
		return B("^", b, e), nil
	}
	return b, nil
}

func (p *parser) atom() (*Node, error) {
	t := p.tok
	switch t.kind {
	case tNum:
		v, err := strconv.ParseFloat(t.text, 64)
		if err != nil {
			return nil, fmt.Errorf("bad number %q at position %d", t.text, t.pos)
		}
		p.next()
		return C(v), nil
	case tIdent:
		p.next()
		if p.tok.kind == tSym && p.tok.text == "(" {
			isUn := false
			for _, u := range UnaryOps {
				if u == t.text {
					isUn = true
				}
			}
			if t.text == "ln" {
				t.text, isUn = "log", true
			}
			if !isUn {
				return nil, fmt.Errorf("unknown function %q at position %d", t.text, t.pos)
			}
			p.next()
			a, err := p.expr()
			if err != nil {
				return nil, err
			}
			if p.tok.text != ")" || p.tok.kind != tSym {
				return nil, fmt.Errorf("expected ) at position %d, got %q", p.tok.pos, p.tok.text)
			}
			p.next()
			return U(t.text, a), nil
		}
		switch strings.ToLower(t.text) {
		case "pi":
			return C(math.Pi), nil
		case "e":
			if !contains(p.names, "e") {
				return C(math.E), nil
			}
		}
		for i, n := range p.names {
			if n == t.text {
				return V(i), nil
			}
		}
		// default names x0, x1, ...
		if len(t.text) > 1 && t.text[0] == 'x' {
			if k, err := strconv.Atoi(t.text[1:]); err == nil && len(p.names) == 0 {
				return V(k), nil
			}
		}
		return nil, fmt.Errorf("unknown variable %q at position %d", t.text, t.pos)
	case tSym:
		if t.text == "(" {
			p.next()
			a, err := p.expr()
			if err != nil {
				return nil, err
			}
			if p.tok.text != ")" || p.tok.kind != tSym {
				return nil, fmt.Errorf("expected ) at position %d, got %q", p.tok.pos, p.tok.text)
			}
			p.next()
			return a, nil
		}
	}
	return nil, fmt.Errorf("unexpected %q at position %d", t.text, t.pos)
}

func contains(s []string, x string) bool {
	for _, v := range s {
		if v == x {
			return true
		}
	}
	return false
}
