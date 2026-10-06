package types

import "fmt"

// UnifyErr describes why two types failed to unify.
type UnifyErr struct {
	Occurs bool
	A, B   Type // the mismatching sub-terms (or the variable and the type containing it for occurs)
	Arity  bool
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
