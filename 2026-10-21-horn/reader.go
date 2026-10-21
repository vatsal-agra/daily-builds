package main

import (
	"bufio"
	"fmt"
	"io"
	"math/big"
	"strconv"
	"strings"
	"unicode"
)

type tokKind int

const (
	tAtom tokKind = iota
	tQAtom
	tVar
	tNum
	tStr
	tBq
	tPunct
	tEnd
	tEOF
)

type token struct {
	kind   tokKind
	text   string
	num    Term
	layout bool // layout/comment precedes this token
	line   int
}

type SyntaxError struct {
	Msg  string
	Line int
}

func (e *SyntaxError) Error() string { return fmt.Sprintf("line %d: %s", e.Line, e.Msg) }

// runeSrc buffers runes from a reader with arbitrary lookahead.
type runeSrc struct {
	r    *bufio.Reader
	buf  []rune
	pos  int
	eof  bool
	line int
}

func newRuneSrc(r io.Reader) *runeSrc {
	return &runeSrc{r: bufio.NewReader(r), line: 1}
}

func (s *runeSrc) peekN(n int) rune {
	for len(s.buf)-s.pos <= n {
		if s.eof {
			return -1
		}
		c, _, err := s.r.ReadRune()
		if err != nil {
			s.eof = true
			return -1
		}
		s.buf = append(s.buf, c)
	}
	return s.buf[s.pos+n]
}
func (s *runeSrc) peek() rune { return s.peekN(0) }
func (s *runeSrc) next() rune {
	c := s.peek()
	if c == -1 {
		return -1
	}
	s.pos++
	if c == '\n' {
		s.line++
	}
	if s.pos > 4096 {
		s.buf = append([]rune(nil), s.buf[s.pos:]...)
		s.pos = 0
	}
	return c
}

func isSymbolChar(c rune) bool { return strings.ContainsRune("+-*/\\^<>=~:.?@#&$", c) }
func isAlnum(c rune) bool {
	return c == '_' || unicode.IsLetter(c) || unicode.IsDigit(c)
}
func isDigit(c rune) bool { return c >= '0' && c <= '9' }

// Reader reads terms from a text source.
type Reader struct {
	m     *Machine
	src   *runeSrc
	toks  []token
	tp    int
	Names []string // variable names in order of appearance
	Vars  []*Var
	vmap  map[string]*Var
	count map[string]int
	Line  int // line where the last term started
}

func newReader(m *Machine, r io.Reader) *Reader { return &Reader{m: m, src: newRuneSrc(r)} }

func (rd *Reader) errf(line int, f string, a ...interface{}) error {
	return &SyntaxError{Msg: fmt.Sprintf(f, a...), Line: line}
}

func (rd *Reader) skipLayout() (bool, error) {
	any := false
	for {
		c := rd.src.peek()
		switch {
		case c == -1:
			return any, nil
		case unicode.IsSpace(c):
			rd.src.next()
			any = true
		case c == '%':
			for c != '\n' && c != -1 {
				rd.src.next()
				c = rd.src.peek()
			}
			any = true
		case c == '/' && rd.src.peekN(1) == '*':
			line := rd.src.line
			rd.src.next()
			rd.src.next()
			for {
				c := rd.src.next()
				if c == -1 {
					return any, rd.errf(line, "unterminated block comment")
				}
				if c == '*' && rd.src.peek() == '/' {
					rd.src.next()
					break
				}
			}
			any = true
		default:
			return any, nil
		}
	}
}

func (rd *Reader) lexQuoted(q rune) (string, error) {
	var sb strings.Builder
	line := rd.src.line
	for {
		c := rd.src.next()
		switch {
		case c == -1:
			return "", rd.errf(line, "unterminated quoted")
		case c == q:
			if rd.src.peek() == q {
				rd.src.next()
				sb.WriteRune(q)
				continue
			}
			return sb.String(), nil
		case c == '\\':
			r, skip, err := rd.lexEscape(q)
			if err != nil {
				return "", err
			}
			if !skip {
				sb.WriteRune(r)
			}
		default:
			sb.WriteRune(c)
		}
	}
}

