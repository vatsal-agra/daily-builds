package main

import (
	"math"
	"math/big"
	"strconv"
	"strings"
	"unicode"
)

type writeOpts struct {
	quoted     bool
	ignoreOps  bool
	numberVars bool
}

type writer struct {
	sb   strings.Builder
	last rune
	o    writeOpts
	ops  OpTable
}

func formatTerm(t Term, quoted bool) string {
	return formatTermOpts(t, writeOpts{quoted: quoted, numberVars: true})
}

func formatTermOpts(t Term, o writeOpts) string {
	w := &writer{o: o, ops: gm.ops}
	w.write(t, 1200)
	return w.sb.String()
}

func formatFloat(f float64) string {
	switch {
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	case math.IsNaN(f):
		return "nan"
	}
	s := strconv.FormatFloat(f, 'g', -1, 64)
	if math.Abs(f) >= 1e15 || (f != 0 && math.Abs(f) < 1e-4) {
		s = strconv.FormatFloat(f, 'e', -1, 64)
	} else {
		s = strconv.FormatFloat(f, 'f', -1, 64)
	}
	mant, exp := s, ""
	if i := strings.IndexByte(s, 'e'); i >= 0 {
		mant, exp = s[:i], s[i:]
	}
	if !strings.Contains(mant, ".") {
		mant += ".0"
	}
	if exp != "" {
		sign := ""
		d := exp[1:]
		if d[0] == '-' {
			sign = "-"
		}
		d = strings.TrimLeft(d, "+-")
		if len(d) < 2 {
			d = "0" + d
		}
		exp = "e" + sign + d
	}
	return mant + exp
}

func atomNeedsQuote(s string) bool {
	if s == "" {
		return true
	}
	switch s {
	case "[]", "!", ";", "{}", ",", "|":
		return s == "," || s == "|"
	}
	rs := []rune(s)
	if unicode.IsLower(rs[0]) {
		for _, r := range rs {
			if !isAlnum(r) {
				return true
			}
		}
		return false
	}
	for _, r := range rs {
		if !isSymbolChar(r) {
			return true
		}
	}
	return false
}

func quoteAtom(s string) string {
	var sb strings.Builder
	sb.WriteByte('\'')
	for _, r := range s {
		switch r {
		case '\'':
			sb.WriteString("\\'")
		case '\\':
			sb.WriteString("\\\\")
		case '\n':
			sb.WriteString("\\n")
		case '\t':
			sb.WriteString("\\t")
		case 0:
			sb.WriteString("\\0\\")
		default:
			sb.WriteRune(r)
		}
	}
	sb.WriteByte('\'')
	return sb.String()
}

func (w *writer) atomText(a *Atom) string {
	if w.o.quoted && atomNeedsQuote(a.Name) {
		return quoteAtom(a.Name)
	}
	return a.Name
}

func (w *writer) emit(s string) {
	if s == "" {
		return
	}
	first := []rune(s)[0]
	if w.sb.Len() > 0 {
		l := w.last
		if (isAlnum(l) && isAlnum(first)) || (isSymbolChar(l) && isSymbolChar(first)) || (l == ',' && first != ' ' && false) {
			w.sb.WriteByte(' ')
		}
	}
	w.sb.WriteString(s)
	rs := []rune(s)
	w.last = rs[len(rs)-1]
}

func (w *writer) raw(s string) {
	w.sb.WriteString(s)
	if s != "" {
		rs := []rune(s)
		w.last = rs[len(rs)-1]
	}
}

func varName(i int64) string {
	s := string(rune('A' + i%26))
	if i >= 26 {
		s += strconv.FormatInt(i/26, 10)
	}
	return s
}

func (w *writer) write(t Term, max int) {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		w.emit("_" + strconv.FormatInt(x.id, 10))
	case Int:
		w.emit(strconv.FormatInt(int64(x), 10))
	case *big.Int:
		w.emit(x.String())
	case Float:
		w.emit(formatFloat(float64(x)))
	case *Atom:
		s := w.atomText(x)
		if e := w.ops[x.Name]; e != nil && max < 1200 && (e.prefix != nil || e.infix != nil) {
			p := 0
			for _, d := range []*opDef{e.prefix, e.infix, e.postfix} {
				if d != nil && d.pri > p {
					p = d.pri
				}
			}
			if p > max {
				w.emit("(")
				w.raw(s)
				w.raw(")")
				return
			}
		}
		w.emit(s)
	case *Compound:
		w.writeCompound(x, max)
	default:
		w.emit("?")
	}
}

