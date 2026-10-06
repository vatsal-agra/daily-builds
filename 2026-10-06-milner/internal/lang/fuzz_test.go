package lang

import (
	"fmt"
	"io"
	"math/rand"
	"strings"
	"testing"

	"milner/internal/syntax"
)

// A type-directed program generator: it builds random expressions of a requested type, so every
// program it emits is well-typed by construction. The properties checked are
//   (soundness)  the checker accepts every generated program, at the intended type, and
//   (progress)   evaluating an accepted program never trips an internal error / Go type assertion;
//                the only allowed failures are the documented runtime errors.

type gty struct {
	kind string // int bool string list opt pair fun unit
	a, b *gty
}

func (t *gty) String() string {
	switch t.kind {
	case "list":
		return "(" + t.a.String() + " list)"
	case "opt":
		return "(" + t.a.String() + " option)"
	case "pair":
		return "(" + t.a.String() + " * " + t.b.String() + ")"
	case "rec":
		return "{ a : " + t.a.String() + "; b : " + t.b.String() + " }"
	case "fun":
		return "(" + t.a.String() + " -> " + t.b.String() + ")"
	}
	return t.kind
}

var (
	tInt  = &gty{kind: "int"}
	tBool = &gty{kind: "bool"}
	tStr  = &gty{kind: "string"}
	tUnit = &gty{kind: "unit"}
)

type genv struct {
	name string
	t    *gty
}

type gen struct {
	r    *rand.Rand
	next int
}

func (g *gen) randType(depth int) *gty {
	if depth <= 0 {
		return []*gty{tInt, tBool, tStr}[g.r.Intn(3)]
	}
	switch g.r.Intn(11) {
	case 9, 10:
		return &gty{kind: "rec", a: g.randType(depth - 1), b: g.randType(depth - 1)}
	case 0, 1:
		return tInt
	case 2:
		return tBool
	case 3:
		return tStr
	case 4:
		return &gty{kind: "list", a: g.randType(depth - 1)}
	case 5:
		return &gty{kind: "opt", a: g.randType(depth - 1)}
	case 6:
		return &gty{kind: "pair", a: g.randType(depth - 1), b: g.randType(depth - 1)}
	default:
		return &gty{kind: "fun", a: g.randType(depth - 1), b: g.randType(depth - 1)}
	}
}

func lit(n int) string {
	if n < 0 {
		return fmt.Sprintf("(%d)", n)
	}
	return fmt.Sprint(n)
}

func eq(a, b *gty) bool { return a.String() == b.String() }

func (g *gen) fresh() string { g.next++; return fmt.Sprintf("v%d", g.next) }

