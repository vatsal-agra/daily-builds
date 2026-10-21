package main

// findall, bagof, setof and friends.

func (m *Machine) findAll(template, goal Term) ([]Term, error) {
	q := m.newQuery(goal)
	var out []Term
	for {
		ok, err := q.next()
		if err != nil {
			q.close()
			return nil, err
		}
		if !ok {
			break
		}
		out = append(out, m.copyTerm(template, map[*Var]Term{}))
	}
	q.close()
	return out, nil
}

// stripCaret removes V^Goal prefixes, collecting the quantified variables.
func stripCaret(g Term, bound map[*Var]bool, out *[]*Var) Term {
	for {
		g = deref(g)
		c, ok := g.(*Compound)
		if ok && c.Fn == atCaret && len(c.Args) == 2 {
			termVars(c.Args[0], bound, out)
			g = c.Args[1]
			continue
		}
		if ok && c.Fn == atColon && len(c.Args) == 2 {
			g = c.Args[1]
			continue
		}
		return g
	}
}

func (m *Machine) installSolutionBuiltins() {
	m.det("findall", 3, func(m *Machine, a []Term) (bool, error) {
		if _, isv := deref(a[1]).(*Var); isv {
			return false, instErr()
		}
		if l := deref(a[2]); l != nil {
			if _, isv := l.(*Var); !isv {
				if _, isc := isCons(l); !isc && l != Term(atNil) {
					return false, typeErr("list", l)
				}
			}
		}
		res, err := m.findAll(a[0], a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[2], mkList(res, atNil)), nil
	})
	m.det("findall", 4, func(m *Machine, a []Term) (bool, error) {
		res, err := m.findAll(a[0], a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[2], mkList(res, a[3])), nil
	})
	bagof := func(isSet bool) NondetFn {
		return func(m *Machine, a []Term) (Term, []Term, error) {
			tmpl, goal := a[0], a[1]
			if _, isv := deref(goal).(*Var); isv {
				return nil, nil, instErr()
			}
			bound := map[*Var]bool{}
			var tv []*Var
			termVars(tmpl, bound, &tv)
			inner := stripCaret(goal, bound, &tv)
			if !isCallable(inner) {
				return nil, nil, typeErr("callable", inner)
			}
			var free []*Var
			termVars(inner, bound, &free)
			wit := make([]Term, len(free))
			for i, v := range free {
				wit[i] = v
			}
			w := &Compound{Fn: mkAtom("v"), Args: wit}
			if len(wit) == 0 {
				w = nil
			}
			var wt Term = atNil
			if w != nil {
				wt = w
			}
			pairs, err := m.findAll(mk("-", wt, tmpl), inner)
			if err != nil {
				return nil, nil, err
			}
			if len(pairs) == 0 {
				return nil, nil, nil
			}
			finish := func(items []Term) Term {
				if isSet {
					items = sortTerms(items, true)
				}
				return mkList(items, atNil)
			}
			if w == nil {
				items := make([]Term, len(pairs))
				for i, p := range pairs {
					items[i] = p.(*Compound).Args[1]
				}
				return a[2], []Term{finish(items)}, nil
			}
			// group by witness: sort pairs by witness (stable), then split on variants
			keys := make([]Term, len(pairs))
			copy(keys, pairs)
			sorted := sortPairsByKey(pairs)
			var sols []Term
			for i := 0; i < len(sorted); {
				k := sorted[i].(*Compound).Args[0]
				j := i
				var items []Term
				for j < len(sorted) && variant(sorted[j].(*Compound).Args[0], k) {
					items = append(items, sorted[j].(*Compound).Args[1])
					j++
				}
				// unify witnesses of the grouped solutions with each other (non-ground case)
				sols = append(sols, mk("-", k, finish(items)))
				i = j
			}
			return mk("-", w, a[2]), sols, nil
		}
	}
	m.nondet("bagof", 3, bagof(false))
	m.nondet("setof", 3, bagof(true))
	m.det("$aggregate_all", 3, func(m *Machine, a []Term) (bool, error) { return m.aggregateAll(a) })
}

