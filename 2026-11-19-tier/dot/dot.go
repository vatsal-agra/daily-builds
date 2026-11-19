// Package dot parses a practical subset of Graphviz DOT: digraph/graph,
// optional "strict", node/edge statements with attribute lists, edge chains,
// node/edge/graph default attributes, quoted ids, and all three comment styles.
// Subgraphs, ports and HTML labels are rejected with positioned errors.
package dot

import (
	"fmt"
	"strings"
	"unicode"
)

// Node is a declared or implicitly created node.
type Node struct {
	ID    string
	Attrs map[string]string
}

// Edge connects two node ids.
type Edge struct {
	From, To string
	Attrs    map[string]string
}

// Graph is the parsed result. Nodes keep first-appearance order.
type Graph struct {
	Directed bool
	Strict   bool
	Name     string
	Attrs    map[string]string
	Nodes    []*Node
	Edges    []*Edge
}

// Error carries a source position.
type Error struct {
	Line, Col int
	Msg       string
}

func (e *Error) Error() string { return fmt.Sprintf("line %d, col %d: %s", e.Line, e.Col, e.Msg) }

type tokKind int

const (
	tEOF tokKind = iota
	tID
	tStr
	tArrow // -> or --
	tPunct
)

type token struct {
	kind      tokKind
	text      string
	line, col int
}

type lexer struct {
	src       []rune
	pos       int
	line, col int
}

func (l *lexer) errf(line, col int, f string, a ...any) *Error {
	return &Error{line, col, fmt.Sprintf(f, a...)}
}

func (l *lexer) peekRune(o int) rune {
	if l.pos+o < len(l.src) {
		return l.src[l.pos+o]
	}
	return 0
}

func (l *lexer) adv() rune {
	r := l.src[l.pos]
	l.pos++
	if r == '\n' {
		l.line++
		l.col = 1
	} else {
		l.col++
	}
	return r
}

func isIDStart(r rune) bool { return r == '_' || unicode.IsLetter(r) || r > 127 }
func isIDRune(r rune) bool  { return isIDStart(r) || unicode.IsDigit(r) }

func (l *lexer) next() (token, error) {
	for l.pos < len(l.src) {
		r := l.src[l.pos]
		switch {
		case unicode.IsSpace(r):
			l.adv()
			continue
		case r == '/' && l.peekRune(1) == '/', r == '#' && l.col == 1:
			for l.pos < len(l.src) && l.src[l.pos] != '\n' {
				l.adv()
			}
			continue
		case r == '/' && l.peekRune(1) == '*':
			sl, sc := l.line, l.col
			l.adv()
			l.adv()
			for {
				if l.pos >= len(l.src) {
					return token{}, l.errf(sl, sc, "unterminated /* comment")
				}
				if l.src[l.pos] == '*' && l.peekRune(1) == '/' {
					l.adv()
					l.adv()
					break
				}
				l.adv()
			}
			continue
		}
		break
	}
	if l.pos >= len(l.src) {
		return token{tEOF, "", l.line, l.col}, nil
	}
	line, col := l.line, l.col
	r := l.src[l.pos]
	switch {
	case r == '"':
		l.adv()
		var sb strings.Builder
		for {
			if l.pos >= len(l.src) {
				return token{}, l.errf(line, col, "unterminated string")
			}
			c := l.adv()
			if c == '"' {
				break
			}
			if c == '\\' && l.pos < len(l.src) {
				n := l.adv()
				switch n {
				case '"':
					sb.WriteRune('"')
				case '\n':
				default:
					sb.WriteRune('\\')
					sb.WriteRune(n)
				}
				continue
			}
			sb.WriteRune(c)
		}
		return token{tStr, sb.String(), line, col}, nil
	case r == '-' && (l.peekRune(1) == '>' || l.peekRune(1) == '-'):
		l.adv()
		op := "-" + string(l.adv())
		return token{tArrow, op, line, col}, nil
	case isIDStart(r):
		var sb strings.Builder
		for l.pos < len(l.src) && isIDRune(l.src[l.pos]) {
			sb.WriteRune(l.adv())
		}
		return token{tID, sb.String(), line, col}, nil
	case unicode.IsDigit(r) || r == '.' || r == '-':
		var sb strings.Builder
		if r == '-' {
			sb.WriteRune(l.adv())
		}
		digits, dot := 0, false
		for l.pos < len(l.src) {
			c := l.src[l.pos]
			if unicode.IsDigit(c) {
				digits++
			} else if c == '.' && !dot {
				dot = true
			} else {
				break
			}
			sb.WriteRune(l.adv())
		}
		if digits == 0 {
			return token{}, l.errf(line, col, "malformed number %q", sb.String())
		}
		return token{tID, sb.String(), line, col}, nil
	case r == '<':
		return token{}, l.errf(line, col, "HTML labels are not supported")
	case strings.ContainsRune("{}[];,=:", r):
		l.adv()
		return token{tPunct, string(r), line, col}, nil
	}
	return token{}, l.errf(line, col, "unexpected character %q", r)
}

