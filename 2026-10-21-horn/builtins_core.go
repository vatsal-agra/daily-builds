package main

import (
	"math/big"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
)

func itoa(i int) string { return strconv.Itoa(i) }

func (m *Machine) det(name string, arity int, f DetFn) {
	p := m.lookupPred(mkAtom(name), arity, true)
	p.det = f
	p.defined = true
}
func (m *Machine) nondet(name string, arity int, f NondetFn) {
	p := m.lookupPred(mkAtom(name), arity, true)
	p.nondet = f
	p.defined = true
}
func (m *Machine) ctl(name string, arity int, id int) {
	p := m.lookupPred(mkAtom(name), arity, true)
	p.ctl = id
	p.defined = true
}

// tryUnify tests unifiability and always undoes the bindings.
func (m *Machine) tryUnify(a, b Term) bool {
	oldhb := m.hb
	m.hb = 1 << 62
	mark := len(m.trail)
	ok := m.unify(a, b)
	m.undoTrail(mark)
	m.hb = oldhb
	return ok
}

// ---------- text helpers ----------

func textOf(t Term) (string, error) {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		return "", instErr()
	case *Atom:
		return x.Name, nil
	case Int, Float, *big.Int:
		return formatTerm(x, false), nil
	case *Compound:
		items, tail := listToSlice(x)
		if tail != Term(atNil) {
			if _, ok := tail.(*Var); ok {
				return "", instErr()
			}
			return "", typeErr("text", t)
		}
		var sb strings.Builder
		for _, it := range items {
			it = deref(it)
			switch c := it.(type) {
			case Int:
				sb.WriteRune(rune(c))
			case *Atom:
				if len([]rune(c.Name)) != 1 {
					return "", typeErr("text", t)
				}
				sb.WriteString(c.Name)
			case *Var:
				return "", instErr()
			default:
				return "", typeErr("text", t)
			}
		}
		return sb.String(), nil
	}
	return "", typeErr("text", t)
}

func codesOf(s string) Term {
	var items []Term
	for _, r := range s {
		items = append(items, Int(r))
	}
	return mkList(items, atNil)
}
func charsOf(s string) Term {
	var items []Term
	for _, r := range s {
		items = append(items, mkAtom(string(r)))
	}
	return mkList(items, atNil)
}

func getInt(t Term) (int, error) {
	t = deref(t)
	switch x := t.(type) {
	case Int:
		return int(x), nil
	case *Var:
		return 0, instErr()
	case *big.Int:
		return 0, reprErr("max_integer")
	}
	return 0, typeErr("integer", t)
}

func getAtom(t Term) (*Atom, error) {
	t = deref(t)
	switch x := t.(type) {
	case *Atom:
		return x, nil
	case *Var:
		return nil, instErr()
	}
	return nil, typeErr("atom", t)
}

func getList(t Term) ([]Term, error) {
	items, tail := listToSlice(t)
	if tail == Term(atNil) {
		return items, nil
	}
	if _, ok := tail.(*Var); ok {
		return nil, instErr()
	}
	return nil, typeErr("list", t)
}

// parseNumber parses Prolog number syntax from text.
func (m *Machine) parseNumber(s string) (Term, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, false
	}
	neg := false
	body := s
	if body[0] == '-' {
		neg = true
		body = body[1:]
	} else if body[0] == '+' {
		body = body[1:]
	}
	if body == "" || !isDigit(rune(body[0])) {
		switch body {
		case "inf", "infinite":
			if neg {
				return Float(-posInf), true
			}
			return Float(posInf), true
		case "nan":
			return Float(nanVal), true
		}
		return nil, false
	}
	rd := newReader(m, strings.NewReader(body+" ."))
	tok, err := rd.nextToken()
	if err != nil || tok.kind != tNum {
		return nil, false
	}
	t2, err := rd.nextToken()
	if err != nil || t2.kind != tEnd {
		return nil, false
	}
	v := tok.num
	if neg {
		switch x := v.(type) {
		case Int:
			v = -x
		case Float:
			v = -x
		case *big.Int:
			v = normBig(new(big.Int).Neg(x))
		}
	}
	return v, true
}

func (m *Machine) parseTermFromText(s string) (Term, *Reader, error) {
	rd := newReader(m, strings.NewReader(s+"\n ."))
	t, err := rd.ReadTerm()
	if err != nil {
		if se, ok := err.(*SyntaxError); ok {
			return nil, nil, syntaxErr(se.Msg)
		}
		return nil, nil, syntaxErr("unexpected end of input")
	}
	return t, rd, nil
}

