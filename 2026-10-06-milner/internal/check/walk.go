package check

import (
	"fmt"

	"milner/internal/syntax"
)

// Decl analyses every match, function parameter and let pattern inside a declaration, returning
// warnings (non-exhaustive matches, redundant arms, refutable bindings).
func (c *Checker) Decl(d syntax.Decl) []*syntax.Diag {
	w := &walker{c: c}
	switch x := d.(type) {
	case *syntax.DLet:
		for _, b := range x.Bindings {
			w.binding(b)
		}
	case *syntax.DExpr:
		w.expr(x.E)
	}
	return w.out
}

type walker struct {
	c   *Checker
	out []*syntax.Diag
}

func (w *walker) warn(sp syntax.Span, msg, label string, notes ...string) {
	w.out = append(w.out, &syntax.Diag{Kind: "pattern", Warn: true, Span: sp, Msg: msg, Label: label, Notes: notes})
}

func (w *walker) binding(b *syntax.Binding) {
	w.refutable(b.Pat, "let binding")
	w.expr(b.Expr)
}

// refutable warns when a single pattern (let / parameter) may fail to match.
func (w *walker) refutable(p syntax.Pat, what string) {
	res := w.c.Analyze([]armIn{{pat: p}})
	if res.GaveUp {
		return
	}
	if res.Missing != "" {
		w.warn(p.PSpan(), fmt.Sprintf("this %s pattern is refutable and may raise `Match_failure` at run time", what),
			"may not match", fmt.Sprintf("for example, it does not match `%s`", res.Missing))
	}
}

func (w *walker) expr(e syntax.Expr) {
	switch x := e.(type) {
	case *syntax.ECon:
		if x.Arg != nil {
			w.expr(x.Arg)
		}
	case *syntax.EFun:
		for _, p := range x.Params {
			w.refutable(p, "parameter")
		}
		w.expr(x.Body)
	case *syntax.EApp:
		w.expr(x.Fn)
		w.expr(x.Arg)
	case *syntax.ELet:
		for _, b := range x.Bindings {
			w.binding(b)
		}
		w.expr(x.Body)
	case *syntax.EIf:
		w.expr(x.Cond)
		w.expr(x.Then)
		w.expr(x.Else)
	case *syntax.EMatch:
		w.expr(x.Scrut)
		arms := make([]armIn, len(x.Arms))
		for i, a := range x.Arms {
			arms[i] = armIn{pat: a.Pat, guarded: a.Guard != nil}
			if a.Guard != nil {
				w.expr(a.Guard)
			}
			w.expr(a.Body)
		}
		res := w.c.Analyze(arms)
		if res.GaveUp {
			w.warn(x.Sp, "pattern analysis gave up (the match is too large to check)", "not checked")
			return
		}
		for _, sp := range res.Redundant {
			w.warn(sp, "this pattern can never match: earlier patterns already cover every value it matches", "unreachable")
		}
		if res.Missing != "" {
			sp := x.Sp
			// underline just the first line (`match ... with`) to keep the diagnostic compact
			if len(x.Arms) > 0 {
				sp = syntax.Span{Start: x.Sp.Start, End: x.Arms[0].Pat.PSpan().Start}
				if sp.End.Line != sp.Start.Line {
					sp.End = x.Sp.Start
					sp.End.Col += 5
					sp.End.Off += 5
				}
			}
			w.warn(sp, "this `match` is not exhaustive", "missing: `"+res.Missing+"`",
				fmt.Sprintf("for example, the value `%s` is not matched by any arm", res.Missing))
		}
	case *syntax.ETuple:
		for _, el := range x.Elems {
			w.expr(el)
		}
	case *syntax.ESeq:
		w.expr(x.A)
		w.expr(x.B)
	case *syntax.EAnd:
		w.expr(x.L)
		w.expr(x.R)
	case *syntax.EOr:
		w.expr(x.L)
		w.expr(x.R)
	case *syntax.EAnnot:
		w.expr(x.E)
	}
}
