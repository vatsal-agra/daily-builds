package main

import "strings"

func (m *Machine) predOfHead(h Term, create bool) (*Pred, error) {
	h = deref(h)
	for {
		if c, ok := h.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
			h = deref(c.Args[1])
			continue
		}
		break
	}
	switch x := h.(type) {
	case *Var:
		return nil, instErr()
	case *Atom:
		return m.lookupPred(x, 0, create), nil
	case *Compound:
		return m.lookupPred(x.Fn, len(x.Args), create), nil
	}
	return nil, typeErr("callable", h)
}

func splitClause(t Term) (head, body Term) {
	t = deref(t)
	if c, ok := t.(*Compound); ok && c.Fn == atNeck && len(c.Args) == 2 {
		return deref(c.Args[0]), c.Args[1]
	}
	return t, atTrue
}

func (m *Machine) assertClause(t Term, atEnd bool) error {
	h, _ := splitClause(t)
	p, err := m.predOfHead(h, true)
	if err != nil {
		return err
	}
	if p.det != nil || p.nondet != nil || p.ctl != 0 {
		return permErr("modify", "static_procedure", pi(p.name, p.arity))
	}
	if !p.defined {
		p.dynamic = true
	}
	return m.addClause(t, atEnd, false)
}

// piList walks Name/Arity specs (comma lists, lists).
func (m *Machine) forEachPI(t Term, f func(name *Atom, arity int) error) error {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		return instErr()
	case *Compound:
		if (x.Fn == atComma || x.Fn == atDot) && len(x.Args) == 2 {
			if err := m.forEachPI(x.Args[0], f); err != nil {
				return err
			}
			return m.forEachPI(x.Args[1], f)
		}
		if x.Fn == atColon && len(x.Args) == 2 {
			return m.forEachPI(x.Args[1], f)
		}
		if x.Fn == atSlash && len(x.Args) == 2 {
			n, err := getAtom(x.Args[0])
			if err != nil {
				return err
			}
			ar, err := getInt(x.Args[1])
			if err != nil {
				return err
			}
			return f(n, ar)
		}
	case *Atom:
		if x == atNil {
			return nil
		}
	}
	return typeErr("predicate_indicator", t)
}

func (m *Machine) clauseSolutions(a []Term, withRef bool) (Term, []Term, error) {
	h := deref(a[0])
	p, err := m.predOfHead(h, false)
	if err != nil {
		return nil, nil, err
	}
	if p == nil {
		return nil, nil, nil
	}
	if p.det != nil || p.nondet != nil || p.ctl != 0 {
		return nil, nil, permErr("access", "private_procedure", pi(p.name, p.arity))
	}
	for {
		if c, ok := h.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
			h = deref(c.Args[1])
			continue
		}
		break
	}
	var key argKey
	if hc, ok := h.(*Compound); ok {
		key = keyOf(deref(hc.Args[0]))
	}
	var sols []Term
	for _, cl := range p.clauses {
		if cl.erased || !key.matches(cl.key) {
			continue
		}
		vars := make([]Term, cl.nvars)
		src := cl.src.(*Compound)
		hd := m.rename(src.Args[0], vars)
		bd := m.rename(src.Args[1], vars)
		if withRef {
			sols = append(sols, mk("c", hd, bd, Int(cl.id)))
		} else {
			sols = append(sols, mk("c", hd, bd))
		}
	}
	if withRef {
		return mk("c", h, a[1], a[2]), sols, nil
	}
	return mk("c", h, a[1]), sols, nil
}