func (rd *Reader) lexEscape(q rune) (rune, bool, error) {
	c := rd.src.next()
	switch c {
	case 'n':
		return '\n', false, nil
	case 't':
		return '\t', false, nil
	case 'r':
		return '\r', false, nil
	case 'a':
		return 7, false, nil
	case 'b':
		return 8, false, nil
	case 'f':
		return 12, false, nil
	case 'v':
		return 11, false, nil
	case '0', '1', '2', '3', '4', '5', '6', '7':
		n := int(c - '0')
		for isDigit(rd.src.peek()) && rd.src.peek() < '8' {
			n = n*8 + int(rd.src.next()-'0')
		}
		if rd.src.peek() == '\\' {
			rd.src.next()
		}
		return rune(n), false, nil
	case 'x':
		n := 0
		for strings.ContainsRune("0123456789abcdefABCDEF", rd.src.peek()) && rd.src.peek() != -1 {
			d, _ := strconv.ParseInt(string(rd.src.next()), 16, 32)
			n = n*16 + int(d)
		}
		if rd.src.peek() == '\\' {
			rd.src.next()
		}
		return rune(n), false, nil
	case 'u', 'U':
		cnt := 4
		if c == 'U' {
			cnt = 8
		}
		n := 0
		for i := 0; i < cnt; i++ {
			d, err := strconv.ParseInt(string(rd.src.next()), 16, 32)
			if err != nil {
				return 0, false, rd.errf(rd.src.line, "bad \\u escape")
			}
			n = n*16 + int(d)
		}
		return rune(n), false, nil
	case 'e':
		return 27, false, nil
	case 's':
		return ' ', false, nil
	case 'z':
		return 0, false, rd.errf(rd.src.line, "undefined escape \\z")
	case '\n':
		return 0, true, nil
	case '\\', '\'', '"', '`':
		return c, false, nil
	}
	return 0, false, rd.errf(rd.src.line, "undefined escape sequence \\%c", c)
}

func (rd *Reader) lexNumber() (token, error) {
	s := rd.src
	line := s.line
	c := s.peek()
	if c == '0' {
		switch n := s.peekN(1); {
		case n == '\'':
			// 0'c character code
			c2 := s.peekN(2)
			if c2 == '\\' {
				s.next()
				s.next()
				s.next()
				r, _, err := rd.lexEscape('\'')
				if err != nil {
					return token{}, err
				}
				return token{kind: tNum, num: Int(r), line: line}, nil
			}
			if c2 == '\'' && s.peekN(3) == '\'' {
				s.next()
				s.next()
				s.next()
				s.next()
				return token{kind: tNum, num: Int('\''), line: line}, nil
			}
			if c2 != -1 {
				s.next()
				s.next()
				s.next()
				return token{kind: tNum, num: Int(c2), line: line}, nil
			}
		case n == 'x' || n == 'o' || n == 'b':
			base := map[rune]int{'x': 16, 'o': 8, 'b': 2}[n]
			digs := ""
			i := 2
			for {
				d := s.peekN(i)
				if d != -1 && validDigit(d, base) {
					digs += string(d)
					i++
					continue
				}
				break
			}
			if digs != "" {
				for k := 0; k < i; k++ {
					s.next()
				}
				b, _ := new(big.Int).SetString(digs, base)
				return token{kind: tNum, num: normBig(b), line: line}, nil
			}
		}
	}
	var sb strings.Builder
	for isDigit(s.peek()) || (s.peek() == '_' && isDigit(s.peekN(1))) {
		ch := s.next()
		if ch != '_' {
			sb.WriteRune(ch)
		}
	}
	isFloat := false
	if s.peek() == '.' && isDigit(s.peekN(1)) {
		isFloat = true
		sb.WriteRune(s.next())
		for isDigit(s.peek()) {
			sb.WriteRune(s.next())
		}
		if e := s.peek(); e == 'e' || e == 'E' {
			n1 := s.peekN(1)
			if isDigit(n1) || ((n1 == '+' || n1 == '-') && isDigit(s.peekN(2))) {
				sb.WriteRune(s.next())
				sb.WriteRune(s.next())
				for isDigit(s.peek()) {
					sb.WriteRune(s.next())
				}
			}
		}
		if s.peek() == 'I' && s.peekN(1) == 'n' && s.peekN(2) == 'f' {
			s.next()
			s.next()
			s.next()
			return token{kind: tNum, num: Float(posInf), line: line}, nil
		}
		if s.peek() == 'N' && s.peekN(1) == 'a' && s.peekN(2) == 'N' {
			s.next()
			s.next()
			s.next()
			return token{kind: tNum, num: Float(nanVal), line: line}, nil
		}
	} else if s.peek() == '\'' && sb.Len() <= 2 {
		// radix notation R'digits
		if base, err := strconv.Atoi(sb.String()); err == nil && base >= 2 && base <= 36 {
			digs := ""
			i := 1
			for {
				d := s.peekN(i)
				if d != -1 && isAlnum(d) && d != '_' {
					if v, err := strconv.ParseInt(string(d), 36, 32); err == nil && int(v) < base {
						digs += string(d)
						i++
						continue
					}
				}
				break
			}
			if digs != "" {
				for k := 0; k < i; k++ {
					s.next()
				}
				b, _ := new(big.Int).SetString(digs, base)
				return token{kind: tNum, num: normBig(b), line: line}, nil
			}
		}
	}
	if isFloat {
		f, err := strconv.ParseFloat(sb.String(), 64)
		if err != nil {
			return token{}, rd.errf(line, "illegal number")
		}
		return token{kind: tNum, num: Float(f), line: line}, nil
	}
	b, _ := new(big.Int).SetString(sb.String(), 10)
	return token{kind: tNum, num: normBig(b), line: line}, nil
}

