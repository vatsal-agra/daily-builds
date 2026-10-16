// Package fuzz generates random terminating Dom programs and checks every compiler configuration
// against the reference interpreter (differential testing), with automatic test-case reduction.
package fuzz

import (
	"fmt"
	"math/rand"
	"strings"
)

type variable struct {
	name     string
	readOnly bool // loop counters: never assigned, so every loop terminates
}

type arrayVar struct {
	name string
	size int
}

type gen struct {
	r         *rand.Rand
	sb        strings.Builder
	indent    int
	scopes    [][]variable
	arrays    []arrayVar
	nvar      int
	curFn     int
	loopDepth int
	inLoop    bool
	budget    int // statements left in the current function
	nfuncs    int
	arity     []int
}

var interesting = []int64{0, 0, 1, 1, 2, 3, 5, 7, 8, 10, 16, 31, 63, 64, 100, 255, 1000, 65536, 2147483647, 4294967296,
	-1, -2, -7, -128, 9223372036854775807}

func (g *gen) w(format string, a ...any) {
	g.sb.WriteString(strings.Repeat("    ", g.indent))
	fmt.Fprintf(&g.sb, format, a...)
	g.sb.WriteByte('\n')
}

func (g *gen) push() { g.scopes = append(g.scopes, nil) }
func (g *gen) pop()  { g.scopes = g.scopes[:len(g.scopes)-1] }

func (g *gen) declare(v variable) { g.scopes[len(g.scopes)-1] = append(g.scopes[len(g.scopes)-1], v) }

func (g *gen) vars(writable bool) []variable {
	var out []variable
	for _, s := range g.scopes {
		for _, v := range s {
			if !writable || !v.readOnly {
				out = append(out, v)
			}
		}
	}
	return out
}

func (g *gen) fresh(prefix string) string { g.nvar++; return fmt.Sprintf("%s%d", prefix, g.nvar) }

func (g *gen) constant() string {
	if g.r.Intn(4) == 0 {
		return fmt.Sprint(g.r.Intn(2000) - 1000)
	}
	return fmt.Sprint(interesting[g.r.Intn(len(interesting))])
}

var binOps = []string{"+", "+", "-", "-", "*", "&", "|", "^", "<", "<=", ">", ">=", "==", "!=", "<<", ">>", "&&", "||"}

func (g *gen) expr(depth int) string {
	vs := g.vars(false)
	if depth <= 0 || g.r.Intn(6) == 0 {
		if len(vs) > 0 && g.r.Intn(3) != 0 {
			return vs[g.r.Intn(len(vs))].name
		}
		return g.constant()
	}
	switch k := g.r.Intn(14); {
	case k < 6:
		op := binOps[g.r.Intn(len(binOps))]
		l, r := g.expr(depth-1), g.expr(depth-1)
		if op == "<<" || op == ">>" {
			if g.r.Intn(8) != 0 {
				r = fmt.Sprintf("(%s & 63)", r)
			}
		}
		return fmt.Sprintf("(%s %s %s)", l, op, r)
	case k == 6:
		return fmt.Sprintf("(%s / (%s | 1))", g.expr(depth-1), g.expr(depth-1))
	case k == 7:
		return fmt.Sprintf("(%s %% (%s | 1))", g.expr(depth-1), g.expr(depth-1))
	case k == 8:
		if g.r.Intn(80) == 0 { // unguarded: may trap with division by zero
			return fmt.Sprintf("(%s / %s)", g.expr(depth-1), g.expr(depth-1))
		}
		return fmt.Sprintf("(%s / %d)", g.expr(depth-1), g.r.Intn(9)+1)
	case k == 9:
		return fmt.Sprintf("%s%s", []string{"-", "~", "!"}[g.r.Intn(3)], g.paren(g.expr(depth-1)))
	case k == 10 && len(g.arrays) > 0:
		a := g.arrays[g.r.Intn(len(g.arrays))]
		return fmt.Sprintf("%s[(%s) & %d]", a.name, g.expr(depth-1), a.size-1)
	case k == 11 && g.curFn > 0 && (g.loopDepth == 0 || g.r.Intn(3) == 0):
		j := g.r.Intn(g.curFn)
		var as []string
		for i := 0; i < g.arity[j]; i++ {
			as = append(as, g.expr(depth-1))
		}
		return fmt.Sprintf("f%d(%s)", j, strings.Join(as, ", "))
	case k == 12:
		return fmt.Sprintf("(%s - %s)", g.expr(depth-1), g.expr(depth-1))
	default:
		op := binOps[g.r.Intn(8)]
		return fmt.Sprintf("(%s %s %s)", g.expr(depth-1), op, g.expr(depth-1))
	}
}

func (g *gen) paren(s string) string {
	if strings.HasPrefix(s, "(") {
		return s
	}
	return "(" + s + ")"
}

