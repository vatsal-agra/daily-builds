// Package lang ties the pipeline together: parse → infer → pattern analysis → evaluate.
package lang

import (
	_ "embed"
	"fmt"
	"io"
	"strings"

	"milner/internal/check"
	"milner/internal/eval"
	"milner/internal/syntax"
	"milner/internal/types"
)

//go:embed prelude.ml
var preludeSrc string

// Session is a stateful interpreter: a typing environment plus a value environment.
type Session struct {
	Env        *types.Env
	Interp     *eval.Interp
	PreludeEnv *types.Env // the environment right after the prelude (for listing user bindings)
}

// DeclOut describes the outcome of one declaration.
type DeclOut struct {
	Decl     syntax.Decl
	Bound    []types.Bound
	Values   map[string]eval.Value
	NewTypes []*types.TypeInfo
	ExprType types.Type
	ExprVal  eval.Value
	IsExpr   bool
	Warnings []*syntax.Diag
}

// NewSession creates a session with the prelude loaded. Program output goes to out.
func NewSession(out io.Writer) (*Session, error) {
	s := &Session{Env: types.NewBaseEnv(), Interp: eval.NewInterp(out)}
	outs, err := s.Run(preludeSrc, true)
	if err != nil {
		if d, ok := err.(*syntax.Diag); ok {
			return nil, fmt.Errorf("prelude is broken:\n%s", d.Render(preludeSrc, "prelude.ml"))
		}
		return nil, fmt.Errorf("prelude is broken: %v", err)
	}
	_ = outs
	s.PreludeEnv = s.Env
	return s, nil
}

// Run parses src and processes every declaration in order, stopping at the first error.
// With evaluate=false programs are only type-checked.
func (s *Session) Run(src string, evaluate bool) ([]*DeclOut, error) {
	decls, d := syntax.ParseProgram(src)
	if d != nil {
		return nil, d
	}
	var outs []*DeclOut
	for _, decl := range decls {
		o, err := s.Step(decl, evaluate)
		if err != nil {
			return outs, err
		}
		outs = append(outs, o)
	}
	return outs, nil
}

// Step processes a single declaration.
func (s *Session) Step(decl syntax.Decl, evaluate bool) (out *DeclOut, err error) {
	defer func() {
		if r := recover(); r != nil {
			out, err = nil, &syntax.Diag{Kind: "internal", Span: decl.DSpan(), Msg: fmt.Sprintf("internal error: %v (this is a bug in Milner)", r)}
		}
	}()
	res, d := types.InferDecl(s.Env, decl)
	if d != nil {
		return nil, d
	}
	out = &DeclOut{Decl: decl, Bound: res.Bound, NewTypes: res.NewTypes}
	if res.Expr != nil {
		out.IsExpr, out.ExprType = true, res.Expr
	}
	out.Warnings = check.New(res.Env.Cons).Decl(decl)
	if evaluate {
		r, rerr := s.Interp.Exec(decl, res.Env.Cons)
		if rerr != nil {
			return out, rerr.Diag()
		}
		out.ExprVal = r.Value
		out.Values = map[string]eval.Value{}
		for _, b := range r.Bound {
			out.Values[b.Name] = b.V
		}
	}
	s.Env = res.Env
	return out, nil
}

// TypeOf infers the type of an expression without evaluating it.
func (s *Session) TypeOf(src string) (string, error) {
	e, d := syntax.ParseExpr(src)
	if d != nil {
		return "", d
	}
	t, d := types.InferExpr(s.Env, e, nil)
	if d != nil {
		return "", d
	}
	return types.TypeString(t), nil
}

// Format renders a declaration outcome the way the REPL / `run -v` shows it.
func (o *DeclOut) Format() string {
	var b strings.Builder
	for _, ti := range o.NewTypes {
		fmt.Fprintf(&b, "type %s\n", typeSummary(ti))
	}
	for _, bd := range o.Bound {
		if bd.Name == "_" {
			continue
		}
		fmt.Fprintf(&b, "val %s : %s", bd.Name, types.SchemeString(bd.Scheme))
		if o.Values != nil {
			fmt.Fprintf(&b, " = %s", eval.Show(o.Values[bd.Name]))
		}
		b.WriteByte('\n')
	}
	if o.IsExpr {
		fmt.Fprintf(&b, "- : %s", types.TypeString(o.ExprType))
		if o.ExprVal != nil {
			fmt.Fprintf(&b, " = %s", eval.Show(o.ExprVal))
		}
		b.WriteByte('\n')
	}
	return b.String()
}

func typeSummary(ti *types.TypeInfo) string {
	var params string
	switch ti.Params {
	case 0:
	case 1:
		params = "'a "
	default:
		ps := make([]string, ti.Params)
		for i := range ps {
			ps[i] = "'" + string(rune('a'+i))
		}
		params = "(" + strings.Join(ps, ", ") + ") "
	}
	if ti.IsAlias {
		return fmt.Sprintf("%s%s = %s", params, ti.Head.Name, types.TypeString(ti.AliasBody))
	}
	cons := make([]string, len(ti.Cons))
	for i, c := range ti.Cons {
		cons[i] = c.Name
		if c.Arity > 0 {
			cons[i] += " of …"
		}
	}
	return fmt.Sprintf("%s%s = %s", params, ti.Head.Name, strings.Join(cons, " | "))
}

// Explain type-checks src (without evaluating) and returns a step-by-step inference trace: every
// sub-expression visited, every polymorphic instantiation, every unification with the variables it
// bound, and every generalisation. The error, if any, is the type error that stopped inference
// (the trace up to that point is still returned).
func (s *Session) Explain(src string) ([]string, error) {
	decls, d := syntax.ParseProgram(src)
	if d != nil {
		return nil, d
	}
	env := s.Env
	var lines []string
	for n, decl := range decls {
		tr := types.NewTracer(src)
		if len(decls) > 1 {
			lines = append(lines, fmt.Sprintf("── declaration %d ──", n+1))
		}
		res, d := types.InferDeclTrace(env, decl, tr)
		lines = append(lines, tr.Lines...)
		if d != nil {
			return lines, d
		}
		env = res.Env
		out := &DeclOut{Decl: decl, Bound: res.Bound, NewTypes: res.NewTypes, ExprType: res.Expr, IsExpr: res.Expr != nil}
		for _, l := range strings.Split(strings.TrimSpace(out.Format()), "\n") {
			if l != "" {
				lines = append(lines, "result: "+strings.TrimPrefix(l, "- : "))
			}
		}
	}
	return lines, nil
}