func (rd *Reader) nextToken() (token, error) {
	layout, err := rd.skipLayout()
	if err != nil {
		return token{}, err
	}
	s := rd.src
	line := s.line
	c := s.peek()
	switch {
	case c == -1:
		return token{kind: tEOF, layout: layout, line: line}, nil
	case isDigit(c):
		t, err := rd.lexNumber()
		t.layout = layout
		return t, err
	case c == '_' || unicode.IsUpper(c):
		var sb strings.Builder
		for isAlnum(s.peek()) {
			sb.WriteRune(s.next())
		}
		return token{kind: tVar, text: sb.String(), layout: layout, line: line}, nil
	case unicode.IsLetter(c):
		var sb strings.Builder
		for isAlnum(s.peek()) {
			sb.WriteRune(s.next())
		}
		return token{kind: tAtom, text: sb.String(), layout: layout, line: line}, nil
	case c == '\'':
		s.next()
		str, err := rd.lexQuoted('\'')
		return token{kind: tQAtom, text: str, layout: layout, line: line}, err
	case c == '"':
		s.next()
		str, err := rd.lexQuoted('"')
		return token{kind: tStr, text: str, layout: layout, line: line}, err
	case c == '`':
		s.next()
		str, err := rd.lexQuoted('`')
		return token{kind: tBq, text: str, layout: layout, line: line}, err
	case strings.ContainsRune("()[]{},|", c):
		s.next()
		if c == '|' && s.peek() == '|' {
			s.next()
			return token{kind: tAtom, text: "||", layout: layout, line: line}, nil
		}
		return token{kind: tPunct, text: string(c), layout: layout, line: line}, nil
	case c == '!':
		s.next()
		return token{kind: tAtom, text: "!", layout: layout, line: line}, nil
	case c == ';':
		s.next()
		return token{kind: tAtom, text: ";", layout: layout, line: line}, nil
	case c == '.':
		n := s.peekN(1)
		if n == -1 || unicode.IsSpace(n) || n == '%' {
			s.next()
			return token{kind: tEnd, layout: layout, line: line}, nil
		}
		fallthrough
	case isSymbolChar(c):
		var sb strings.Builder
		for isSymbolChar(s.peek()) {
			sb.WriteRune(s.next())
		}
		return token{kind: tAtom, text: sb.String(), layout: layout, line: line}, nil
	}
	s.next()
	return token{}, rd.errf(line, "illegal character %q", c)
}

// ReadTerm reads the next clause/term. Returns (nil, io.EOF) at end of input.
func (rd *Reader) ReadTerm() (Term, error) {
	rd.toks = rd.toks[:0]
	rd.tp = 0
	rd.Names, rd.Vars = nil, nil
	rd.vmap = map[string]*Var{}
	rd.count = map[string]int{}
	var lexErr error
	for {
		t, err := rd.nextToken()
		if err != nil {
			lexErr = err
			rd.recover()
			return nil, lexErr
		}
		if t.kind == tEOF {
			if len(rd.toks) == 0 {
				return nil, io.EOF
			}
			return nil, rd.errf(t.line, "operator expected (end of file inside term)")
		}
		if len(rd.toks) == 0 {
			rd.Line = t.line
		}
		rd.toks = append(rd.toks, t)
		if t.kind == tEnd {
			break
		}
	}
	p := &parser{rd: rd}
	term, err := p.parse(1200)
	if err == nil && p.peek().kind != tEnd {
		err = rd.errf(p.peek().line, "operator expected")
	}
	if err != nil {
		return nil, err
	}
	return term, nil
}

// recover skips to the next end token after a lexical error.
func (rd *Reader) recover() {
	for {
		t, err := rd.nextToken()
		if err != nil {
			continue
		}
		if t.kind == tEnd || t.kind == tEOF {
			return
		}
	}
}

