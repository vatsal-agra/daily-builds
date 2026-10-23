package elab_test

import (
	"fmt"
	"math/big"
	"math/rand"
	"strings"
	"testing"

	"gatecraft/internal/aig"
	"gatecraft/internal/hdl"
	"gatecraft/internal/testutil"
)

// ---- independent reference interpreter: math/big, Verilog context-width rules ----

type refEnv map[string]*big.Int

var sigWidth = map[string]int{}

func rmask(w int) *big.Int {
	return new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(w)), big.NewInt(1))
}
func trunc(v *big.Int, w int) *big.Int {
	return new(big.Int).And(v, rmask(w))
}
func rb(b bool) *big.Int {
	if b {
		return big.NewInt(1)
	}
	return big.NewInt(0)
}

func selfW(e hdl.Expr) int {
	switch e := e.(type) {
	case *hdl.Number:
		if e.Width > 0 {
			return e.Width
		}
		return max(32, e.Val.BitLen())
	case *hdl.Ident:
		return sigWidth[e.Name]
	case *hdl.Index:
		switch e.Part {
		case 0:
			return 1
		default:
			hi, lo := int(e.Hi.(*hdl.Number).Val.Int64()), int(e.Lo.(*hdl.Number).Val.Int64())
			return hi - lo + 1
		}
	case *hdl.Unary:
		if e.Op == "~" || e.Op == "-" || e.Op == "+" {
			return selfW(e.X)
		}
		return 1
	case *hdl.Binary:
		switch e.Op {
		case "<<", ">>":
			return selfW(e.L)
		case "==", "!=", "<", "<=", ">", ">=", "&&", "||":
			return 1
		}
		return max(selfW(e.L), selfW(e.R))
	case *hdl.Ternary:
		return max(selfW(e.T), selfW(e.F))
	case *hdl.Concat:
		n := 0
		for _, p := range e.Parts {
			n += selfW(p)
		}
		return n
	case *hdl.Repl:
		return int(e.Count.(*hdl.Number).Val.Int64()) * selfW(e.X)
	}
	panic("selfW")
}

