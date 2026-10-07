package model

import (
	"fmt"
	"math/big"
	"strings"
	"unicode"
)

// ParseError is a positioned syntax / semantic error.
type ParseError struct {
	Line, Col int
	Msg       string
	Src       string
}

func (e *ParseError) Error() string {
	s := fmt.Sprintf("line %d, col %d: %s", e.Line, e.Col, e.Msg)
	if e.Src != "" {
		s += "\n    " + e.Src + "\n    " + strings.Repeat(" ", max(e.Col-1, 0)) + "^"
	}
	return s
}

type tokKind int

const (
	tEOF tokKind = iota
	tIdent
	tNum
	tPlus
	tMinus
	tStar
	tLE
	tGE
	tEQ
	tColon
)

type token struct {
	kind tokKind
	text string
	num  *big.Rat
	line int
	col  int
}

type lexLine struct {
	no   int
	src  string
	toks []token
}

func isIdentStart(r rune) bool { return unicode.IsLetter(r) || r == '_' }
func isIdentCont(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsDigit(r) || strings.ContainsRune("_.[]()~'$@", r)
}

func lexSource(src string) ([]lexLine, error) {
	var out []lexLine
	for i, raw := range strings.Split(strings.ReplaceAll(src, "\r\n", "\n"), "\n") {
		no := i + 1
		line := raw
		if k := strings.IndexAny(line, "\\#"); k >= 0 {
			line = line[:k]
		}
		rs := []rune(line)
		var toks []token
		for p := 0; p < len(rs); {
			c := rs[p]
			col := p + 1
			switch {
			case c == ' ' || c == '\t':
				p++
			case c == '+':
				toks = append(toks, token{kind: tPlus, text: "+", line: no, col: col})
				p++
			case c == '-':
				toks = append(toks, token{kind: tMinus, text: "-", line: no, col: col})
				p++
			case c == '*':
				toks = append(toks, token{kind: tStar, text: "*", line: no, col: col})
				p++
			case c == ':':
				toks = append(toks, token{kind: tColon, text: ":", line: no, col: col})
				p++
			case c == '<' || c == '>' || c == '=':
				k := tEQ
				if c == '<' {
					k = tLE
				} else if c == '>' {
					k = tGE
				}
				p++
				if p < len(rs) && rs[p] == '=' {
					p++
				}
				toks = append(toks, token{kind: k, text: string(c), line: no, col: col})
			case unicode.IsDigit(c) || c == '.':
				q := p
				for q < len(rs) && (unicode.IsDigit(rs[q]) || rs[q] == '.') {
					q++
				}
				if q < len(rs) && (rs[q] == 'e' || rs[q] == 'E') {
					r := q + 1
					if r < len(rs) && (rs[r] == '+' || rs[r] == '-') {
						r++
					}
					if r < len(rs) && unicode.IsDigit(rs[r]) {
						for r < len(rs) && unicode.IsDigit(rs[r]) {
							r++
						}
						q = r
					}
				}
				if q < len(rs) && rs[q] == '/' && q+1 < len(rs) && unicode.IsDigit(rs[q+1]) {
					q++
					for q < len(rs) && unicode.IsDigit(rs[q]) {
						q++
					}
				}
				text := string(rs[p:q])
				v, ok := new(big.Rat).SetString(text)
				if !ok {
					return nil, &ParseError{no, col, fmt.Sprintf("bad number %q", text), raw}
				}
				if strings.Contains(text, "/") && v.Denom().Sign() == 0 {
					return nil, &ParseError{no, col, "division by zero in fraction", raw}
				}
				toks = append(toks, token{kind: tNum, text: text, num: v, line: no, col: col})
				p = q
			case isIdentStart(c):
				q := p
				for q < len(rs) && isIdentCont(rs[q]) {
					q++
				}
				toks = append(toks, token{kind: tIdent, text: string(rs[p:q]), line: no, col: col})
				p = q
			default:
				return nil, &ParseError{no, col, fmt.Sprintf("unexpected character %q", string(c)), raw}
			}
		}
		out = append(out, lexLine{no: no, src: raw, toks: toks})
	}
	return out, nil
}

type section int

const (
	secNone section = iota
	secObj
	secCons
	secBounds
	secInt
	secBin
	secEnd
)