func (m *Machine) installDBBuiltins() {
	m.det("assert", 1, func(m *Machine, a []Term) (bool, error) { return true, m.assertClause(a[0], true) })
	m.det("assertz", 1, func(m *Machine, a []Term) (bool, error) { return true, m.assertClause(a[0], true) })
	m.det("asserta", 1, func(m *Machine, a []Term) (bool, error) { return true, m.assertClause(a[0], false) })
	m.nondet("clause", 2, func(m *Machine, a []Term) (Term, []Term, error) {
		if _, isv := deref(a[0]).(*Var); isv {
			return nil, nil, instErr()
		}
		b := deref(a[1])
		if _, isv := b.(*Var); !isv && !isCallable(b) {
			return nil, nil, typeErr("callable", b)
		}
		return m.clauseSolutions(a, false)
	})
	m.nondet("$clause_ref", 3, func(m *Machine, a []Term) (Term, []Term, error) {
		return m.clauseSolutions(a, true)
	})
	m.det("$erase", 1, func(m *Machine, a []Term) (bool, error) {
		id, _ := deref(a[0]).(Int)
		if cl, ok := m.clauseByID[int64(id)]; ok {
			m.eraseClause(cl)
			return true, nil
		}
		return false, nil
	})
	m.det("$clause_head_body", 3, func(m *Machine, a []Term) (bool, error) {
		h, b := splitClause(a[0])
		if _, isv := h.(*Var); isv {
			return false, instErr()
		}
		return m.unify(a[1], h) && m.unify(a[2], b), nil
	})
	m.det("retractall", 1, func(m *Machine, a []Term) (bool, error) {
		p, err := m.predOfHead(a[0], true)
		if err != nil {
			return false, err
		}
		if p.det != nil || p.nondet != nil || p.ctl != 0 {
			return false, permErr("modify", "static_procedure", pi(p.name, p.arity))
		}
		if !p.defined {
			p.dynamic = true
			return true, nil
		}
		h := deref(a[0])
		for {
			if c, ok := h.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
				h = deref(c.Args[1])
				continue
			}
			break
		}
		for _, cl := range append([]*Clause(nil), p.clauses...) {
			vars := make([]Term, cl.nvars)
			hd := m.rename(cl.src.(*Compound).Args[0], vars)
			if m.tryUnify(h, hd) {
				m.eraseClause(cl)
			}
		}
		return true, nil
	})
	m.det("abolish", 1, func(m *Machine, a []Term) (bool, error) {
		return true, m.forEachPI(a[0], func(n *Atom, ar int) error {
			p := m.lookupPred(n, ar, false)
			if p == nil {
				return nil
			}
			if p.det != nil || p.nondet != nil || p.ctl != 0 {
				return permErr("modify", "static_procedure", pi(n, ar))
			}
			for _, c := range p.clauses {
				c.erased = true
				delete(m.clauseByID, c.id)
			}
			p.clauses = nil
			return nil
		})
	})
	decl := func(name string, f func(p *Pred)) {
		m.det(name, 1, func(m *Machine, a []Term) (bool, error) {
			return true, m.forEachPI(a[0], func(n *Atom, ar int) error {
				p := m.lookupPred(n, ar, true)
				if p.det != nil || p.nondet != nil || p.ctl != 0 {
					return permErr("modify", "static_procedure", pi(n, ar))
				}
				f(p)
				return nil
			})
		})
	}
	decl("dynamic", func(p *Pred) {
		if p.library && m.loading {
			p.clauses, p.library = nil, false
		}
		p.dynamic = true
		p.defined = true
	})
	decl("discontiguous", func(p *Pred) { p.discont = true })
	decl("multifile", func(p *Pred) {})
	decl("module_transparent", func(p *Pred) {})
	decl("public", func(p *Pred) {})
	decl("table", func(p *Pred) {})
	decl("thread_local", func(p *Pred) { p.dynamic = true; p.defined = true })
	m.det("meta_predicate", 1, func(m *Machine, a []Term) (bool, error) { return true, nil })
	m.det("garbage_collect", 0, func(m *Machine, a []Term) (bool, error) { return true, nil })

	m.nondet("current_predicate", 1, func(m *Machine, a []Term) (Term, []Term, error) {
		spec := deref(a[0])
		if c, ok := spec.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
			spec = deref(c.Args[1])
		}
		c, ok := spec.(*Compound)
		if !ok || c.Fn != atSlash || len(c.Args) != 2 {
			if _, isv := spec.(*Var); isv {
				return nil, nil, instErr()
			}
			return nil, nil, typeErr("predicate_indicator", spec)
		}
		var sols []Term
		visit := func(at *Atom) {
			for _, p := range at.preds {
				if p != nil && p.det == nil && p.nondet == nil && p.ctl == 0 && !p.library && (len(p.clauses) > 0 || p.dynamic) {
					sols = append(sols, pi(p.name, p.arity))
				}
			}
		}
		if n, ok := deref(c.Args[0]).(*Atom); ok {
			visit(n)
		} else {
			for _, at := range atomTable {
				visit(at)
			}
		}
		return spec, sols, nil
	})
	m.nondet("predicate_property", 2, func(m *Machine, a []Term) (Term, []Term, error) {
		h := deref(a[0])
		if c, ok := h.(*Compound); ok && c.Fn == atColon && len(c.Args) == 2 {
			h = deref(c.Args[1])
		}
		if _, isv := h.(*Var); isv {
			return nil, nil, nil
		}
		p, err := m.predOfHead(h, false)
		if err != nil || p == nil || !(p.defined || p.dynamic) {
			return nil, nil, err
		}
		var sols []Term
		sols = append(sols, mkAtom("defined"), mkAtom("visible"))
		if p.det != nil || p.nondet != nil || p.ctl != 0 {
			sols = append(sols, mkAtom("built_in"), mkAtom("static"))
		} else {
			if p.dynamic {
				sols = append(sols, mkAtom("dynamic"))
			} else {
				sols = append(sols, mkAtom("static"))
			}
			n := 0
			for _, c := range p.clauses {
				if !c.erased {
					n++
				}
			}
			sols = append(sols, mk("number_of_clauses", Int(n)))
		}
		return a[1], sols, nil
	})
	m.det("listing", 1, func(m *Machine, a []Term) (bool, error) {
		return true, m.listing(a[0])
	})
	m.det("portray_clause", 1, func(m *Machine, a []Term) (bool, error) {
		m.write(m.portrayClause(a[0]))
		return true, nil
	})
	m.det("portray_clause", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.getStream(a[0])
		if err != nil {
			return false, err
		}
		m.streamWrite(s, m.portrayClause(a[1]))
		return true, nil
	})
}