func sortPairsByKey(pairs []Term) []Term {
	out := append([]Term(nil), pairs...)
	sortStable(out, func(x, y Term) bool {
		return compareTerms(x.(*Compound).Args[0], y.(*Compound).Args[0]) < 0
	})
	return out
}

// variant reports structural equality up to variable renaming.
func variant(a, b Term) bool {
	m1 := map[*Var]*Var{}
	m2 := map[*Var]*Var{}
	var rec func(a, b Term) bool
	rec = func(a, b Term) bool {
		a, b = deref(a), deref(b)
		va, aok := a.(*Var)
		vb, bok := b.(*Var)
		if aok || bok {
			if !(aok && bok) {
				return false
			}
			if x, ok := m1[va]; ok {
				return x == vb
			}
			if _, ok := m2[vb]; ok {
				return false
			}
			m1[va], m2[vb] = vb, va
			return true
		}
		ca, aok := a.(*Compound)
		cb, bok := b.(*Compound)
		if aok && bok {
			if ca.Fn != cb.Fn || len(ca.Args) != len(cb.Args) {
				return false
			}
			for i := range ca.Args {
				if !rec(ca.Args[i], cb.Args[i]) {
					return false
				}
			}
			return true
		}
		return compareTerms(a, b) == 0
	}
	return rec(a, b)
}

func (m *Machine) aggregateAll(a []Term) (bool, error) {
	spec := deref(a[0])
	if at, ok := spec.(*Atom); ok && at.Name == "count" {
		res, err := m.findAll(atTrue, a[1])
		if err != nil {
			return false, err
		}
		return m.unify(a[2], Int(len(res))), nil
	}
	c, ok := spec.(*Compound)
	if !ok || len(c.Args) != 1 {
		if _, isv := spec.(*Var); isv {
			return false, instErr()
		}
		return false, domErr("aggregate_spec", spec)
	}
	res, err := m.findAll(c.Args[0], a[1])
	if err != nil {
		return false, err
	}
	switch c.Fn.Name {
	case "count":
		return m.unify(a[2], Int(len(res))), nil
	case "bag":
		return m.unify(a[2], mkList(res, atNil)), nil
	case "set":
		return m.unify(a[2], mkList(sortTerms(res, true), atNil)), nil
	case "sum":
		var acc Term = Int(0)
		for _, r := range res {
			var err error
			acc, err = m.eval(&Compound{Fn: atPlus, Args: []Term{acc, r}})
			if err != nil {
				return false, err
			}
		}
		return m.unify(a[2], acc), nil
	case "max", "min":
		if len(res) == 0 {
			return false, nil
		}
		isMax := c.Fn.Name == "max"
		// max(X) numeric; max(X, Witness) handled via pair terms below
		var best Term
		for _, r := range res {
			r = deref(r)
			if pc, ok := r.(*Compound); ok && pc.Fn == atMinus && len(pc.Args) == 2 {
				_ = pc
			}
			var v Term = r
			if isNumber(r) {
				// numeric solutions compare by value
			} else if ev, err := m.eval(r); err == nil && isCallable(r) && !isPairLike(r) {
				v = ev
			}
			cmp := compareValues(v, best)
			if best == nil || (isMax && cmp > 0) || (!isMax && cmp < 0) {
				best = v
			}
		}
		return m.unify(a[2], best), nil
	}
	return false, domErr("aggregate_spec", spec)
}

// isPairLike reports Key-Value style terms, which aggregate_all(max(...)) orders by standard order.
func isPairLike(t Term) bool {
	c, ok := deref(t).(*Compound)
	return ok && c.Fn == atMinus && len(c.Args) == 2
}

// compareValues orders numbers numerically and everything else by standard order of terms.
func compareValues(a, b Term) int {
	if b == nil {
		return 0
	}
	if isNumber(a) && isNumber(b) {
		return numCompare(a, b)
	}
	return compareTerms(a, b)
}
