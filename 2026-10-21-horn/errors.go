package main

import "fmt"

// PrologError carries a thrown ball.
type PrologError struct{ Ball Term }

func (e *PrologError) Error() string { return "prolog error: " + formatTerm(e.Ball, true) }

type haltSignal struct{ code int }

func (h *haltSignal) Error() string { return fmt.Sprintf("halt(%d)", h.code) }

func throwTerm(formal Term, ctx Term) error {
	if ctx == nil {
		ctx = &Var{}
	}
	return &PrologError{Ball: &Compound{Fn: atError, Args: []Term{formal, ctx}}}
}

func instErr() error { return throwTerm(mkAtom("instantiation_error"), nil) }
func typeErr(typ string, culprit Term) error {
	return throwTerm(mk("type_error", mkAtom(typ), culprit), nil)
}
func domErr(dom string, culprit Term) error {
	return throwTerm(mk("domain_error", mkAtom(dom), culprit), nil)
}
func existErr(kind string, what Term) error {
	return throwTerm(mk("existence_error", mkAtom(kind), what), nil)
}
func permErr(action, typ string, culprit Term) error {
	return throwTerm(mk("permission_error", mkAtom(action), mkAtom(typ), culprit), nil)
}
func reprErr(what string) error { return throwTerm(mk("representation_error", mkAtom(what)), nil) }
func evalErr(what string) error { return throwTerm(mk("evaluation_error", mkAtom(what)), nil) }
func syntaxErr(msg string) error {
	return throwTerm(mk("syntax_error", mkAtom(msg)), nil)
}