func (g *gen) expr(t *gty, env []genv, d int) string {
	// variables of exactly this type
	var vars []string
	for _, e := range env {
		if eq(e.t, t) {
			vars = append(vars, e.name)
		}
	}
	if d <= 0 {
		if len(vars) > 0 && g.r.Intn(2) == 0 {
			return vars[g.r.Intn(len(vars))]
		}
		return g.leaf(t, env)
	}
	n := g.r.Intn(12)
	switch {
	case n == 10:
		// field selection (the record may have extra fields at the use site only through its type)
		other := g.randType(1)
		field := []string{"a", "b"}[g.r.Intn(2)]
		rt := &gty{kind: "rec", a: t, b: other}
		if field == "b" {
			rt = &gty{kind: "rec", a: other, b: t}
		}
		return fmt.Sprintf("(%s).%s", g.expr(rt, env, d-1), field)
	case n == 11:
		// destructure a record with a pattern
		at, bt := g.randType(1), g.randType(1)
		x, y := g.fresh(), g.fresh()
		e2 := append(env[:len(env):len(env)], genv{x, at}, genv{y, bt})
		return fmt.Sprintf("(let { b = %s; a = %s } = %s in %s)", y, x, g.expr(&gty{kind: "rec", a: at, b: bt}, env, d-1), g.expr(t, e2, d-1))
	case n == 0 && len(vars) > 0:
		return vars[g.r.Intn(len(vars))]
	case n == 1:
		// if
		return fmt.Sprintf("(if %s then %s else %s)", g.expr(tBool, env, d-1), g.expr(t, env, d-1), g.expr(t, env, d-1))
	case n == 2:
		// let
		lt := g.randType(1)
		v := g.fresh()
		return fmt.Sprintf("(let %s = %s in %s)", v, g.expr(lt, env, d-1), g.expr(t, append(env[:len(env):len(env)], genv{v, lt}), d-1))
	case n == 3:
		// apply a function
		at := g.randType(1)
		return fmt.Sprintf("(%s %s)", g.expr(&gty{kind: "fun", a: at, b: t}, env, d-1), g.expr(at, env, d-1))
	case n == 4:
		// match on an option
		at := g.randType(1)
		v := g.fresh()
		return fmt.Sprintf("(match %s with Some %s -> %s | None -> %s)", g.expr(&gty{kind: "opt", a: at}, env, d-1), v,
			g.expr(t, append(env[:len(env):len(env)], genv{v, at}), d-1), g.expr(t, env, d-1))
	case n == 5:
		// match on a list
		at := g.randType(1)
		h, tl := g.fresh(), g.fresh()
		e2 := append(env[:len(env):len(env)], genv{h, at}, genv{tl, &gty{kind: "list", a: at}})
		return fmt.Sprintf("(match %s with [] -> %s | %s :: %s -> %s)", g.expr(&gty{kind: "list", a: at}, env, d-1), g.expr(t, env, d-1), h, tl, g.expr(t, e2, d-1))
	case n == 6:
		// destructure a pair
		at, bt := g.randType(1), g.randType(1)
		a, b := g.fresh(), g.fresh()
		e2 := append(env[:len(env):len(env)], genv{a, at}, genv{b, bt})
		return fmt.Sprintf("(let (%s, %s) = %s in %s)", a, b, g.expr(&gty{kind: "pair", a: at, b: bt}, env, d-1), g.expr(t, e2, d-1))
	}
	return g.structural(t, env, d)
}

func (g *gen) leaf(t *gty, env []genv) string {
	switch t.kind {
	case "int":
		return lit(g.r.Intn(21) - 5)
	case "bool":
		return []string{"true", "false"}[g.r.Intn(2)]
	case "string":
		return fmt.Sprintf("%q", []string{"a", "bc", "", "xyz"}[g.r.Intn(4)])
	case "unit":
		return "()"
	}
	return g.structural(t, env, 0)
}

