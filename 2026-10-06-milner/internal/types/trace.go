package types

import "milner/internal/syntax"

// Tracer records inference steps for `milner explain`.
type Tracer struct {
	Events []TraceEvent
}

// TraceEvent is one step of the inference trace.
type TraceEvent struct {
	Depth int
	Kind  string // "expr", "inst", "unify", "generalize"
	Text  string
	Span  syntax.Span
}

func (t *Tracer) expr(depth int, e syntax.Expr, ty Type)         {}
func (t *Tracer) inst(depth int, name string, scheme, inst Type) {}
func (t *Tracer) unify(depth int, a, b Type)                     {}
func (t *Tracer) generalize(depth int, name string, ty Type)     {}