// ev evaluates e in a context of width w (w >= selfW(e) unless explicitly truncating).
func ev(e hdl.Expr, w int, env refEnv) *big.Int {
	switch e := e.(type) {
	case *hdl.Number:
		return trunc(e.Val, w)
	case *hdl.Ident:
		return trunc(env[e.Name], w)
	case *hdl.Index:
		v := env[e.X.(*hdl.Ident).Name]
		if e.Part == 0 {
			if n, ok := e.Hi.(*hdl.Number); ok {
				return trunc(rb(v.Bit(int(n.Val.Int64())) == 1), w)
			}
			// dynamic index: out of range reads 0
			ix := ev(e.Hi, selfW(e.Hi), env)
			if ix.IsInt64() && ix.Int64() < int64(sigWidth[e.X.(*hdl.Ident).Name]) {
				return trunc(rb(v.Bit(int(ix.Int64())) == 1), w)
			}
			return big.NewInt(0)
		}
		hi, lo := int(e.Hi.(*hdl.Number).Val.Int64()), int(e.Lo.(*hdl.Number).Val.Int64())
		return trunc(new(big.Int).Rsh(trunc(v, hi+1), uint(lo)), w)
	case *hdl.Unary:
		switch e.Op {
		case "~":
			return trunc(new(big.Int).Not(ev(e.X, w, env)), w)
		case "-":
			return trunc(new(big.Int).Neg(ev(e.X, w, env)), w)
		case "+":
			return ev(e.X, w, env)
		}
		sw := selfW(e.X)
		x := ev(e.X, sw, env)
		var r bool
		switch e.Op {
		case "!":
			r = x.Sign() == 0
		case "&":
			r = x.Cmp(rmask(sw)) == 0
		case "|":
			r = x.Sign() != 0
		case "^":
			r = popcount(x)%2 == 1
		case "~&":
			r = x.Cmp(rmask(sw)) != 0
		case "~|":
			r = x.Sign() == 0
		case "~^":
			r = popcount(x)%2 == 0
		}
		return trunc(rb(r), w)
	case *hdl.Binary:
		switch e.Op {
		case "+", "-", "*", "/", "%", "&", "|", "^", "~^":
			l, r := ev(e.L, w, env), ev(e.R, w, env)
			z := new(big.Int)
			switch e.Op {
			case "+":
				z.Add(l, r)
			case "-":
				z.Sub(l, r)
			case "*":
				z.Mul(l, r)
			case "/":
				if r.Sign() == 0 {
					return rmask(w)
				}
				z.Quo(l, r)
			case "%":
				if r.Sign() == 0 {
					return l
				}
				z.Rem(l, r)
			case "&":
				z.And(l, r)
			case "|":
				z.Or(l, r)
			case "^":
				z.Xor(l, r)
			case "~^":
				z.Xor(l, r)
				z.Not(z)
			}
			return trunc(z, w)
		case "<<", ">>":
			l := ev(e.L, w, env)
			r := ev(e.R, selfW(e.R), env)
			if r.Cmp(big.NewInt(int64(w))) >= 0 {
				return big.NewInt(0)
			}
			if e.Op == "<<" {
				return trunc(new(big.Int).Lsh(l, uint(r.Int64())), w)
			}
			return new(big.Int).Rsh(l, uint(r.Int64()))
		case "&&", "||":
			l := ev(e.L, selfW(e.L), env).Sign() != 0
			r := ev(e.R, selfW(e.R), env).Sign() != 0
			if e.Op == "&&" {
				return trunc(rb(l && r), w)
			}
			return trunc(rb(l || r), w)
		default:
			m := max(selfW(e.L), selfW(e.R))
			c := ev(e.L, m, env).Cmp(ev(e.R, m, env))
			var r bool
			switch e.Op {
			case "==":
				r = c == 0
			case "!=":
				r = c != 0
			case "<":
				r = c < 0
			case "<=":
				r = c <= 0
			case ">":
				r = c > 0
			case ">=":
				r = c >= 0
			}
			return trunc(rb(r), w)
		}
	case *hdl.Ternary:
		if ev(e.C, selfW(e.C), env).Sign() != 0 {
			return ev(e.T, w, env)
		}
		return ev(e.F, w, env)
	case *hdl.Concat:
		acc := new(big.Int)
		for _, p := range e.Parts {
			pw := selfW(p)
			acc.Lsh(acc, uint(pw))
			acc.Or(acc, ev(p, pw, env))
		}
		return trunc(acc, w)
	case *hdl.Repl:
		n := int(e.Count.(*hdl.Number).Val.Int64())
		pw := selfW(e.X)
		inner := ev(e.X, pw, env)
		acc := new(big.Int)
		for i := 0; i < n; i++ {
			acc.Lsh(acc, uint(pw))
			acc.Or(acc, inner)
		}
		return trunc(acc, w)
	}
	panic("ev")
}

func popcount(x *big.Int) int {
	n := 0
	for i := 0; i < x.BitLen(); i++ {
		n += int(x.Bit(i))
	}
	return n
}

// ---- random expression text generator ----

type gen struct {
	rng   *rand.Rand
	names []string // readable signals
}

func (g *gen) sig() string { return g.names[g.rng.Intn(len(g.names))] }

func (g *gen) lit() string {
	switch g.rng.Intn(4) {
	case 0:
		return fmt.Sprintf("%d", g.rng.Intn(40))
	case 1:
		w := 1 + g.rng.Intn(10)
		return fmt.Sprintf("%d'd%d", w, g.rng.Intn(1<<uint(w)))
	case 2:
		return fmt.Sprintf("8'h%02x", g.rng.Intn(256))
	}
	return fmt.Sprintf("%d'b%b", 4, g.rng.Intn(16))
}

func (g *gen) sized() string { // self-determined sized operand for concatenations
	switch g.rng.Intn(4) {
	case 0:
		return g.sig()
	case 1:
		return g.slice()
	case 2:
		return fmt.Sprintf("%d'd%d", 4, g.rng.Intn(16))
	}
	return "(" + g.expr(1) + ")" // may be wide; self-determined
}