func isOp(k tokKind) bool { return k == tLE || k == tGE || k == tEQ }

// sectionOf recognises a section header line (returns section, handled).
func sectionOf(l lexLine) (section, bool, bool) {
	if len(l.toks) == 0 {
		return secNone, false, false
	}
	var words []string
	for _, t := range l.toks {
		if t.kind != tIdent && !(t.kind == tColon) {
			return secNone, false, false
		}
		words = append(words, strings.ToLower(t.text))
	}
	w := strings.Join(words, " ")
	switch w {
	case "maximize", "maximise", "max", "maximum":
		return secObj, true, true
	case "minimize", "minimise", "min", "minimum":
		return secObj, true, false
	case "subject to", "such that", "st", "s.t.", "s.t", "constraints":
		return secCons, true, false
	case "bounds", "bound":
		return secBounds, true, false
	case "integer", "integers", "general", "generals", "gen":
		return secInt, true, false
	case "binary", "binaries", "bin":
		return secBin, true, false
	case "end":
		return secEnd, true, false
	}
	return secNone, false, false
}

// Parse reads the LP text format into a Model.
func Parse(src string) (*Model, error) {
	lines, err := lexSource(src)
	if err != nil {
		return nil, err
	}
	m := New()
	sec := secNone
	sawObj := false
	explicitLo := map[int]bool{}

	// Group lines into logical statements (continuations).
	type stmt struct {
		toks []token
		src  string
		line int
	}
	var stmts []stmt
	var cur *stmt
	flush := func() {
		if cur != nil {
			stmts = append(stmts, *cur)
			cur = nil
		}
	}
	type item struct {
		sec  section
		st   *stmt
		maxi bool
	}
	var items []item
	for _, l := range lines {
		if len(l.toks) == 0 {
			continue
		}
		if s, ok, mx := sectionOf(l); ok {
			flush()
			items = append(items, item{sec: s, maxi: mx})
			stmts = nil
			continue
		}
		cont := false
		if cur != nil {
			last := cur.toks[len(cur.toks)-1].kind
			first := l.toks[0].kind
			if isOp(last) || last == tPlus || last == tMinus || last == tColon || last == tStar || first == tPlus || isOp(first) {
				cont = true
			}
		}
		if cont {
			cur.toks = append(cur.toks, l.toks...)
		} else {
			flush()
			cur = &stmt{toks: append([]token(nil), l.toks...), src: l.src, line: l.no}
		}
		// register at the end of group in the order encountered
		if !cont {
			items = append(items, item{sec: secNone, st: cur})
		}
	}
	flush()

	pe := func(t token, src, msg string, a ...any) error {
		return &ParseError{t.line, t.col, fmt.Sprintf(msg, a...), src}
	}
	for _, it := range items {
		if it.st == nil {
			sec = it.sec
			switch sec {
			case secObj:
				if sawObj {
					return nil, fmt.Errorf("more than one objective section")
				}
				sawObj = true
				m.Maximize = it.maxi
			case secEnd:
				// ignore everything after End
				goto done
			}
			continue
		}
		st := it.st
		p := &parser{toks: st.toks, src: st.src, m: m}
		switch sec {
		case secNone:
			return nil, pe(st.toks[0], st.src, "expected a section header (Minimize / Maximize) before this line")
		case secObj:
			if err := p.parseObjective(); err != nil {
				return nil, err
			}
		case secCons:
			if err := p.parseConstraint(); err != nil {
				return nil, err
			}
		case secBounds:
			if err := p.parseBound(explicitLo); err != nil {
				return nil, err
			}
		case secInt, secBin:
			for _, t := range st.toks {
				if t.kind != tIdent {
					return nil, pe(t, st.src, "expected a variable name")
				}
				j := m.VarIndex(t.text)
				if j < 0 {
					return nil, pe(t, st.src, "unknown variable %q (declare it in the objective with coefficient 0 if it is unused)", t.text)
				}
				m.Vars[j].Int = true
				if sec == secBin {
					m.Vars[j].Lo = big.NewRat(0, 1)
					m.Vars[j].Hi = big.NewRat(1, 1)
					explicitLo[j] = true
				}
			}
		}
	}
done:
	if !sawObj {
		return nil, fmt.Errorf("model has no objective section (start with Minimize or Maximize)")
	}
	if err := m.Validate(); err != nil {
		return nil, err
	}
	return m, nil
}

