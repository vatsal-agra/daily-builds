package sable

import (
	"fmt"
	"math/rand"
	"strings"
)

// GenConfig bounds the random program generator.
type GenConfig struct {
	Funcs     int // helper functions besides main
	MaxStmts  int // statements per block
	MaxDepth  int // statement nesting
	ExprDepth int
	TrapRate  int // percent of divisions whose divisor is NOT forced non-zero
}

func DefaultGen() GenConfig {
	return GenConfig{Funcs: 3, MaxStmts: 5, MaxDepth: 3, ExprDepth: 3, TrapRate: 8}
}

type gen struct {
	r      *rand.Rand
	cfg    GenConfig
	sb     strings.Builder
	scopes [][]gvar
	nameN  int
	loops  int
	callee int // functions with index < callee may be called
	inFor  int
	arity  []int
}

type gvar struct {
	name      string
	protected bool // loop counters: never assigned in the body so loops terminate
}

var interesting = []string{"0", "1", "2", "3", "5", "7", "8", "10", "16", "31", "63", "64", "100", "255", "1000",
	"65536", "2147483647", "4294967296", "9223372036854775807", "-1", "-2", "-8", "-100", "(-9223372036854775807 - 1)"}

// GenProgram deterministically generates a terminating program from a seed.
func GenProgram(seed int64, cfg GenConfig) string {
	g := &gen{r: rand.New(rand.NewSource(seed)), cfg: cfg}
	arity := make([]int, cfg.Funcs)
	for i := range arity {
		arity[i] = g.r.Intn(4)
	}
	for i := 0; i < cfg.Funcs; i++ {
		g.callee = i
		g.funcDecl(fmt.Sprintf("f%d", i), arity[i], arity)
	}
	g.callee = cfg.Funcs
	g.funcDecl("main", 0, arity)
	return g.sb.String()
}

func (g *gen) fresh(p string) string { g.nameN++; return fmt.Sprintf("%s%d", p, g.nameN) }
func (g *gen) w(f string, a ...any)  { fmt.Fprintf(&g.sb, f, a...) }

func (g *gen) funcDecl(name string, n int, arity []int) {
	g.scopes = [][]gvar{nil}
	var ps []string
	for i := 0; i < n; i++ {
		p := fmt.Sprintf("p%d", i)
		ps = append(ps, p)
		g.scopes[0] = append(g.scopes[0], gvar{name: p})
	}
	g.w("func %s(%s) {\n", name, strings.Join(ps, ", "))
	g.arity = arity
	g.block(1, 0)
	g.w("    return %s;\n}\n\n", g.expr(g.cfg.ExprDepth))
}

func (g *gen) vars(assignable bool) []string {
	var out []string
	for _, s := range g.scopes {
		for _, v := range s {
			if !assignable || !v.protected {
				out = append(out, v.name)
			}
		}
	}
	return out
}

func (g *gen) indent(d int) string { return strings.Repeat("    ", d) }

func (g *gen) block(ind, depth int) {
	n := 1 + g.r.Intn(g.cfg.MaxStmts)
	for i := 0; i < n; i++ {
		g.stmt(ind, depth)
	}
}

func (g *gen) scoped(ind, depth int, pre func()) {
	g.scopes = append(g.scopes, nil)
	if pre != nil {
		pre()
	}
	g.block(ind, depth)
	g.scopes = g.scopes[:len(g.scopes)-1]
}

func (g *gen) stmt(ind, depth int) {
	in := g.indent(ind)
	choice := g.r.Intn(100)
	canNest := depth < g.cfg.MaxDepth
	switch {
	case choice < 22 || len(g.vars(true)) == 0:
		name := g.fresh("v")
		g.w("%svar %s = %s;\n", in, name, g.expr(g.cfg.ExprDepth))
		top := len(g.scopes) - 1
		g.scopes[top] = append(g.scopes[top], gvar{name: name})
	case choice < 42:
		vs := g.vars(true)
		g.w("%s%s = %s;\n", in, vs[g.r.Intn(len(vs))], g.expr(g.cfg.ExprDepth))
	case choice < 54:
		g.w("%sprint(%s);\n", in, g.expr(g.cfg.ExprDepth))
	case choice < 68 && canNest:
		g.w("%sif %s {\n", in, g.cond())
		g.scoped(ind+1, depth+1, nil)
		if g.r.Intn(2) == 0 {
			g.w("%s} else {\n", in)
			g.scoped(ind+1, depth+1, nil)
		}
		g.w("%s}\n", in)
	case choice < 80 && canNest && g.loops < 2:
		g.loops++
		g.inFor++
		iv := g.fresh("i")
		bound := 1 + g.r.Intn(6)
		g.w("%sfor var %s = 0; %s < %d; %s = %s + 1 {\n", in, iv, iv, bound, iv, iv)
		g.scoped(ind+1, depth+1, func() {
			top := len(g.scopes) - 1
			g.scopes[top] = append(g.scopes[top], gvar{name: iv, protected: true})
		})
		g.w("%s}\n", in)
		g.inFor--
		g.loops--
	case choice < 84 && g.inFor > 0:
		if g.r.Intn(2) == 0 {
			g.w("%sif %s { break; }\n", in, g.cond())
		} else {
			g.w("%sif %s { continue; }\n", in, g.cond())
		}
	case choice < 88 && canNest:
		g.w("%sif %s { return %s; }\n", in, g.cond(), g.expr(2))
	case choice < 90 && g.callee > 0:
		g.w("%s%s;\n", in, g.call(g.cfg.ExprDepth-1))
	default:
		vs := g.vars(true)
		v := vs[g.r.Intn(len(vs))]
		g.w("%s%s = %s %s %s;\n", in, v, v, []string{"+", "-", "^", "*"}[g.r.Intn(4)], g.atom())
	}
}