func (m *Machine) installBuiltins() {
	m.ctl(",", 2, ctlConj)
	m.ctl("true", 0, ctlTrue)
	m.ctl("otherwise", 0, ctlTrue)
	m.ctl("fail", 0, ctlFail)
	m.ctl("false", 0, ctlFail)
	m.ctl("!", 0, ctlCut)
	m.ctl(";", 2, ctlDisj)
	m.ctl("|", 2, ctlDisj)
	m.ctl("->", 2, ctlIf)
	m.ctl("*->", 2, ctlSoft)
	m.ctl("\\+", 1, ctlNot)
	m.ctl("not", 1, ctlNot)
	for i := 1; i <= 8; i++ {
		m.ctl("call", i, ctlCall)
	}
	m.ctl("catch", 3, ctlCatch)
	m.ctl("once", 1, ctlOnce)
	m.ctl("ignore", 1, ctlIgnore)
	m.ctl("forall", 2, ctlForall)
	m.ctl(":", 2, ctlColon)

	m.installTypeChecks()
	m.installTermBuiltins()
	m.installAtomBuiltins()
	m.installDBBuiltins()
	m.installSolutionBuiltins()
	m.installIOBuiltins()
	m.installSystemBuiltins()
}

func (m *Machine) installTypeChecks() {
	tc := func(name string, f func(Term) bool) {
		m.det(name, 1, func(m *Machine, a []Term) (bool, error) { return f(deref(a[0])), nil })
	}
	tc("var", func(t Term) bool { _, ok := t.(*Var); return ok })
	tc("nonvar", func(t Term) bool { _, ok := t.(*Var); return !ok })
	tc("atom", func(t Term) bool { _, ok := t.(*Atom); return ok })
	tc("number", isNumber)
	tc("integer", isInt)
	tc("float", func(t Term) bool { _, ok := t.(Float); return ok })
	tc("atomic", isAtomic)
	tc("compound", func(t Term) bool { _, ok := t.(*Compound); return ok })
	tc("callable", isCallable)
	tc("is_list", func(t Term) bool { _, tail := listToSlice(t); return tail == Term(atNil) })
	tc("ground", isGround)
	tc("string", func(t Term) bool { return false })
	tc("is_dict", func(t Term) bool { return false })
	tc("is_stream", func(t Term) bool { _, err := gm.getStream(t); return err == nil })
	tc("is_assoc", func(t Term) bool {
		if a, ok := t.(*Atom); ok {
			return a.Name == "t"
		}
		c, ok := t.(*Compound)
		return ok && c.Fn.Name == "t"
	})

	m.det("=", 2, func(m *Machine, a []Term) (bool, error) { return m.unify(a[0], a[1]), nil })
	m.det("\\=", 2, func(m *Machine, a []Term) (bool, error) { return !m.tryUnify(a[0], a[1]), nil })
	m.det("==", 2, func(m *Machine, a []Term) (bool, error) { return compareTerms(a[0], a[1]) == 0, nil })
	m.det("\\==", 2, func(m *Machine, a []Term) (bool, error) { return compareTerms(a[0], a[1]) != 0, nil })
	m.det("@<", 2, func(m *Machine, a []Term) (bool, error) { return compareTerms(a[0], a[1]) < 0, nil })
	m.det("@>", 2, func(m *Machine, a []Term) (bool, error) { return compareTerms(a[0], a[1]) > 0, nil })
	m.det("@=<", 2, func(m *Machine, a []Term) (bool, error) { return compareTerms(a[0], a[1]) <= 0, nil })
	m.det("@>=", 2, func(m *Machine, a []Term) (bool, error) { return compareTerms(a[0], a[1]) >= 0, nil })
	m.det("compare", 3, func(m *Machine, a []Term) (bool, error) {
		if o := deref(a[0]); o != nil {
			if _, isv := o.(*Var); !isv {
				at, ok := o.(*Atom)
				if !ok {
					return false, typeErr("atom", o)
				}
				if at.Name != "<" && at.Name != ">" && at.Name != "=" {
					return false, domErr("order", o)
				}
			}
		}
		c := compareTerms(a[1], a[2])
		s := "="
		if c < 0 {
			s = "<"
		} else if c > 0 {
			s = ">"
		}
		return m.unify(a[0], mkAtom(s)), nil
	})
	m.det("unify_with_occurs_check", 2, func(m *Machine, a []Term) (bool, error) {
		old := m.occursCheck
		m.occursCheck = true
		ok := m.unify(a[0], a[1])
		m.occursCheck = old
		return ok, nil
	})
	m.det("=@=", 2, func(m *Machine, a []Term) (bool, error) { return variant(a[0], a[1]), nil })
	m.det("\\=@=", 2, func(m *Machine, a []Term) (bool, error) { return !variant(a[0], a[1]), nil })
	m.det("?=", 2, func(m *Machine, a []Term) (bool, error) {
		return compareTerms(a[0], a[1]) == 0 || !m.tryUnify(a[0], a[1]), nil
	})

	cmp := func(name string, f func(c int) bool) {
		m.det(name, 2, func(m *Machine, a []Term) (bool, error) {
			x, err := m.eval(a[0])
			if err != nil {
				return false, err
			}
			y, err := m.eval(a[1])
			if err != nil {
				return false, err
			}
			if fx, ok := x.(Float); ok && fx != fx {
				return false, nil
			}
			if fy, ok := y.(Float); ok && fy != fy {
				return false, nil
			}
			return f(numCompare(x, y)), nil
		})
	}
	cmp("=:=", func(c int) bool { return c == 0 })
	cmp("=\\=", func(c int) bool { return c != 0 })
	cmp("<", func(c int) bool { return c < 0 })
	cmp(">", func(c int) bool { return c > 0 })
	cmp("=<", func(c int) bool { return c <= 0 })
	cmp(">=", func(c int) bool { return c >= 0 })
	m.det("is", 2, func(m *Machine, a []Term) (bool, error) {
		v, err := m.eval(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[0], v), nil
	})
	m.det("succ", 2, func(m *Machine, a []Term) (bool, error) {
		x, y := deref(a[0]), deref(a[1])
		if xv, ok := x.(Int); ok {
			if xv < 0 {
				return false, typeErr("not_less_than_zero", x)
			}
			if _, isv := y.(*Var); !isv {
				if _, ok := y.(Int); !ok {
					return false, typeErr("integer", y)
				}
			}
			return m.unify(y, xv+1), nil
		}
		if _, isv := x.(*Var); !isv {
			return false, typeErr("integer", x)
		}
		yv, ok := y.(Int)
		if !ok {
			if _, isv := y.(*Var); isv {
				return false, instErr()
			}
			return false, typeErr("integer", y)
		}
		if yv < 0 {
			return false, typeErr("not_less_than_zero", y)
		}
		if yv == 0 {
			return false, nil
		}
		return m.unify(x, yv-1), nil
	})
	m.det("plus", 3, func(m *Machine, a []Term) (bool, error) {
		x, y, z := deref(a[0]), deref(a[1]), deref(a[2])
		_, xv := x.(*Var)
		_, yv := y.(*Var)
		_, zv := z.(*Var)
		switch {
		case !xv && !yv:
			r, err := m.eval(&Compound{Fn: atPlus, Args: []Term{x, y}})
			if err != nil {
				return false, err
			}
			return m.unify(z, r), nil
		case !xv && !zv:
			r, err := m.eval(&Compound{Fn: atMinus, Args: []Term{z, x}})
			if err != nil {
				return false, err
			}
			return m.unify(y, r), nil
		case !yv && !zv:
			r, err := m.eval(&Compound{Fn: atMinus, Args: []Term{z, y}})
			if err != nil {
				return false, err
			}
			return m.unify(x, r), nil
		}
		return false, instErr()
	})
}