type parser struct {
	lx   *lexer
	tok  token
	g    *Graph
	idx  map[string]*Node
	nDef map[string]string
	eDef map[string]string
	seen map[[2]string]bool
}

func (p *parser) advance() error {
	t, err := p.lx.next()
	if err != nil {
		return err
	}
	p.tok = t
	return nil
}

func (p *parser) errAt(t token, f string, a ...any) *Error {
	return &Error{t.line, t.col, fmt.Sprintf(f, a...)}
}

func (p *parser) isP(s string) bool { return p.tok.kind == tPunct && p.tok.text == s }

func (p *parser) expectP(s string) error {
	if !p.isP(s) {
		return p.errAt(p.tok, "expected %q, found %s", s, p.describe())
	}
	return p.advance()
}

func (p *parser) describe() string {
	switch p.tok.kind {
	case tEOF:
		return "end of input"
	case tStr:
		return fmt.Sprintf("string %q", p.tok.text)
	}
	return fmt.Sprintf("%q", p.tok.text)
}

// Parse parses DOT source.
func Parse(src string) (*Graph, error) {
	p := &parser{lx: &lexer{src: []rune(src), line: 1, col: 1},
		g: &Graph{Attrs: map[string]string{}}, idx: map[string]*Node{},
		nDef: map[string]string{}, eDef: map[string]string{}, seen: map[[2]string]bool{}}
	if err := p.advance(); err != nil {
		return nil, err
	}
	if p.tok.kind == tID && strings.EqualFold(p.tok.text, "strict") {
		p.g.Strict = true
		if err := p.advance(); err != nil {
			return nil, err
		}
	}
	if p.tok.kind != tID || !(strings.EqualFold(p.tok.text, "digraph") || strings.EqualFold(p.tok.text, "graph")) {
		return nil, p.errAt(p.tok, "expected 'digraph' or 'graph', found %s", p.describe())
	}
	p.g.Directed = strings.EqualFold(p.tok.text, "digraph")
	if err := p.advance(); err != nil {
		return nil, err
	}
	if p.tok.kind == tID || p.tok.kind == tStr {
		p.g.Name = p.tok.text
		if err := p.advance(); err != nil {
			return nil, err
		}
	}
	if err := p.expectP("{"); err != nil {
		return nil, err
	}
	for !p.isP("}") {
		if p.tok.kind == tEOF {
			return nil, p.errAt(p.tok, "unexpected end of input, missing '}'")
		}
		if err := p.stmt(); err != nil {
			return nil, err
		}
		for p.isP(";") {
			if err := p.advance(); err != nil {
				return nil, err
			}
		}
	}
	if err := p.advance(); err != nil {
		return nil, err
	}
	if p.tok.kind != tEOF {
		return nil, p.errAt(p.tok, "unexpected %s after closing '}'", p.describe())
	}
	return p.g, nil
}

func (p *parser) nodeRef() (string, error) {
	if p.tok.kind != tID && p.tok.kind != tStr {
		return "", p.errAt(p.tok, "expected node id, found %s", p.describe())
	}
	id := p.tok.text
	if err := p.advance(); err != nil {
		return "", err
	}
	if p.isP(":") {
		return "", p.errAt(p.tok, "node ports are not supported")
	}
	return id, nil
}