func (m *Machine) listing(spec Term) error {
	spec = deref(spec)
	var name *Atom
	arity := -1
	switch x := spec.(type) {
	case *Atom:
		name = x
	case *Compound:
		if x.Fn == atSlash && len(x.Args) == 2 {
			n, err := getAtom(x.Args[0])
			if err != nil {
				return err
			}
			ar, err := getInt(x.Args[1])
			if err != nil {
				return err
			}
			name, arity = n, ar
		} else {
			return typeErr("predicate_indicator", spec)
		}
	default:
		return instErr()
	}
	for ar, p := range name.preds {
		if p == nil || (arity >= 0 && ar != arity) || p.det != nil || p.nondet != nil || p.ctl != 0 {
			continue
		}
		if !p.defined && !p.dynamic {
			continue
		}
		var sb strings.Builder
		if p.dynamic {
			sb.WriteString(":- dynamic " + formatTermOpts(pi(p.name, p.arity), writeOpts{quoted: true}) + ".\n\n")
		}
		for _, c := range p.clauses {
			vars := make([]Term, c.nvars)
			src := c.src.(*Compound)
			t := &Compound{Fn: atNeck, Args: []Term{m.rename(src.Args[0], vars), m.rename(src.Args[1], vars)}}
			sb.WriteString(m.portrayClause(t))
		}
		sb.WriteString("\n")
		m.write(sb.String())
	}
	return nil
}