func (m *Machine) installTermBuiltins() {
	m.det("functor", 3, func(m *Machine, a []Term) (bool, error) {
		t := deref(a[0])
		switch x := t.(type) {
		case *Var:
			n := deref(a[1])
			ar, err := getInt(a[2])
			if err != nil {
				return false, err
			}
			if _, isv := n.(*Var); isv {
				return false, instErr()
			}
			if ar < 0 {
				return false, domErr("not_less_than_zero", a[2])
			}
			if ar == 0 {
				if !isAtomic(n) {
					return false, typeErr("atomic", n)
				}
				return m.unify(x, n), nil
			}
			if _, isc := n.(*Compound); isc {
				return false, typeErr("atomic", n)
			}
			at, ok := n.(*Atom)
			if !ok {
				return false, typeErr("atom", n)
			}
			args := make([]Term, ar)
			for i := range args {
				args[i] = m.newVar()
			}
			return m.unify(x, &Compound{Fn: at, Args: args}), nil
		case *Compound:
			return m.unify(a[1], x.Fn) && m.unify(a[2], Int(len(x.Args))), nil
		default:
			return m.unify(a[1], t) && m.unify(a[2], Int(0)), nil
		}
	})
	m.nondet("arg", 3, func(m *Machine, a []Term) (Term, []Term, error) {
		t := deref(a[1])
		c, ok := t.(*Compound)
		if !ok {
			if _, isv := t.(*Var); isv {
				return nil, nil, instErr()
			}
			return nil, nil, typeErr("compound", t)
		}
		n := deref(a[0])
		switch x := n.(type) {
		case Int:
			if x < 1 || int(x) > len(c.Args) {
				return nil, nil, nil
			}
			return a[2], []Term{c.Args[x-1]}, nil
		case *Var:
			var sols []Term
			for i, arg := range c.Args {
				sols = append(sols, mk("-", Int(i+1), arg))
			}
			return mk("-", x, a[2]), sols, nil
		}
		return nil, nil, typeErr("integer", n)
	})
	m.det("=..", 2, func(m *Machine, a []Term) (bool, error) {
		t := deref(a[0])
		switch x := t.(type) {
		case *Var:
			items, tail := listToSlice(a[1])
			if _, isv := tail.(*Var); isv {
				return false, instErr()
			}
			if tail != Term(atNil) {
				return false, typeErr("list", a[1])
			}
			if len(items) == 0 {
				return false, domErr("non_empty_list", atNil)
			}
			h := deref(items[0])
			if len(items) == 1 {
				if _, isv := h.(*Var); isv {
					return false, instErr()
				}
				if _, isc := h.(*Compound); isc {
					return false, typeErr("atomic", h)
				}
				return m.unify(x, h), nil
			}
			at, ok := h.(*Atom)
			if !ok {
				if _, isv := h.(*Var); isv {
					return false, instErr()
				}
				return false, typeErr("atom", h)
			}
			return m.unify(x, &Compound{Fn: at, Args: append([]Term(nil), items[1:]...)}), nil
		case *Compound:
			return m.unify(a[1], cons(x.Fn, mkList(x.Args, atNil))), nil
		default:
			return m.unify(a[1], cons(t, atNil)), nil
		}
	})
	m.det("copy_term", 2, func(m *Machine, a []Term) (bool, error) {
		return m.unify(a[1], m.copyTerm(a[0], map[*Var]Term{})), nil
	})
	m.det("term_variables", 2, func(m *Machine, a []Term) (bool, error) {
		var vs []*Var
		termVars(a[0], map[*Var]bool{}, &vs)
		items := make([]Term, len(vs))
		for i, v := range vs {
			items[i] = v
		}
		return m.unify(a[1], mkList(items, atNil)), nil
	})
	m.det("setarg", 3, func(m *Machine, a []Term) (bool, error) {
		n, err := getInt(a[0])
		if err != nil {
			return false, err
		}
		c, ok := deref(a[1]).(*Compound)
		if !ok {
			return false, typeErr("compound", a[1])
		}
		if n < 1 || n > len(c.Args) {
			return false, nil
		}
		old := c.Args[n-1]
		c.Args[n-1] = deref(a[2])
		m.pushUndo(func() { c.Args[n-1] = old })
		return true, nil
	})
	m.det("nb_setarg", 3, func(m *Machine, a []Term) (bool, error) {
		n, err := getInt(a[0])
		if err != nil {
			return false, err
		}
		c, ok := deref(a[1]).(*Compound)
		if !ok {
			return false, typeErr("compound", a[1])
		}
		if n < 1 || n > len(c.Args) {
			return false, nil
		}
		c.Args[n-1] = m.copyTerm(a[2], map[*Var]Term{})
		return true, nil
	})
	m.det("$skip_list", 3, func(m *Machine, a []Term) (bool, error) {
		items, tail := listToSlice(a[0])
		return m.unify(a[1], Int(len(items))) && m.unify(a[2], tail), nil
	})
	m.det("msort", 2, func(m *Machine, a []Term) (bool, error) {
		items, err := getList(a[0])
		if err != nil {
			return false, err
		}
		return m.unify(a[1], mkList(sortTerms(append([]Term(nil), items...), false), atNil)), nil
	})
	m.det("sort", 2, func(m *Machine, a []Term) (bool, error) {
		items, err := getList(a[0])
		if err != nil {
			return false, err
		}
		return m.unify(a[1], mkList(sortTerms(append([]Term(nil), items...), true), atNil)), nil
	})
	m.det("sort", 4, func(m *Machine, a []Term) (bool, error) {
		key, err := getInt(a[0])
		if err != nil {
			return false, err
		}
		ord, err := getAtom(a[1])
		if err != nil {
			return false, err
		}
		items, err := getList(a[2])
		if err != nil {
			return false, err
		}
		items = append([]Term(nil), items...)
		keyOf := func(t Term) (Term, error) {
			if key == 0 {
				return t, nil
			}
			c, ok := deref(t).(*Compound)
			if !ok {
				return nil, typeErr("compound", t)
			}
			if key > len(c.Args) {
				return nil, typeErr("compound", t)
			}
			return c.Args[key-1], nil
		}
		keys := make([]Term, len(items))
		for i, it := range items {
			if keys[i], err = keyOf(it); err != nil {
				return false, err
			}
		}
		idx := make([]int, len(items))
		for i := range idx {
			idx[i] = i
		}
		var less func(i, j int) bool
		switch ord.Name {
		case "@<", "@=<":
			less = func(i, j int) bool { return compareTerms(keys[idx[i]], keys[idx[j]]) < 0 }
		case "@>", "@>=":
			less = func(i, j int) bool { return compareTerms(keys[idx[i]], keys[idx[j]]) > 0 }
		default:
			return false, domErr("order", ord)
		}
		sort.SliceStable(idx, less)
		var out []Term
		for n, i := range idx {
			if (ord.Name == "@<" || ord.Name == "@>") && n > 0 && compareTerms(keys[idx[n-1]], keys[i]) == 0 {
				continue
			}
			out = append(out, items[i])
		}
		return m.unify(a[3], mkList(out, atNil)), nil
	})
	m.det("keysort", 2, func(m *Machine, a []Term) (bool, error) {
		items, err := getList(a[0])
		if err != nil {
			return false, err
		}
		keys := make([]Term, len(items))
		for i, it := range items {
			it = deref(it)
			c, ok := it.(*Compound)
			if !ok || c.Fn != atMinus || len(c.Args) != 2 {
				if _, isv := it.(*Var); isv {
					return false, instErr()
				}
				return false, typeErr("pair", it)
			}
			keys[i] = c.Args[0]
		}
		idx := make([]int, len(items))
		for i := range idx {
			idx[i] = i
		}
		sort.SliceStable(idx, func(i, j int) bool { return compareTerms(keys[idx[i]], keys[idx[j]]) < 0 })
		out := make([]Term, len(items))
		for n, i := range idx {
			out[n] = items[i]
		}
		return m.unify(a[1], mkList(out, atNil)), nil
	})
}

