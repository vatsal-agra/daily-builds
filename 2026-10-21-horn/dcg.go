package main

// DCG translation (ISO-style, as in SWI-Prolog).

func (m *Machine) dcgRule(rule *Compound) (Term, error) {
	head := deref(rule.Args[0])
	body := rule.Args[1]
	var pushback Term
	if c, ok := head.(*Compound); ok && c.Fn == atComma && len(c.Args) == 2 {
		head = deref(c.Args[0])
		pushback = c.Args[1]
	}
	if _, ok := head.(*Var); ok {
		return nil, instErr()
	}
	if !isCallable(head) {
		return nil, typeErr("callable", head)
	}
	s0, s := m.newVar(), m.newVar()
	var nh Term
	var nb Term
	var err error
	if pushback != nil {
		mid := m.newVar()
		nh, err = dcgExtend(head, s0, s)
		if err != nil {
			return nil, err
		}
		b1, err := m.dcgBody(body, s0, mid)
		if err != nil {
			return nil, err
		}
		b2, err := m.dcgTerminals(pushback, s, mid)
		if err != nil {
			return nil, err
		}
		nb = &Compound{Fn: atComma, Args: []Term{b1, b2}}
	} else {
		nh, err = dcgExtend(head, s0, s)
		if err != nil {
			return nil, err
		}
		nb, err = m.dcgBody(body, s0, s)
		if err != nil {
			return nil, err
		}
	}
	return &Compound{Fn: atNeck, Args: []Term{nh, nb}}, nil
}

func dcgExtend(t Term, s0, s Term) (Term, error) {
	t = deref(t)
	switch x := t.(type) {
	case *Atom:
		return &Compound{Fn: x, Args: []Term{s0, s}}, nil
	case *Compound:
		na := append(append([]Term(nil), x.Args...), s0, s)
		return &Compound{Fn: x.Fn, Args: na}, nil
	}
	return nil, typeErr("callable", t)
}

// dcgTerminals builds S0 = List ++ S.
func (m *Machine) dcgTerminals(list Term, s0, s Term) (Term, error) {
	items, tail := listToSlice(list)
	if tail != Term(atNil) {
		return nil, typeErr("list", list)
	}
	return &Compound{Fn: atEq, Args: []Term{s0, mkList(items, s)}}, nil
}

func (m *Machine) dcgBody(b Term, s0, s Term) (Term, error) {
	b = deref(b)
	switch x := b.(type) {
	case Str:
		return &Compound{Fn: atEq, Args: []Term{s0, mkList(codeItems(string(x)), s)}}, nil
	case *Var:
		return mk("phrase", x, s0, s), nil
	case *Atom:
		switch x {
		case atNil:
			return &Compound{Fn: atEq, Args: []Term{s0, s}}, nil
		case atCut:
			return &Compound{Fn: atComma, Args: []Term{atCut, &Compound{Fn: atEq, Args: []Term{s0, s}}}}, nil
		}
		return dcgExtend(x, s0, s)
	case *Compound:
		if len(x.Args) == 2 {
			switch x.Fn {
			case atComma:
				mid := m.newVar()
				l, err := m.dcgBody(x.Args[0], s0, mid)
				if err != nil {
					return nil, err
				}
				r, err := m.dcgBody(x.Args[1], mid, s)
				if err != nil {
					return nil, err
				}
				return &Compound{Fn: atComma, Args: []Term{l, r}}, nil
			case atSemi, atBar:
				l, err := m.dcgBody(x.Args[0], s0, s)
				if err != nil {
					return nil, err
				}
				r, err := m.dcgBody(x.Args[1], s0, s)
				if err != nil {
					return nil, err
				}
				return &Compound{Fn: atSemi, Args: []Term{l, r}}, nil
			case atArrow, atSoft:
				mid := m.newVar()
				l, err := m.dcgBody(x.Args[0], s0, mid)
				if err != nil {
					return nil, err
				}
				r, err := m.dcgBody(x.Args[1], mid, s)
				if err != nil {
					return nil, err
				}
				return &Compound{Fn: x.Fn, Args: []Term{l, r}}, nil
			}
		}
		if x.Fn == atNot && len(x.Args) == 1 {
			l, err := m.dcgBody(x.Args[0], s0, m.newVar())
			if err != nil {
				return nil, err
			}
			return &Compound{Fn: atComma, Args: []Term{&Compound{Fn: atNot, Args: []Term{l}}, &Compound{Fn: atEq, Args: []Term{s0, s}}}}, nil
		}
		if x.Fn == atCurly && len(x.Args) == 1 {
			return &Compound{Fn: atComma, Args: []Term{x.Args[0], &Compound{Fn: atEq, Args: []Term{s0, s}}}}, nil
		}
		if x.Fn == atCall {
			na := append(append([]Term(nil), x.Args...), s0, s)
			return &Compound{Fn: atCall, Args: na}, nil
		}
		if x.Fn == atDot && len(x.Args) == 2 {
			return m.dcgTerminals(x, s0, s)
		}
		return dcgExtend(x, s0, s)
	}
	return nil, typeErr("callable", b)
}

func codeItems(s string) []Term {
	var items []Term
	for _, r := range s {
		items = append(items, Int(r))
	}
	return items
}