type parser struct {
	toks []token
	pos  int
	src  string
	m    *Model
}

func (p *parser) peek() token {
	if p.pos < len(p.toks) {
		return p.toks[p.pos]
	}
	last := token{kind: tEOF, text: "end of line"}
	if len(p.toks) > 0 {
		t := p.toks[len(p.toks)-1]
		last.line, last.col = t.line, t.col+len(t.text)
	}
	return last
}
func (p *parser) next() token { t := p.peek(); p.pos++; return t }
func (p *parser) errAt(t token, msg string, a ...any) error {
	return &ParseError{t.line, t.col, fmt.Sprintf(msg, a...), p.src}
}

// linExpr is a parsed linear expression: sum coef*var + const.
type linExpr struct {
	coef  map[int]*big.Rat
	order []int
	cons  *big.Rat
	first token
}

func newExpr() *linExpr { return &linExpr{coef: map[int]*big.Rat{}, cons: new(big.Rat)} }

func isInf(t token) bool {
	if t.kind != tIdent {
		return false
	}
	s := strings.ToLower(t.text)
	return s == "inf" || s == "infinity"
}

// parseExpr parses terms until an operator / colon / EOF. addVars controls
// whether unknown identifiers create variables.
func (p *parser) parseExpr(addVars bool) (*linExpr, error) {
	e := newExpr()
	e.first = p.peek()
	sign := 1
	expectTerm := true
	any := false
	for {
		t := p.peek()
		switch {
		case t.kind == tPlus || t.kind == tMinus:
			if !expectTerm && false {
				return nil, p.errAt(t, "unexpected sign")
			}
			p.next()
			if t.kind == tMinus {
				sign = -sign
			}
			expectTerm = true
			continue
		case t.kind == tNum || t.kind == tIdent && !isInf(t):
			var coef *big.Rat
			if t.kind == tNum {
				p.next()
				coef = new(big.Rat).Set(t.num)
				if p.peek().kind == tStar {
					p.next()
				}
				nt := p.peek()
				if nt.kind == tIdent && !isInf(nt) {
					p.next()
					if err := p.addTerm(e, nt, coef, sign, addVars); err != nil {
						return nil, err
					}
				} else {
					if sign < 0 {
						coef.Neg(coef)
					}
					e.cons.Add(e.cons, coef)
				}
			} else {
				p.next()
				if err := p.addTerm(e, t, big.NewRat(1, 1), sign, addVars); err != nil {
					return nil, err
				}
			}
			sign = 1
			expectTerm = false
			any = true
		case isInf(t):
			p.next()
			// treated as a huge constant marker; callers of bounds handle inf separately
			return nil, p.errAt(t, "infinity is only allowed in the bounds section")
		default:
			if expectTerm && (any || sign != 1) {
				return nil, p.errAt(t, "expected a term after sign, found %s", describe(t))
			}
			if !any {
				return nil, p.errAt(t, "expected an expression, found %s", describe(t))
			}
			return e, nil
		}
	}
}

func describe(t token) string {
	if t.kind == tEOF {
		return "end of line"
	}
	return fmt.Sprintf("%q", t.text)
}

func (p *parser) addTerm(e *linExpr, nameTok token, coef *big.Rat, sign int, addVars bool) error {
	j := p.m.VarIndex(nameTok.text)
	if j < 0 {
		if !addVars {
			return p.errAt(nameTok, "unknown variable %q", nameTok.text)
		}
		j = p.m.AddVar(nameTok.text)
	}
	if sign < 0 {
		coef = new(big.Rat).Neg(coef)
	}
	if old, ok := e.coef[j]; ok {
		old.Add(old, coef)
	} else {
		e.coef[j] = new(big.Rat).Set(coef)
		e.order = append(e.order, j)
	}
	return nil
}