func (p *parser) attrList() (map[string]string, error) {
	m := map[string]string{}
	for p.isP("[") {
		if err := p.advance(); err != nil {
			return nil, err
		}
		for !p.isP("]") {
			if p.tok.kind != tID && p.tok.kind != tStr {
				return nil, p.errAt(p.tok, "expected attribute name, found %s", p.describe())
			}
			k := p.tok.text
			if err := p.advance(); err != nil {
				return nil, err
			}
			v := "true"
			if p.isP("=") {
				if err := p.advance(); err != nil {
					return nil, err
				}
				if p.tok.kind != tID && p.tok.kind != tStr {
					return nil, p.errAt(p.tok, "expected value for attribute %q, found %s", k, p.describe())
				}
				v = p.tok.text
				if err := p.advance(); err != nil {
					return nil, err
				}
			}
			m[k] = v
			if p.isP(",") || p.isP(";") {
				if err := p.advance(); err != nil {
					return nil, err
				}
			}
		}
		if err := p.advance(); err != nil {
			return nil, err
		}
	}
	return m, nil
}

func merge(base, over map[string]string) map[string]string {
	m := make(map[string]string, len(base)+len(over))
	for k, v := range base {
		m[k] = v
	}
	for k, v := range over {
		m[k] = v
	}
	return m
}

func (p *parser) ensure(id string) *Node {
	if n, ok := p.idx[id]; ok {
		return n
	}
	n := &Node{ID: id, Attrs: merge(p.nDef, nil)}
	p.idx[id] = n
	p.g.Nodes = append(p.g.Nodes, n)
	return n
}

func (p *parser) stmt() error {
	if p.tok.kind == tID {
		switch strings.ToLower(p.tok.text) {
		case "subgraph":
			return p.errAt(p.tok, "subgraphs are not supported")
		case "node", "edge", "graph":
			kind := strings.ToLower(p.tok.text)
			if err := p.advance(); err != nil {
				return err
			}
			if !p.isP("[") {
				return p.errAt(p.tok, "expected '[' after %q, found %s", kind, p.describe())
			}
			at, err := p.attrList()
			if err != nil {
				return err
			}
			switch kind {
			case "node":
				p.nDef = merge(p.nDef, at)
			case "edge":
				p.eDef = merge(p.eDef, at)
			default:
				p.g.Attrs = merge(p.g.Attrs, at)
			}
			return nil
		}
	}
	if p.isP("{") {
		return p.errAt(p.tok, "subgraphs are not supported")
	}
	first := p.tok
	id, err := p.nodeRef()
	if err != nil {
		return err
	}
	if p.isP("=") { // graph attribute: rankdir=LR
		if err := p.advance(); err != nil {
			return err
		}
		if p.tok.kind != tID && p.tok.kind != tStr {
			return p.errAt(p.tok, "expected value for %q, found %s", id, p.describe())
		}
		p.g.Attrs[id] = p.tok.text
		return p.advance()
	}
	chain := []string{id}
	wantOp := "--"
	if p.g.Directed {
		wantOp = "->"
	}
	for p.tok.kind == tArrow {
		if p.tok.text != wantOp {
			return p.errAt(p.tok, "%q is not valid in a %s (use %q)", p.tok.text, map[bool]string{true: "digraph", false: "graph"}[p.g.Directed], wantOp)
		}
		if err := p.advance(); err != nil {
			return err
		}
		n, err := p.nodeRef()
		if err != nil {
			return err
		}
		chain = append(chain, n)
	}
	at, err := p.attrList()
	if err != nil {
		return err
	}
	if len(chain) == 1 {
		n := p.ensure(id)
		n.Attrs = merge(n.Attrs, at)
		_ = first
		return nil
	}
	for _, c := range chain {
		p.ensure(c)
	}
	for i := 0; i+1 < len(chain); i++ {
		a, b := chain[i], chain[i+1]
		if p.g.Strict {
			k := [2]string{a, b}
			if !p.g.Directed && a > b {
				k = [2]string{b, a}
			}
			if p.seen[k] {
				continue
			}
			p.seen[k] = true
		}
		p.g.Edges = append(p.g.Edges, &Edge{From: a, To: b, Attrs: merge(p.eDef, at)})
	}
	return nil
}