func (m *Machine) installAtomBuiltins() {
	conv := func(name string, toList func(string) Term, makeAtom bool) {
		m.det(name, 2, func(m *Machine, a []Term) (bool, error) {
			x := deref(a[0])
			if _, isv := x.(*Var); !isv {
				s, err := textOf(x)
				if err != nil {
					return false, err
				}
				if _, isc := x.(*Compound); isc {
					return false, typeErr("atom", x)
				}
				return m.unify(a[1], toList(s)), nil
			}
			s, err := textOf(a[1])
			if err != nil {
				return false, err
			}
			if makeAtom {
				return m.unify(x, mkAtom(s)), nil
			}
			n, ok := m.parseNumber(s)
			if !ok {
				return false, syntaxErr("illegal_number")
			}
			return m.unify(x, n), nil
		})
	}
	conv("atom_codes", codesOf, true)
	conv("atom_chars", charsOf, true)
	conv("number_codes", codesOf, false)
	conv("number_chars", charsOf, false)
	m.det("char_code", 2, func(m *Machine, a []Term) (bool, error) {
		x := deref(a[0])
		if at, ok := x.(*Atom); ok {
			rs := []rune(at.Name)
			if len(rs) != 1 {
				return false, typeErr("character", x)
			}
			return m.unify(a[1], Int(rs[0])), nil
		}
		c, err := getInt(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(x, mkAtom(string(rune(c)))), nil
	})
	m.det("atom_length", 2, func(m *Machine, a []Term) (bool, error) {
		x := deref(a[0])
		if _, isc := x.(*Compound); isc {
			return false, typeErr("atom", x)
		}
		s, err := textOf(x)
		if err != nil {
			return false, err
		}
		if l := deref(a[1]); l != nil {
			if _, isv := l.(*Var); !isv {
				n, ok := l.(Int)
				if !ok {
					return false, typeErr("integer", l)
				}
				if n < 0 {
					return false, domErr("not_less_than_zero", l)
				}
			}
		}
		return m.unify(a[1], Int(len([]rune(s)))), nil
	})
	m.det("string_length", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		return m.unify(a[1], Int(len([]rune(s)))), nil
	})
	m.det("atom_number", 2, func(m *Machine, a []Term) (bool, error) {
		x := deref(a[0])
		if _, isv := x.(*Var); isv {
			n := deref(a[1])
			if _, isv := n.(*Var); isv {
				return false, instErr()
			}
			if !isNumber(n) {
				return false, typeErr("number", n)
			}
			return m.unify(x, mkAtom(formatTerm(n, false))), nil
		}
		s, err := textOf(x)
		if err != nil {
			return false, err
		}
		n, ok := m.parseNumber(s)
		if !ok {
			return false, nil
		}
		return m.unify(a[1], n), nil
	})
	m.nondet("atom_concat", 3, func(m *Machine, a []Term) (Term, []Term, error) {
		x, y := deref(a[0]), deref(a[1])
		_, xv := x.(*Var)
		_, yv := y.(*Var)
		if !xv && !yv {
			s1, err := textOf(x)
			if err != nil {
				return nil, nil, err
			}
			s2, err := textOf(y)
			if err != nil {
				return nil, nil, err
			}
			return a[2], []Term{mkAtom(s1 + s2)}, nil
		}
		z := deref(a[2])
		if _, zv := z.(*Var); zv {
			return nil, nil, instErr()
		}
		s, err := textOf(z)
		if err != nil {
			return nil, nil, err
		}
		rs := []rune(s)
		var sols []Term
		for i := 0; i <= len(rs); i++ {
			sols = append(sols, mk("-", mkAtom(string(rs[:i])), mkAtom(string(rs[i:]))))
		}
		return mk("-", x, y), sols, nil
	})
	subAtom := func(m *Machine, a []Term) (Term, []Term, error) {
		s, err := textOf(a[0])
		if err != nil {
			return nil, nil, err
		}
		rs := []rune(s)
		n := len(rs)
		sub := deref(a[4])
		pat := mk("s", a[1], a[2], a[3], a[4])
		mkSol := func(b, l int) Term {
			return mk("s", Int(b), Int(l), Int(n-b-l), mkAtom(string(rs[b:b+l])))
		}
		var sols []Term
		if _, isv := sub.(*Var); !isv {
			ss, err := textOf(sub)
			if err != nil {
				return nil, nil, err
			}
			sr := []rune(ss)
			for b := 0; b+len(sr) <= n; b++ {
				if string(rs[b:b+len(sr)]) == ss {
					sols = append(sols, mkSol(b, len(sr)))
				}
			}
			return pat, sols, nil
		}
		B, L, A := deref(a[1]), deref(a[2]), deref(a[3])
		bi, bok := B.(Int)
		li, lok := L.(Int)
		ai, aok := A.(Int)
		switch {
		case bok && lok:
			if bi >= 0 && li >= 0 && int(bi+li) <= n {
				sols = append(sols, mkSol(int(bi), int(li)))
			}
		case bok && aok:
			if l := n - int(bi) - int(ai); bi >= 0 && ai >= 0 && l >= 0 {
				sols = append(sols, mkSol(int(bi), l))
			}
		case lok && aok:
			if b := n - int(li) - int(ai); li >= 0 && ai >= 0 && b >= 0 {
				sols = append(sols, mkSol(b, int(li)))
			}
		case bok:
			for l := 0; int(bi) >= 0 && int(bi)+l <= n; l++ {
				sols = append(sols, mkSol(int(bi), l))
			}
		case lok:
			for b := 0; int(li) >= 0 && b+int(li) <= n; b++ {
				sols = append(sols, mkSol(b, int(li)))
			}
		case aok:
			for b := 0; n-int(ai)-b >= 0 && int(ai) >= 0; b++ {
				sols = append(sols, mkSol(b, n-int(ai)-b))
			}
		default:
			for b := 0; b <= n; b++ {
				for l := 0; b+l <= n; l++ {
					sols = append(sols, mkSol(b, l))
				}
			}
		}
		return pat, sols, nil
	}
	m.nondet("sub_atom", 5, subAtom)
	m.nondet("sub_string", 5, subAtom)
	caseConv := func(name string, f func(string) string) {
		m.det(name, 2, func(m *Machine, a []Term) (bool, error) {
			s, err := textOf(a[0])
			if err != nil {
				return false, err
			}
			return m.unify(a[1], mkAtom(f(s))), nil
		})
	}
	caseConv("upcase_atom", strings.ToUpper)
	caseConv("downcase_atom", strings.ToLower)
	caseConv("string_upper", strings.ToUpper)
	caseConv("string_lower", strings.ToLower)
	m.det("term_to_atom", 2, func(m *Machine, a []Term) (bool, error) {
		t := deref(a[0])
		if _, isv := t.(*Var); !isv {
			return m.unify(a[1], mkAtom(formatTermOpts(t, writeOpts{quoted: true, numberVars: true}))), nil
		}
		s, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		pt, _, err := m.parseTermFromText(s)
		if err != nil {
			return false, err
		}
		return m.unify(t, pt), nil
	})
	m.det("term_string", 2, func(m *Machine, a []Term) (bool, error) {
		t := deref(a[0])
		if _, isv := t.(*Var); !isv {
			return m.unify(a[1], mkAtom(formatTermOpts(t, writeOpts{quoted: true, numberVars: true}))), nil
		}
		s, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		pt, _, err := m.parseTermFromText(s)
		if err != nil {
			return false, err
		}
		return m.unify(t, pt), nil
	})
	m.det("atom_to_term", 3, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		pt, rd, err := m.parseTermFromText(s)
		if err != nil {
			return false, err
		}
		var bs []Term
		for i, n := range rd.Names {
			bs = append(bs, mk("=", mkAtom(n), rd.Vars[i]))
		}
		return m.unify(a[1], pt) && m.unify(a[2], mkList(bs, atNil)), nil
	})
	m.det("sformat", 3, func(m *Machine, a []Term) (bool, error) { return false, nil })
	m.det("atomic_list_concat", 2, func(m *Machine, a []Term) (bool, error) {
		return m.atomicListConcat(a[0], atEmpty, a[1])
	})
	m.det("atomic_list_concat", 3, func(m *Machine, a []Term) (bool, error) {
		return m.atomicListConcat(a[0], deref(a[1]), a[2])
	})
	m.det("split_string", 4, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		sep, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		pad, err := textOf(a[2])
		if err != nil {
			return false, err
		}
		var parts []string
		if sep == "" {
			parts = []string{s}
		} else {
			cur := ""
			for _, r := range s {
				if strings.ContainsRune(sep, r) {
					parts = append(parts, cur)
					cur = ""
				} else {
					cur += string(r)
				}
			}
			parts = append(parts, cur)
		}
		var items []Term
		for _, p := range parts {
			items = append(items, mkAtom(strings.Trim(p, pad)))
		}
		return m.unify(a[3], mkList(items, atNil)), nil
	})
	m.det("string_concat", 3, func(m *Machine, a []Term) (bool, error) {
		s1, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		s2, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[2], mkAtom(s1+s2)), nil
	})
	m.det("string_chars", 2, func(m *Machine, a []Term) (bool, error) {
		if _, isv := deref(a[0]).(*Var); !isv {
			s, err := textOf(a[0])
			if err != nil {
				return false, err
			}
			return m.unify(a[1], charsOf(s)), nil
		}
		s, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[0], mkAtom(s)), nil
	})
	m.det("string_codes", 2, func(m *Machine, a []Term) (bool, error) {
		if _, isv := deref(a[0]).(*Var); !isv {
			s, err := textOf(a[0])
			if err != nil {
				return false, err
			}
			return m.unify(a[1], codesOf(s)), nil
		}
		s, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[0], mkAtom(s)), nil
	})
	m.det("string_to_atom", 2, func(m *Machine, a []Term) (bool, error) {
		if _, isv := deref(a[0]).(*Var); !isv {
			s, err := textOf(a[0])
			if err != nil {
				return false, err
			}
			return m.unify(a[1], mkAtom(s)), nil
		}
		s, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[0], mkAtom(s)), nil
	})
	m.det("number_string", 2, func(m *Machine, a []Term) (bool, error) {
		if _, isv := deref(a[1]).(*Var); !isv {
			s, err := textOf(a[1])
			if err != nil {
				return false, err
			}
			n, ok := m.parseNumber(s)
			return ok && m.unify(a[0], n), nil
		}
		n := deref(a[0])
		if !isNumber(n) {
			return false, instErr()
		}
		return m.unify(a[1], mkAtom(formatTerm(n, false))), nil
	})
	m.det("text_concat", 3, func(m *Machine, a []Term) (bool, error) {
		s1, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		s2, err := textOf(a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[2], mkAtom(s1+s2)), nil
	})
	m.det("char_type", 2, func(m *Machine, a []Term) (bool, error) { return m.charType(a, false) })
	m.det("code_type", 2, func(m *Machine, a []Term) (bool, error) { return m.charType(a, true) })
	m.det("numbervars", 3, func(m *Machine, a []Term) (bool, error) {
		start, err := getInt(a[1])
		if err != nil {
			return false, err
		}
		var vs []*Var
		termVars(a[0], map[*Var]bool{}, &vs)
		for _, v := range vs {
			m.bind(v, &Compound{Fn: atVarFn, Args: []Term{Int(start)}})
			start++
		}
		return m.unify(a[2], Int(start)), nil
	})
}