func (p *parser) parseObjective() error {
	// optional "name :"
	if len(p.toks) >= 2 && p.toks[0].kind == tIdent && p.toks[1].kind == tColon {
		p.m.ObjName = p.toks[0].text
		p.pos = 2
	}
	if p.pos >= len(p.toks) {
		return nil // empty objective: feasibility problem
	}
	e, err := p.parseExpr(true)
	if err != nil {
		return err
	}
	if t := p.peek(); t.kind != tEOF {
		return p.errAt(t, "unexpected %s in objective", describe(t))
	}
	for _, j := range e.order {
		p.m.Vars[j].Obj.Add(p.m.Vars[j].Obj, e.coef[j])
	}
	p.m.ObjConst.Add(p.m.ObjConst, e.cons)
	return nil
}

func (p *parser) parseConstraint() error {
	name := ""
	if len(p.toks) >= 2 && p.toks[0].kind == tIdent && p.toks[1].kind == tColon {
		name = p.toks[0].text
		p.pos = 2
	}
	startTok := p.peek()
	var exprs []*linExpr
	var ops []token
	for {
		e, err := p.parseExpr(true)
		if err != nil {
			return err
		}
		exprs = append(exprs, e)
		t := p.peek()
		if isOp(t.kind) {
			p.next()
			ops = append(ops, t)
			continue
		}
		if t.kind != tEOF {
			return p.errAt(t, "unexpected %s in constraint", describe(t))
		}
		break
	}
	if len(ops) == 0 {
		return p.errAt(p.peek(), "constraint has no comparison operator (<=, >=, =)")
	}
	if len(ops) > 2 {
		return p.errAt(ops[2], "at most two comparison operators are allowed (range constraint)")
	}
	if name == "" {
		name = fmt.Sprintf("c%d", len(p.m.Rows)+1)
	}
	for _, r := range p.m.Rows {
		if r.Name == name {
			return p.errAt(startTok, "duplicate constraint name %q", name)
		}
	}
	row := Row{Name: name}
	if len(ops) == 1 {
		l, r := exprs[0], exprs[1]
		diff := newExpr()
		for _, j := range l.order {
			diff.coef[j] = new(big.Rat).Set(l.coef[j])
			diff.order = append(diff.order, j)
		}
		for _, j := range r.order {
			if v, ok := diff.coef[j]; ok {
				v.Sub(v, r.coef[j])
			} else {
				diff.coef[j] = new(big.Rat).Neg(r.coef[j])
				diff.order = append(diff.order, j)
			}
		}
		rhs := new(big.Rat).Sub(r.cons, l.cons)
		row.Entries = collect(diff)
		switch ops[0].kind {
		case tLE:
			row.Hi = rhs
		case tGE:
			row.Lo = rhs
		default:
			row.Lo, row.Hi = rhs, new(big.Rat).Set(rhs)
		}
	} else {
		a, b, c := exprs[0], exprs[1], exprs[2]
		if len(a.order) > 0 || len(c.order) > 0 {
			return p.errAt(a.first, "in a range constraint both outer sides must be constants")
		}
		if ops[0].kind != ops[1].kind || ops[0].kind == tEQ {
			return p.errAt(ops[1], "range constraint must use the same direction twice (lo <= expr <= hi)")
		}
		row.Entries = collect(b)
		lo := new(big.Rat).Sub(a.cons, b.cons)
		hi := new(big.Rat).Sub(c.cons, b.cons)
		if ops[0].kind == tLE { // a <= expr <= c  -> expr in [a-b.c, c-b.c]
			row.Lo, row.Hi = lo, hi
		} else { // a >= expr >= c
			row.Lo, row.Hi = hi, lo
		}
	}
	if len(row.Entries) == 0 {
		return p.errAt(startTok, "constraint %q contains no variables", name)
	}
	p.m.Rows = append(p.m.Rows, row)
	return nil
}

func collect(e *linExpr) []Entry {
	var out []Entry
	for _, j := range e.order {
		if e.coef[j].Sign() != 0 {
			out = append(out, Entry{j, e.coef[j]})
		}
	}
	return out
}