// Singletons returns named variables that occur only once.
func (rd *Reader) Singletons() []string {
	var out []string
	for _, n := range rd.Names {
		if rd.count[n] == 1 && !strings.HasPrefix(n, "_") {
			out = append(out, n)
		}
	}
	return out
}

type parser struct {
	rd *Reader
	p  int
}

func (p *parser) peek() token { return p.rd.toks[p.p] }
func (p *parser) advance() token {
	t := p.rd.toks[p.p]
	if p.p < len(p.rd.toks)-1 {
		p.p++
	}
	return t
}
func (p *parser) peekAt(n int) token {
	if p.p+n >= len(p.rd.toks) {
		return p.rd.toks[len(p.rd.toks)-1]
	}
	return p.rd.toks[p.p+n]
}

func (p *parser) errf(t token, f string, a ...interface{}) error {
	return p.rd.errf(t.line, f, a...)
}

func (p *parser) isTermStart(t token) bool {
	switch t.kind {
	case tEnd, tEOF:
		return false
	case tPunct:
		return t.text == "(" || t.text == "[" || t.text == "{"
	}
	return true
}

func (p *parser) infixOp(t token) *opDef {
	var name string
	switch t.kind {
	case tAtom:
		name = t.text
	case tPunct:
		if t.text == "," || t.text == "|" {
			name = t.text
		} else {
			return nil
		}
	case tQAtom:
		name = t.text
	default:
		return nil
	}
	if e := p.rd.m.ops[name]; e != nil {
		return e.infix
	}
	return nil
}

func (p *parser) parse(max int) (Term, error) {
	left, lp, err := p.parsePrimary(max)
	if err != nil {
		return nil, err
	}
	return p.parseInfix(left, lp, max)
}

func (p *parser) parseInfix(left Term, lp int, max int) (Term, error) {
	for {
		t := p.peek()
		name := t.text
		if t.kind == tPunct && name == "|" {
			name = "|"
		}
		if d := p.infixOp(t); d != nil {
			if d.pri <= max && d.leftMax() >= lp {
				// make sure a term can follow
				if nt := p.peekAt(1); p.isTermStart(nt) || nt.kind == tAtom {
					save := p.p
					p.advance()
					right, err := p.parse(d.rightMax())
					if err != nil {
						p.p = save
						return nil, err
					}
					fn := name
					if fn == "|" {
						fn = ";"
					}
					left = &Compound{Fn: mkAtom(fn), Args: []Term{left, right}}
					lp = d.pri
					continue
				}
			}
		}
		if t.kind == tAtom {
			if e := p.rd.m.ops[name]; e != nil && e.postfix != nil && e.postfix.pri <= max && e.postfix.leftMax() >= lp {
				p.advance()
				left = &Compound{Fn: mkAtom(name), Args: []Term{left}}
				lp = e.postfix.pri
				continue
			}
		}
		return left, nil
	}
}

func (p *parser) mkVar(name string) Term {
	rd := p.rd
	if name == "_" {
		return rd.m.newVar()
	}
	rd.count[name]++
	if v, ok := rd.vmap[name]; ok {
		return v
	}
	v := rd.m.newVar()
	rd.vmap[name] = v
	rd.Names = append(rd.Names, name)
	rd.Vars = append(rd.Vars, v)
	return v
}

func (p *parser) parseArgs() ([]Term, error) {
	var args []Term
	for {
		a, err := p.parse(999)
		if err != nil {
			return nil, err
		}
		args = append(args, a)
		t := p.advance()
		if t.kind == tPunct && t.text == "," {
			continue
		}
		if t.kind == tPunct && t.text == ")" {
			return args, nil
		}
		return nil, p.errf(t, "illegal start of term or missing ) or ,")
	}
}

func (p *parser) strTerm(s string, flag string) Term {
	switch flag {
	case "atom":
		return mkAtom(s)
	case "chars":
		var items []Term
		for _, r := range s {
			items = append(items, mkAtom(string(r)))
		}
		return mkList(items, atNil)
	}
	var items []Term
	for _, r := range s {
		items = append(items, Int(r))
	}
	return mkList(items, atNil)
}