func (m *Machine) charType(a []Term, code bool) (bool, error) {
	c := deref(a[0])
	var r rune
	switch x := c.(type) {
	case *Atom:
		rs := []rune(x.Name)
		if len(rs) != 1 {
			return false, typeErr("character", c)
		}
		r = rs[0]
	case Int:
		r = rune(x)
	case *Var:
		return false, instErr()
	default:
		return false, typeErr("character", c)
	}
	mkc := func(r rune) Term {
		if code {
			return Int(r)
		}
		return mkAtom(string(r))
	}
	t := deref(a[1])
	switch x := t.(type) {
	case *Atom:
		switch x.Name {
		case "alpha":
			return unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_', nil
		case "alnum":
			return unicode.IsLetter(r) || unicode.IsDigit(r), nil
		case "csym":
			return isAlnum(r), nil
		case "csymf":
			return unicode.IsLetter(r) || r == '_', nil
		case "digit":
			return unicode.IsDigit(r), nil
		case "space", "white":
			return unicode.IsSpace(r), nil
		case "upper":
			return unicode.IsUpper(r), nil
		case "lower":
			return unicode.IsLower(r), nil
		case "punct":
			return unicode.IsPunct(r) || unicode.IsSymbol(r), nil
		case "graph":
			return unicode.IsGraphic(r) && !unicode.IsSpace(r), nil
		case "print":
			return unicode.IsPrint(r), nil
		case "ascii":
			return r < 128, nil
		case "end_of_line":
			return r == '\n' || r == '\r', nil
		case "newline":
			return r == '\n', nil
		}
		return false, domErr("char_type", t)
	case *Compound:
		if len(x.Args) != 1 {
			return false, domErr("char_type", t)
		}
		switch x.Fn.Name {
		case "digit":
			if r >= '0' && r <= '9' {
				return m.unify(x.Args[0], Int(r-'0')), nil
			}
			return false, nil
		case "to_lower":
			return m.unify(x.Args[0], mkc(unicode.ToLower(r))), nil
		case "to_upper":
			return m.unify(x.Args[0], mkc(unicode.ToUpper(r))), nil
		case "upper":
			if unicode.IsUpper(r) {
				return m.unify(x.Args[0], mkc(unicode.ToLower(r))), nil
			}
			return false, nil
		case "lower":
			if unicode.IsLower(r) {
				return m.unify(x.Args[0], mkc(unicode.ToUpper(r))), nil
			}
			return false, nil
		}
	}
	return false, domErr("char_type", t)
}

func (m *Machine) atomicListConcat(l Term, sep Term, res Term) (bool, error) {
	sepS, err := textOf(sep)
	if err != nil {
		return false, err
	}
	items, tail := listToSlice(l)
	ground := tail == Term(atNil)
	if ground {
		for _, it := range items {
			if _, isv := deref(it).(*Var); isv {
				ground = false
				break
			}
		}
	}
	if ground {
		parts := make([]string, len(items))
		for i, it := range items {
			if !isAtomic(deref(it)) {
				return false, typeErr("atomic", it)
			}
			s, err := textOf(it)
			if err != nil {
				return false, err
			}
			parts[i] = s
		}
		return m.unify(res, mkAtom(strings.Join(parts, sepS))), nil
	}
	r := deref(res)
	if _, isv := r.(*Var); isv {
		return false, instErr()
	}
	if sepS == "" {
		return false, domErr("non_empty_atom", sep)
	}
	s, err := textOf(r)
	if err != nil {
		return false, err
	}
	var out []Term
	for _, p := range strings.Split(s, sepS) {
		out = append(out, mkAtom(p))
	}
	return m.unify(l, mkList(out, atNil)), nil
}

var _ = time.Now