func (w *writer) writeCompound(c *Compound, max int) {
	name := c.Fn.Name
	n := len(c.Args)
	if c.Fn == atDot && n == 2 {
		w.writeList(c)
		return
	}
	if w.o.numberVars && c.Fn == atVarFn && n == 1 {
		if i, ok := deref(c.Args[0]).(Int); ok && i >= 0 {
			w.emit(varName(int64(i)))
			return
		}
	}
	if c.Fn == atCurly && n == 1 && !w.o.ignoreOps {
		w.emit("{")
		w.write(c.Args[0], 1200)
		w.raw("}")
		return
	}
	if !w.o.ignoreOps {
		if e := w.ops[name]; e != nil {
			if n == 2 && e.infix != nil {
				d := e.infix
				open := d.pri > max
				if open {
					w.emit("(")
				}
				w.write(c.Args[0], d.leftMax())
				switch {
				case name == ",":
					w.raw(",")
				case isAlnumAtom(name) || name == "->" || name == ":-" || name == "-->" || name == "*->":
					if name == "->" || name == "*->" || name == ":-" || name == "-->" {
						w.raw(name)
					} else {
						w.raw(" ")
						w.raw(w.atomText(c.Fn))
						w.raw(" ")
					}
				default:
					w.emit(w.atomText(c.Fn))
				}
				w.write(c.Args[1], d.rightMax())
				if open {
					w.raw(")")
				}
				return
			}
			if n == 1 && e.prefix != nil && name != "-" && name != "+" || n == 1 && e.prefix != nil && (name == "-" || name == "+") {
				d := e.prefix
				open := d.pri > max
				if open {
					w.emit("(")
				}
				w.emit(w.atomText(c.Fn))
				arg := deref(c.Args[0])
				if isNumber(arg) && (name == "-" || name == "+") {
					w.raw(" ")
				} else if isAlnumAtom(name) {
					w.raw(" ")
				} else if a, ok := arg.(*Atom); ok && w.ops[a.Name] != nil {
					w.raw(" ")
				}
				w.write(arg, d.rightMax())
				if open {
					w.raw(")")
				}
				return
			}
			if n == 1 && e.postfix != nil {
				d := e.postfix
				open := d.pri > max
				if open {
					w.emit("(")
				}
				w.write(c.Args[0], d.leftMax())
				w.emit(w.atomText(c.Fn))
				if open {
					w.raw(")")
				}
				return
			}
		}
	}
	w.emit(w.atomText(c.Fn))
	w.raw("(")
	for i, a := range c.Args {
		if i > 0 {
			w.raw(",")
		}
		w.writeArg(a)
	}
	w.raw(")")
}

func (w *writer) writeArg(a Term) {
	if at, ok := deref(a).(*Atom); ok {
		w.emit(w.atomText(at))
		return
	}
	w.write(a, 999)
}

func isAlnumAtom(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if !isAlnum(r) {
			return false
		}
	}
	return true
}

func (w *writer) writeList(c *Compound) {
	w.emit("[")
	var t Term = c
	first := true
	for {
		t = deref(t)
		if cc, ok := isCons(t); ok {
			if !first {
				w.raw(",")
			}
			first = false
			w.writeArg(cc.Args[0])
			t = cc.Args[1]
			continue
		}
		if t != Term(atNil) {
			w.raw("|")
			w.write(t, 999)
		}
		break
	}
	w.raw("]")
}

// ---------- portray_clause / listing ----------

func (m *Machine) portrayClause(t Term) string {
	t = m.copyTerm(t, map[*Var]Term{})
	var vs []*Var
	termVars(t, map[*Var]bool{}, &vs)
	for i, v := range vs {
		v.ref = &Compound{Fn: atVarFn, Args: []Term{Int(i)}}
	}
	o := writeOpts{quoted: true, numberVars: true}
	pc := func(t Term, max int) string {
		w := &writer{o: o, ops: m.ops}
		w.write(t, max)
		return w.sb.String()
	}
	t = deref(t)
	if c, ok := t.(*Compound); ok && c.Fn == atNeck && len(c.Args) == 2 {
		body := deref(c.Args[1])
		if body == Term(atTrue) {
			return pc(c.Args[0], 999) + ".\n"
		}
		return pc(c.Args[0], 999) + " :-\n" + m.portrayBody(body, 1, 1200, pc) + ".\n"
	}
	if c, ok := t.(*Compound); ok && c.Fn == atNeck && len(c.Args) == 1 {
		return ":- " + pc(c.Args[0], 1199) + ".\n"
	}
	return pc(t, 999) + ".\n"
}

func (m *Machine) portrayBody(t Term, depth int, max int, pc func(Term, int) string) string {
	ind := strings.Repeat("    ", depth)
	t = deref(t)
	if c, ok := t.(*Compound); ok && len(c.Args) == 2 {
		switch c.Fn {
		case atComma:
			return m.portrayBody(c.Args[0], depth, 999, pc) + ",\n" + m.portrayBody(c.Args[1], depth, 1000, pc)
		case atSemi, atArrow, atSoft:
			return ind + "(   " + m.portrayDisj(t, depth, pc) + "\n" + ind + ")"
		}
	}
	return ind + pc(t, 999)
}

func (m *Machine) portrayDisj(t Term, depth int, pc func(Term, int) string) string {
	ind := strings.Repeat("    ", depth)
	t = deref(t)
	if c, ok := t.(*Compound); ok && len(c.Args) == 2 {
		switch c.Fn {
		case atSemi:
			return m.portrayDisj(c.Args[0], depth, pc) + "\n" + ind + ";   " + m.portrayDisj(c.Args[1], depth, pc)
		case atArrow, atSoft:
			op := "->  "
			if c.Fn == atSoft {
				op = "*-> "
			}
			return m.portrayInner(c.Args[0], depth, pc) + "\n" + ind + op + m.portrayInner(c.Args[1], depth, pc)
		}
	}
	return m.portrayInner(t, depth, pc)
}

func (m *Machine) portrayInner(t Term, depth int, pc func(Term, int) string) string {
	ind := strings.Repeat("    ", depth)
	t = deref(t)
	if c, ok := t.(*Compound); ok && len(c.Args) == 2 {
		switch c.Fn {
		case atComma:
			return m.portrayInner(c.Args[0], depth, pc) + ",\n" + ind + "    " + m.portrayInner(c.Args[1], depth, pc)
		case atSemi, atArrow, atSoft:
			return "(   " + m.portrayDisj(t, depth+1, pc) + "\n" + ind + "    )"
		}
	}
	return pc(t, 999)
}