func (g *gen) structural(t *gty, env []genv, d int) string {
	dd := d - 1
	switch t.kind {
	case "int":
		switch g.r.Intn(6) {
		case 0:
			return fmt.Sprintf("(%s + %s)", g.expr(tInt, env, dd), g.expr(tInt, env, dd))
		case 1:
			return fmt.Sprintf("(%s * %s)", g.expr(tInt, env, dd), g.expr(tInt, env, dd))
		case 2:
			return fmt.Sprintf("(%s - %s)", g.expr(tInt, env, dd), g.expr(tInt, env, dd))
		case 3:
			return fmt.Sprintf("(%s / %s)", g.expr(tInt, env, dd), g.expr(tInt, env, dd)) // may divide by zero: allowed
		case 4:
			return fmt.Sprintf("(length %s)", g.expr(&gty{kind: "list", a: g.randType(1)}, env, dd))
		}
		return lit(g.r.Intn(21) - 5)
	case "bool":
		switch g.r.Intn(5) {
		case 0:
			return fmt.Sprintf("(%s < %s)", g.expr(tInt, env, dd), g.expr(tInt, env, dd))
		case 1:
			return fmt.Sprintf("(%s && %s)", g.expr(tBool, env, dd), g.expr(tBool, env, dd))
		case 2:
			return fmt.Sprintf("(not %s)", g.expr(tBool, env, dd))
		case 3:
			at := g.randType(1)
			if strings.Contains(at.String(), "->") {
				at = tInt
			}
			return fmt.Sprintf("(%s = %s)", g.expr(at, env, dd), g.expr(at, env, dd))
		}
		return []string{"true", "false"}[g.r.Intn(2)]
	case "string":
		switch g.r.Intn(3) {
		case 0:
			return fmt.Sprintf("(%s ^ %s)", g.expr(tStr, env, dd), g.expr(tStr, env, dd))
		case 1:
			return fmt.Sprintf("(string_of_int %s)", g.expr(tInt, env, dd))
		}
		return `"s"`
	case "list":
		switch g.r.Intn(5) {
		case 0:
			return "[]"
		case 1:
			return fmt.Sprintf("(%s :: %s)", g.expr(t.a, env, dd), g.expr(t, env, dd))
		case 2:
			return fmt.Sprintf("(%s @ %s)", g.expr(t, env, dd), g.expr(t, env, dd))
		case 3:
			at := g.randType(1)
			return fmt.Sprintf("(map %s %s)", g.expr(&gty{kind: "fun", a: at, b: t.a}, env, dd), g.expr(&gty{kind: "list", a: at}, env, dd))
		}
		return fmt.Sprintf("[%s; %s]", g.expr(t.a, env, dd), g.expr(t.a, env, dd))
	case "opt":
		if g.r.Intn(3) == 0 {
			return "None"
		}
		return fmt.Sprintf("(Some %s)", g.expr(t.a, env, dd))
	case "pair":
		return fmt.Sprintf("(%s, %s)", g.expr(t.a, env, dd), g.expr(t.b, env, dd))
	case "rec":
		ea, eb := g.expr(t.a, env, dd), g.expr(t.b, env, dd)
		if g.r.Intn(2) == 0 {
			return fmt.Sprintf("{ a = %s; b = %s }", ea, eb)
		}
		return fmt.Sprintf("{ b = %s; a = %s }", eb, ea)
	case "fun":
		v := g.fresh()
		return fmt.Sprintf("(fun %s -> %s)", v, g.expr(t.b, append(env[:len(env):len(env)], genv{v, t.a}), dd))
	}
	return "()"
}

func TestFuzzSoundnessAndProgress(t *testing.T) {
	s, _ := newSession(t)
	s.Interp.M.Out = io.Discard
	s.Interp.M.MaxSteps = 200000
	seed := int64(20261006)
	g := &gen{r: rand.New(rand.NewSource(seed))}
	accepted, ran, runtimeFail := 0, 0, 0
	const N = 4000
	for k := 0; k < N; k++ {
		ty := g.randType(2)
		src := fmt.Sprintf("(%s : %s)", g.expr(ty, nil, 4), ty)
		e, d := syntax.ParseExpr(src)
		if d != nil {
			t.Fatalf("generator produced unparsable source (seed %d, #%d): %v\n%s", seed, k, d, src)
		}
		decl := &syntax.DExpr{E: e, Sp: e.ESpan()}
		o, err := s.Step(decl, true)
		if err != nil {
			dg, ok := err.(*syntax.Diag)
			if !ok {
				t.Fatalf("#%d: non-diagnostic error %v", k, err)
			}
			switch dg.Kind {
			case "runtime":
				if o == nil {
					t.Fatalf("#%d: runtime error without a type-check result", k)
				}
				accepted++
				runtimeFail++
				if !strings.Contains(dg.Msg, "Division_by_zero") && !strings.Contains(dg.Msg, "step limit") && !strings.Contains(dg.Msg, "stack overflow") {
					t.Fatalf("#%d: unexpected runtime error %q for %s", k, dg.Msg, src)
				}
			default:
				t.Fatalf("#%d: checker rejected (or crashed on) a well-typed program: [%s] %s\n%s", k, dg.Kind, dg.Msg, src)
			}
			continue
		}
		accepted++
		ran++
	}
	if ran < N/2 {
		t.Errorf("only %d of %d programs ran to completion (%d runtime failures)", ran, N, runtimeFail)
	}
	t.Logf("accepted %d/%d well-typed programs; %d ran to completion, %d hit allowed runtime errors", accepted, N, ran, runtimeFail)
}