// parseBound handles one line of the bounds section.
func (p *parser) parseBound(explicitLo map[int]bool) error {
	// forms:  x free | [bnd op] x [op bnd]  with bnd = [+-] number | inf
	if len(p.toks) == 2 && p.toks[0].kind == tIdent && p.toks[1].kind == tIdent && strings.EqualFold(p.toks[1].text, "free") {
		j := p.m.VarIndex(p.toks[0].text)
		if j < 0 {
			return p.errAt(p.toks[0], "unknown variable %q", p.toks[0].text)
		}
		p.m.Vars[j].Lo, p.m.Vars[j].Hi = nil, nil
		explicitLo[j] = true
		return nil
	}
	type part struct {
		isVar bool
		j     int
		val   *big.Rat // nil + inf flag
		inf   int      // -1,+1 for infinities
		tok   token
	}
	var parts []part
	var ops []token
	for {
		t := p.peek()
		switch {
		case t.kind == tIdent && !isInf(t):
			p.next()
			j := p.m.VarIndex(t.text)
			if j < 0 {
				return p.errAt(t, "unknown variable %q in bounds (declare it in the objective with coefficient 0 if it is unused)", t.text)
			}
			parts = append(parts, part{isVar: true, j: j, tok: t})
		case t.kind == tNum || t.kind == tPlus || t.kind == tMinus || isInf(t):
			sign := 1
			first := t
			for p.peek().kind == tPlus || p.peek().kind == tMinus {
				if p.next().kind == tMinus {
					sign = -sign
				}
			}
			n := p.next()
			switch {
			case n.kind == tNum:
				v := new(big.Rat).Set(n.num)
				if sign < 0 {
					v.Neg(v)
				}
				parts = append(parts, part{val: v, tok: first})
			case isInf(n):
				parts = append(parts, part{inf: sign, tok: first})
			default:
				return p.errAt(n, "expected a number or inf in bounds, found %s", describe(n))
			}
		default:
			return p.errAt(t, "unexpected %s in bounds", describe(t))
		}
		t = p.peek()
		if isOp(t.kind) {
			p.next()
			ops = append(ops, t)
			continue
		}
		if t.kind != tEOF {
			return p.errAt(t, "unexpected %s in bounds", describe(t))
		}
		break
	}
	if len(ops) == 0 || len(ops) > 2 || len(parts) != len(ops)+1 {
		return p.errAt(p.toks[0], "malformed bound; use `x <= 5`, `x >= 1`, `1 <= x <= 5`, `x = 3` or `x free`")
	}
	nv := 0
	vi := -1
	for i, pt := range parts {
		if pt.isVar {
			nv++
			vi = i
		}
	}
	if nv != 1 {
		return p.errAt(p.toks[0], "a bound must mention exactly one variable")
	}
	if len(ops) == 2 && vi != 1 {
		return p.errAt(p.toks[0], "in `a <= x <= b` the variable must be in the middle")
	}
	j := parts[vi].j
	v := &p.m.Vars[j]
	apply := func(op tokKind, onLeft bool, b part) error {
		// normalise to "x op b"
		k := op
		if onLeft { // b op x  -> x (flip) b
			switch op {
			case tLE:
				k = tGE
			case tGE:
				k = tLE
			}
		}
		setLo := func() {
			if b.inf < 0 {
				v.Lo = nil
			} else {
				v.Lo = new(big.Rat).Set(b.val)
			}
			explicitLo[j] = true
		}
		setHi := func() {
			if b.inf > 0 {
				v.Hi = nil
			} else {
				v.Hi = new(big.Rat).Set(b.val)
			}
			if b.val != nil && b.val.Sign() < 0 && !explicitLo[j] {
				v.Lo = nil
				explicitLo[j] = true
			}
		}
		if b.inf != 0 && ((k == tLE && b.inf < 0) || (k == tGE && b.inf > 0)) {
			return p.errAt(b.tok, "this bound makes the variable infeasible")
		}
		switch k {
		case tGE:
			setLo()
		case tLE:
			setHi()
		default:
			if b.inf != 0 {
				return p.errAt(b.tok, "cannot fix a variable to infinity")
			}
			setLo()
			setHi()
		}
		return nil
	}
	if len(ops) == 1 {
		if vi == 0 {
			return apply(ops[0].kind, false, parts[1])
		}
		return apply(ops[0].kind, true, parts[0])
	}
	if ops[0].kind != ops[1].kind || ops[0].kind == tEQ {
		return p.errAt(ops[1], "double bound must be `lo <= x <= hi` (same direction twice)")
	}
	if err := apply(ops[0].kind, true, parts[0]); err != nil {
		return err
	}
	return apply(ops[1].kind, false, parts[2])
}
