package types

import (
	"fmt"
	"strings"

	"milner/internal/syntax"
)

// Tracer records inference steps for `milner explain`: which sub-expression is being inferred, which
// polymorphic schemes get instantiated, which unifications happen and which variables they bind.
// Unresolved type variables are shown as t1, t2, … in order of first appearance; generalised ones as 'a, 'b.
type Tracer struct {
	Src   string
	Lines []string
	ids   map[*TVar]int
}

// NewTracer returns a tracer that quotes snippets of src.
func NewTracer(src string) *Tracer {
	return &Tracer{Src: src, ids: map[*TVar]int{}}
}

func (t *Tracer) printer() *Printer {
	p := NewPrinter()
	p.namer = func(v *TVar) string {
		if v.Level == Generic {
			return ""
		}
		id, ok := t.ids[v]
		if !ok {
			id = len(t.ids) + 1
			t.ids[v] = id
		}
		return fmt.Sprintf("t%d", id)
	}
	return p
}

func (t *Tracer) ty(x Type) string { return t.printer().String(x) }

func (t *Tracer) line(depth int, format string, a ...any) {
	t.Lines = append(t.Lines, strings.Repeat("  ", depth)+fmt.Sprintf(format, a...))
}

func (t *Tracer) snippet(sp syntax.Span) string {
	if sp.End.Off > len(t.Src) || sp.End.Off <= sp.Start.Off {
		return ""
	}
	s := strings.Join(strings.Fields(t.Src[sp.Start.Off:sp.End.Off]), " ")
	// the parser drops parentheses from spans; put back the ones this snippet cuts in half
	open, inStr := 0, false
	missingOpen := 0
	for _, r := range s {
		switch {
		case r == '"':
			inStr = !inStr
		case inStr:
		case r == '(':
			open++
		case r == ')':
			if open > 0 {
				open--
			} else {
				missingOpen++
			}
		}
	}
	s = strings.Repeat("(", missingOpen) + s + strings.Repeat(")", open)
	if r := []rune(s); len(r) > 48 {
		s = string(r[:45]) + "..."
	}
	return s
}

func (t *Tracer) enter(depth int, e syntax.Expr) {
	t.line(depth-1, "infer  %s", t.snippet(e.ESpan()))
}

func (t *Tracer) expr(depth int, e syntax.Expr, ty Type) {
	t.line(depth, "⊢ %s : %s", t.snippet(e.ESpan()), t.ty(ty))
}

func (t *Tracer) inst(depth int, name string, scheme, inst Type) {
	if hasGeneric(scheme) {
		t.line(depth, "instantiate `%s` : %s  ⟹  %s", name, t.ty(scheme), t.ty(inst))
	} else if hasUnbound(inst) {
		t.line(depth, "`%s` : %s  (monomorphic variable: its type is still being solved)", name, t.ty(inst))
	} else {
		t.line(depth, "`%s` : %s", name, t.ty(inst))
	}
}

func (t *Tracer) unifyStr(depth int, a, b string, bound []string, failed bool) {
	switch {
	case failed:
		t.line(depth, "unify %s ~ %s  ✗ fails", a, b)
	case len(bound) == 0:
		t.line(depth, "unify %s ~ %s  ✓ (already equal)", a, b)
	default:
		t.line(depth, "unify %s ~ %s  ✓  %s", a, b, strings.Join(bound, ", "))
	}
}

func (t *Tracer) generalize(depth int, name string, ty Type) {
	t.line(depth, "generalize `%s` : %s", name, t.ty(ty))
}

func hasUnbound(t Type) bool {
	switch x := Prune(t).(type) {
	case *TVar:
		return x.Level != Generic
	case *TCon:
		for _, a := range x.Args {
			if hasUnbound(a) {
				return true
			}
		}
	}
	return false
}
