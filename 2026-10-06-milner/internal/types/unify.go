package types

import "fmt"

// UnifyErr describes why two types failed to unify.
type UnifyErr struct {
	Occurs bool
	A, B   Type // the mismatching sub-terms (or the variable and the type containing it for occurs)
	Arity  bool
	Field  string // non-empty: a record row lacks this field
	// LacksLeft: the row lacking Field is on the left (expected) side of the unification
	LacksLeft bool
}

func (u *UnifyErr) Error() string { return "unification failed" }

type unifier struct {
	trail []*TVar
	next  *int
}

func (u *unifier) bind(v *TVar, t Type) {
	v.Ref = t
	u.trail = append(u.trail, v)
}

func (u *unifier) undo() {
	for _, v := range u.trail {
		v.Ref = nil
	}
	u.trail = nil
}

// occursAdjust checks that v does not occur in t and lowers the levels of variables in t to v's level.
func occursAdjust(v *TVar, t Type) bool {
	t = Prune(t)
	switch x := t.(type) {
	case *TVar:
		if x == v {
			return true
		}
		if x.Level > v.Level {
			x.Level = v.Level
		}
	case *TCon:
		for _, a := range x.Args {
			if occursAdjust(v, a) {
				return true
			}
		}
	}
	return false
}

func (u *unifier) unify(a, b Type) *UnifyErr {
	a, b = Prune(a), Prune(b)
	if a == b {
		return nil
	}
	if va, ok := a.(*TVar); ok {
		return u.bindVar(va, b)
	}
	if vb, ok := b.(*TVar); ok {
		return u.bindVar(vb, a)
	}
	ca, cb := a.(*TCon), b.(*TCon)
	if ca.Head.Row || cb.Head.Row {
		return u.unifyRows(a, b, ca, cb)
	}
	if ca.Head != cb.Head {
		return &UnifyErr{A: a, B: b}
	}
	if len(ca.Args) != len(cb.Args) {
		return &UnifyErr{A: a, B: b, Arity: true}
	}
	for i := range ca.Args {
		if err := u.unify(ca.Args[i], cb.Args[i]); err != nil {
			return err
		}
	}
	return nil
}

func (u *unifier) bindVar(v *TVar, t Type) *UnifyErr {
	if v.Level == Generic {
		panic(fmt.Sprintf("internal error: unifying generic variable %d", v.ID))
	}
	if occursAdjust(v, t) {
		return &UnifyErr{Occurs: true, A: v, B: t}
	}
	u.bind(v, t)
	return nil
}

// unifyRows unifies two record rows (Rémy-style): fields may appear in any order, and an open row
// (ending in an unresolved variable) absorbs the fields the other side has and it lacks.
func (u *unifier) unifyRows(a, b Type, ca, cb *TCon) *UnifyErr {
	switch {
	case ca.Head == HRowEmpty && cb.Head == HRowEmpty:
		return nil
	case ca.Head == HRowEmpty:
		return &UnifyErr{A: a, B: b, Field: cb.Head.Label, LacksLeft: true}
	case cb.Head == HRowEmpty:
		return &UnifyErr{A: b, B: a, Field: ca.Head.Label}
	}
	if ca.Head == cb.Head {
		if err := u.unify(ca.Args[0], cb.Args[0]); err != nil {
			return err
		}
		return u.unify(ca.Args[1], cb.Args[1])
	}
	t, rest, err := u.rewriteRow(b, ca.Head.Label)
	if err != nil {
		return err
	}
	if err := u.unify(ca.Args[0], t); err != nil {
		return err
	}
	return u.unify(ca.Args[1], rest)
}

// rewriteRow finds `label` in row, returning its type and the row without it.
func (u *unifier) rewriteRow(row Type, label string) (Type, Type, *UnifyErr) {
	row = Prune(row)
	switch x := row.(type) {
	case *TCon:
		if x.Head == HRowEmpty {
			return nil, nil, &UnifyErr{A: x, B: x, Field: label}
		}
		if x.Head.Label == label {
			return x.Args[0], x.Args[1], nil
		}
		t, rest, err := u.rewriteRow(x.Args[1], label)
		if err != nil {
			return nil, nil, err
		}
		return t, RowExt(x.Head.Label, x.Args[0], rest), nil
	case *TVar:
		t := &TVar{ID: -1, Level: x.Level}
		rest := &TVar{ID: -1, Level: x.Level}
		if err := u.bindVar(x, RowExt(label, t, rest)); err != nil {
			return nil, nil, err
		}
		return t, rest, nil
	}
	panic("rewriteRow: bad row")
}