func (g *gen) block(depth int, n int) {
	g.push()
	g.indent++
	for i := 0; i < n && g.budget > 0; i++ {
		g.stmt(depth)
	}
	g.indent--
	g.pop()
}

func (g *gen) stmt(depth int) {
	g.budget--
	ws := g.vars(true)
	switch k := g.r.Intn(20); {
	case k < 3 || len(ws) == 0:
		n := g.fresh("v")
		g.w("var %s = %s;", n, g.expr(3))
		g.declare(variable{name: n})
	case k < 7:
		v := ws[g.r.Intn(len(ws))]
		switch g.r.Intn(4) {
		case 0:
			g.w("%s += %s;", v.name, g.expr(2))
		case 1:
			g.w("%s -= %s;", v.name, g.expr(2))
		case 2:
			g.w("%s *= %s;", v.name, g.expr(2))
		default:
			g.w("%s = %s;", v.name, g.expr(3))
		}
	case k < 10 && len(g.arrays) > 0:
		a := g.arrays[g.r.Intn(len(g.arrays))]
		g.w("%s[(%s) & %d] = %s;", a.name, g.expr(2), a.size-1, g.expr(3))
	case k < 12:
		g.w("print(%s);", g.expr(3))
	case k < 15 && depth > 0:
		g.w("if %s {", g.expr(3))
		g.block(depth-1, 1+g.r.Intn(3))
		if g.r.Intn(2) == 0 {
			g.w("} else {")
			g.block(depth-1, 1+g.r.Intn(3))
		}
		g.w("}")
	case k < 17 && depth > 0 && g.loopDepth < 3:
		iv := g.fresh("i")
		trip := 1 + g.r.Intn(5)
		if g.loopDepth == 0 {
			trip += g.r.Intn(12)
		}
		step := 1
		if g.r.Intn(4) == 0 {
			step = 2
		}
		g.w("for var %s = 0; %s < %d; %s += %d {", iv, iv, trip, iv, step)
		g.push()
		g.declare(variable{name: iv, readOnly: true})
		g.loopDepth++
		save := g.inLoop
		g.inLoop = true
		g.block(depth-1, 1+g.r.Intn(4))
		g.inLoop = save
		g.loopDepth--
		g.pop()
		g.w("}")
	case k < 18 && depth > 0 && g.loopDepth < 3:
		cn := g.fresh("w")
		g.w("var %s = %d;", cn, 1+g.r.Intn(8))
		g.declare(variable{name: cn, readOnly: true})
		g.w("while %s > 0 {", cn)
		g.indent++
		g.w("%s -= 1;", cn)
		g.indent--
		g.loopDepth++
		save := g.inLoop
		g.inLoop = true
		g.block(depth-1, 1+g.r.Intn(3))
		g.inLoop = save
		g.loopDepth--
		g.w("}")
	case k < 19 && g.inLoop:
		if g.r.Intn(2) == 0 {
			g.w("if %s { break; }", g.expr(2))
		} else {
			g.w("if %s { continue; }", g.expr(2))
		}
	default:
		if g.curFn > 0 && g.r.Intn(3) == 0 {
			g.w("return %s;", g.expr(3))
		} else {
			g.w("print(%s);", g.expr(2))
		}
	}
}

// Generate returns the source of a random program for the seed.
func Generate(seed int64) string {
	g := &gen{r: rand.New(rand.NewSource(seed))}
	g.nfuncs = 1 + g.r.Intn(4)
	for i := 0; i < g.nfuncs; i++ {
		g.arity = append(g.arity, g.r.Intn(4))
	}
	for fi := 0; fi <= g.nfuncs; fi++ {
		g.curFn = fi
		g.scopes = nil
		g.arrays = nil
		g.loopDepth = 0
		g.inLoop = false
		g.budget = 6 + g.r.Intn(18)
		g.push()
		name := fmt.Sprintf("f%d", fi)
		var ps []string
		if fi == g.nfuncs {
			name = "main"
		} else {
			for p := 0; p < g.arity[fi]; p++ {
				pn := fmt.Sprintf("p%d", p)
				ps = append(ps, pn)
				g.declare(variable{name: pn})
			}
		}
		g.w("fn %s(%s) {", name, strings.Join(ps, ", "))
		g.indent++
		for a := 0; a < g.r.Intn(3); a++ {
			sz := []int{2, 4, 8, 16}[g.r.Intn(4)]
			an := fmt.Sprintf("a%d", a)
			g.w("var %s[%d];", an, sz)
			g.arrays = append(g.arrays, arrayVar{an, sz})
		}
		for g.budget > 0 {
			g.stmt(3)
		}
		g.w("return %s;", g.expr(3))
		g.indent--
		g.w("}")
		g.pop()
	}
	return g.sb.String()
}