func (g *gen) cond() string {
	if g.r.Intn(4) == 0 {
		return fmt.Sprintf("%s %s %s", g.cmp(), []string{"&&", "||"}[g.r.Intn(2)], g.cmp())
	}
	return g.cmp()
}

func (g *gen) cmp() string {
	return fmt.Sprintf("%s %s %s", g.expr(1), []string{"<", "<=", ">", ">=", "==", "!="}[g.r.Intn(6)], g.expr(1))
}

func (g *gen) atom() string {
	vs := g.vars(false)
	if len(vs) > 0 && g.r.Intn(3) != 0 {
		return vs[g.r.Intn(len(vs))]
	}
	return interesting[g.r.Intn(len(interesting))]
}

func (g *gen) call(depth int) string {
	k := g.r.Intn(g.callee)
	var as []string
	for i := 0; i < g.arity[k]; i++ {
		as = append(as, g.expr(depth))
	}
	return fmt.Sprintf("f%d(%s)", k, strings.Join(as, ", "))
}

var binOps = []string{"+", "+", "-", "-", "*", "&", "|", "^", "<<", ">>", "<", "<=", ">", ">=", "==", "!=", "/", "%", "&&", "||"}

func (g *gen) expr(depth int) string {
	if depth <= 0 || g.r.Intn(5) == 0 {
		return g.atom()
	}
	switch g.r.Intn(12) {
	case 0:
		return fmt.Sprintf("(-%s)", g.expr(depth-1))
	case 1:
		return fmt.Sprintf("(!%s)", g.expr(depth-1))
	case 2:
		return fmt.Sprintf("(~%s)", g.expr(depth-1))
	case 3:
		if g.callee > 0 {
			return g.call(depth - 1)
		}
	}
	op := binOps[g.r.Intn(len(binOps))]
	l, r := g.expr(depth-1), g.expr(depth-1)
	if (op == "/" || op == "%") && g.r.Intn(100) >= g.cfg.TrapRate {
		r = fmt.Sprintf("((%s) | 1)", r)
	}
	return fmt.Sprintf("(%s %s %s)", l, op, r)
}

// ---- differential fuzzing ----

// Finding describes one divergence found by the fuzzer.
type Finding struct {
	Seed   int64
	Source string
	Where  string
	Detail string
}

func (f Finding) String() string {
	return fmt.Sprintf("seed %d: %s\n%s\n--- program ---\n%s", f.Seed, f.Where, f.Detail, f.Source)
}

// FuzzOne generates the program for seed, runs it through every executor and
// returns a Finding if anything disagrees with the oracle (or the compiler errors).
func FuzzOne(seed int64, cfg GenConfig) *Finding {
	src := GenProgram(seed, cfg)
	fail := func(where, format string, a ...any) *Finding {
		return &Finding{Seed: seed, Source: src, Where: where, Detail: fmt.Sprintf(format, a...)}
	}
	ast, err := Parse(src)
	if err != nil {
		return fail("generator", "generated program does not parse: %v", err)
	}
	var res *CheckResult
	var cerr error
	func() {
		defer func() {
			if r := recover(); r != nil {
				cerr = fmt.Errorf("compiler panic: %v", r)
			}
		}()
		res, cerr = CheckAST(ast)
	}()
	if cerr != nil {
		return fail("compile", "%v", cerr)
	}
	for _, row := range res.Rows {
		if row.Skipped == "" && !row.Match {
			where := row.Name
			detail := fmt.Sprintf("oracle %v, executor %v", res.Oracle, row.Outcome)
			if strings.HasPrefix(row.Name, "SSA -O") {
				if p := BisectPass(ast); p != "" {
					detail += "\nfirst divergent pass: " + p
				}
			}
			return fail(where, "%s", detail)
		}
	}
	return nil
}

// BisectPass finds the first optimisation pass application (at -O2) after which
// the IR no longer agrees with the oracle.
func BisectPass(ast *Program) string {
	want := RunAST(ast, checkFuel)
	m := Lower(ast)
	if BuildSSA(m) != nil {
		return "mem2reg"
	}
	if !RunIR(m, (want.Steps*50 + 1_000_000)).Same(want) {
		return "mem2reg"
	}
	full, _ := Optimize(m.Clone(), Options{Level: 2})
	for n := 1; n <= full.Applied; n++ {
		mm := Lower(ast)
		_ = BuildSSA(mm)
		st, err := Optimize(mm, Options{Level: 2, MaxPasses: n})
		if err != nil {
			return fmt.Sprintf("%v (after pass #%d)", err, n)
		}
		if got := RunIR(mm, (want.Steps*50 + 1_000_000)); !got.Resource() && !got.Same(want) && len(st.Rows) > 0 {
			r := st.Rows[len(st.Rows)-1]
			return fmt.Sprintf("%s on %s (round %d, pass #%d)", r.Pass, r.Func, r.Round, n)
		}
	}
	return ""
}