func (g *gen) slice() string {
	s := g.sig()
	w := sigWidth[s]
	if w == 1 {
		return s
	}
	if g.rng.Intn(2) == 0 {
		return fmt.Sprintf("%s[%d]", s, g.rng.Intn(w))
	}
	hi := g.rng.Intn(w)
	lo := g.rng.Intn(hi + 1)
	return fmt.Sprintf("%s[%d:%d]", s, hi, lo)
}

func (g *gen) expr(depth int) string {
	if depth <= 0 || g.rng.Intn(5) == 0 {
		switch g.rng.Intn(5) {
		case 0:
			return g.lit()
		case 1:
			return g.slice()
		}
		return g.sig()
	}
	bin := []string{"+", "-", "*", "/", "%", "&", "|", "^", "~^", "<<", ">>", "==", "!=", "<", "<=", ">", ">=", "&&", "||"}
	switch g.rng.Intn(9) {
	case 0:
		un := []string{"~", "-", "!", "&", "|", "^", "~&", "~|", "~^", "+"}
		return fmt.Sprintf("(%s%s)", un[g.rng.Intn(len(un))], g.expr(depth-1))
	case 1:
		return fmt.Sprintf("(%s ? %s : %s)", g.expr(depth-1), g.expr(depth-1), g.expr(depth-1))
	case 2:
		return fmt.Sprintf("{%s, %s}", g.sized(), g.sized())
	case 3:
		return fmt.Sprintf("{%d{%s}}", 1+g.rng.Intn(3), g.sized())
	case 4:
		s := g.sig()
		return fmt.Sprintf("%s[%s]", s, g.sig()) // dynamic bit select
	}
	return fmt.Sprintf("(%s %s %s)", g.expr(depth-1), bin[g.rng.Intn(len(bin))], g.expr(depth-1))
}

func TestExpressionsAgainstBigIntReference(t *testing.T) {
	rng := rand.New(rand.NewSource(20261023))
	g := &gen{rng: rng, names: []string{"a", "b", "c", "d", "e"}}
	sigWidth = map[string]int{"a": 1, "b": 3, "c": 8, "d": 13, "e": 5}
	const N = 700
	for it := 0; it < N; it++ {
		ow := 1 + rng.Intn(20)
		text := g.expr(1 + rng.Intn(4))
		src := fmt.Sprintf("module m(input a, input [2:0] b, input [7:0] c, input [12:0] d, input [4:0] e, output [%d:0] y);\n assign y = %s;\nendmodule", ow-1, text)
		f, err := hdl.Parse("fuzz.v", src)
		if err != nil {
			t.Fatalf("parse %q: %v", text, err)
		}
		rhs := f.Modules[0].Assigns[0].RHS
		gr, err := testutil.Try(src, "")
		if err != nil {
			if strings.Contains(err.Error(), "out of range") || strings.Contains(err.Error(), "unsized number") {
				continue
			}
			t.Fatalf("elab %q: %v", text, err)
		}
		s := aig.NewSimulator(gr)
		// 64 random lanes
		lane := make([]refEnv, 64)
		for k := range lane {
			lane[k] = refEnv{}
		}
		for _, p := range gr.Inputs {
			for k := 0; k < 64; k++ {
				lane[k][p.Name] = new(big.Int)
			}
			for bi, b := range p.Bits {
				w := rng.Uint64()
				pi := gr.PIs[gr.Nodes[b.ID()].Idx]
				for idx := range gr.PIs {
					if gr.PIs[idx] == pi {
						s.SetPI(idx, w)
					}
				}
				for k := 0; k < 64; k++ {
					if w>>uint(k)&1 == 1 {
						lane[k][p.Name].SetBit(lane[k][p.Name], bi, 1)
					}
				}
			}
		}
		s.Eval()
		cw := max(ow, selfW(rhs))
		for k := 0; k < 64; k++ {
			want := trunc(ev(rhs, cw, lane[k]), ow)
			got := new(big.Int)
			for i, b := range gr.Outputs[0].Bits {
				if s.Lit(b)>>uint(k)&1 == 1 {
					got.SetBit(got, i, 1)
				}
			}
			if got.Cmp(want) != 0 {
				t.Fatalf("expr %q (out %d bits) lane inputs %v: got %s want %s", text, ow, lane[k], got, want)
			}
		}
	}
}