func (p *parser) parsePrimary(max int) (Term, int, error) {
	t := p.advance()
	m := p.rd.m
	switch t.kind {
	case tNum:
		return t.num, 0, nil
	case tVar:
		return p.mkVar(t.text), 0, nil
	case tStr:
		return p.strTerm(t.text, m.flags["double_quotes"]), 0, nil
	case tBq:
		return p.strTerm(t.text, "codes"), 0, nil
	case tPunct:
		switch t.text {
		case "(":
			inner, err := p.parse(1200)
			if err != nil {
				return nil, 0, err
			}
			c := p.advance()
			if c.kind != tPunct || c.text != ")" {
				return nil, 0, p.errf(c, "expected )")
			}
			return inner, 0, nil
		case "[":
			if n := p.peek(); n.kind == tPunct && n.text == "]" {
				p.advance()
				return p.atomOrCompound(atNil.Name, t, max, true)
			}
			var items []Term
			for {
				a, err := p.parse(999)
				if err != nil {
					return nil, 0, err
				}
				items = append(items, a)
				n := p.advance()
				if n.kind == tPunct && n.text == "," {
					continue
				}
				var tail Term = atNil
				if n.kind == tPunct && n.text == "|" {
					tail, err = p.parse(999)
					if err != nil {
						return nil, 0, err
					}
					n = p.advance()
				}
				if n.kind == tPunct && n.text == "]" {
					return mkList(items, tail), 0, nil
				}
				return nil, 0, p.errf(n, "illegal start of term or missing ] in list")
			}
		case "{":
			if n := p.peek(); n.kind == tPunct && n.text == "}" {
				p.advance()
				return p.atomOrCompound("{}", t, max, true)
			}
			inner, err := p.parse(1200)
			if err != nil {
				return nil, 0, err
			}
			c := p.advance()
			if c.kind != tPunct || c.text != "}" {
				return nil, 0, p.errf(c, "expected }")
			}
			return &Compound{Fn: atCurly, Args: []Term{inner}}, 0, nil
		case ",":
			return nil, 0, p.errf(t, "illegal start of term")
		case "|":
			return p.atomOrCompound("|", t, max, false)
		}
		return nil, 0, p.errf(t, "illegal start of term: %s", t.text)
	case tQAtom:
		return p.atomOrCompound(t.text, t, max, true)
	case tAtom:
		return p.atomOrCompound(t.text, t, max, false)
	}
	return nil, 0, p.errf(t, "unexpected end of clause")
}

func (p *parser) atomOrCompound(name string, t token, max int, quoted bool) (Term, int, error) {
	nx := p.peek()
	if nx.kind == tPunct && nx.text == "(" && !nx.layout {
		p.advance()
		args, err := p.parseArgs()
		if err != nil {
			return nil, 0, err
		}
		return &Compound{Fn: mkAtom(name), Args: args}, 0, nil
	}
	if !quoted && name == "-" && nx.kind == tNum && !nx.layout {
		p.advance()
		switch v := nx.num.(type) {
		case Int:
			return -v, 0, nil
		case Float:
			return -v, 0, nil
		case *big.Int:
			return normBig(new(big.Int).Neg(v)), 0, nil
		}
	}
	if !quoted && name == "+" && nx.kind == tNum && !nx.layout {
		p.advance()
		return nx.num, 0, nil
	}
	e := p.rd.m.ops[name]
	if e != nil && !quoted {
		if d := e.prefix; d != nil {
			// decide whether to treat as prefix operator or plain atom
			asAtom := !p.isTermStart(nx)
			if !asAtom && nx.kind == tAtom || nx.kind == tPunct && nx.text == "," {
				// next is an infix operator that cannot start a term => atom
				if id := p.infixOp(nx); id != nil {
					ne := p.rd.m.ops[nx.text]
					if ne.prefix == nil {
						after := p.peekAt(1)
						if !(after.kind == tPunct && after.text == "(" && !after.layout) {
							asAtom = true
						}
					}
				}
			}
			if nx.kind == tPunct && nx.text == "|" {
				asAtom = true
			}
			if !asAtom {
				pri := d.pri
				argMax := d.rightMax()
				if pri > max {
					pri = 999
					if argMax > 999 {
						argMax = 999
					}
				}
				save := p.p
				arg, err := p.parse(argMax)
				if err == nil {
					return &Compound{Fn: mkAtom(name), Args: []Term{arg}}, pri, nil
				}
				// fall back: treat as atom (e.g. "- )" style); restore
				p.p = save
				if _, isSyn := err.(*SyntaxError); !isSyn {
					return nil, 0, err
				}
				return nil, 0, err
			}
			pri := d.pri
			if pri > max {
				pri = 0
			}
			return mkAtom(name), pri, nil
		}
		if e.infix != nil {
			pri := e.infix.pri
			if pri > max {
				pri = 0
			}
			return mkAtom(name), pri, nil
		}
	}
	return mkAtom(name), 0, nil
}

func validDigit(d rune, base int) bool {
	v, err := strconv.ParseInt(string(d), 36, 32)
	return err == nil && int(v) < base
}
