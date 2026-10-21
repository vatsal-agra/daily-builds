package main

import (
	"math/big"
	"math/rand"
	"os"
	"strconv"
	"strings"
	"testing"
)

var tm = func() *Machine { m := newMachine(); m.loadLibrary(); return m }()

var weirdAtoms = []string{"a", "foo", "Bar", "hello world", "[]", "{}", "!", ";", ",", "|", "+", "-", "*", "\\", "\\+", "=", ":-", "-->", "->",
	"mod", "is", "dynamic", "'", "\\n", "a'b", "é", "", "[", "]", "()", "1a", "_x", "a.b", ".", "..", "/*", "%", "$", "^", "**", "<", "=..", "@", "#", "f(x)", "∀"}

func randTerm(r *rand.Rand, depth int, vars []*Var) Term {
	k := r.Intn(10)
	if depth <= 0 {
		k = r.Intn(5)
	}
	switch k {
	case 0:
		return mkAtom(weirdAtoms[r.Intn(len(weirdAtoms))])
	case 1:
		switch r.Intn(4) {
		case 0:
			return Int(r.Int63n(2000) - 1000)
		case 1:
			return normBig(new(big.Int).Lsh(big.NewInt(r.Int63()), uint(r.Intn(80))))
		case 2:
			return Int(r.Intn(10))
		default:
			return Int(-r.Int63n(1 << 40))
		}
	case 2:
		return Float([]float64{0.5, -1.5, 3.0, 1e10, 1.5e-7, -0.0, 123456.789, 1e22, 2.5e-300}[r.Intn(9)])
	case 3:
		if len(vars) > 0 {
			return vars[r.Intn(len(vars))]
		}
		return mkAtom("v")
	case 4:
		return mkAtom([]string{"x", "y", "z", "nil"}[r.Intn(4)])
	case 5, 6:
		n := r.Intn(3) + 1
		args := make([]Term, n)
		for i := range args {
			args[i] = randTerm(r, depth-1, vars)
		}
		names := []string{"f", "g", "-", "+", "*", ":-", ",", ";", "->", "=", "\\+", "-", "mod", "^", "**", "a b", "dynamic", "is", ":", "|", "[]", "{}", "$VAR"}
		return &Compound{Fn: mkAtom(names[r.Intn(len(names))]), Args: args}
	case 7:
		n := r.Intn(4)
		items := make([]Term, n)
		for i := range items {
			items[i] = randTerm(r, depth-1, vars)
		}
		var tail Term = atNil
		if r.Intn(4) == 0 {
			tail = randTerm(r, depth-1, vars)
		}
		return mkList(items, tail)
	case 8:
		return &Compound{Fn: atCurly, Args: []Term{randTerm(r, depth-1, vars)}}
	}
	return &Compound{Fn: mkAtom([]string{"-", "+", "\\", "\\+", "?-"}[r.Intn(5)]), Args: []Term{randTerm(r, depth-1, vars)}}
}

func TestWriteReadRoundTrip(t *testing.T) {
	r := rand.New(rand.NewSource(seedFromEnv(42)))
	bad := 0
	for i := 0; i < roundTripN(); i++ {
		vars := []*Var{tm.newVar(), tm.newVar()}
		term := randTerm(r, 4, vars)
		// '$VAR'(N) is written as a letter under numbervars; skip those for the round trip
		text := formatTermOpts(term, writeOpts{quoted: true})
		rd := newReader(tm, strings.NewReader(text+" ."))
		got, err := rd.ReadTerm()
		if err != nil {
			bad++
			if bad <= 8 {
				t.Errorf("parse failed: %q: %v", text, err)
			}
			continue
		}
		if !variant(term, got) {
			bad++
			if bad <= 8 {
				t.Errorf("round trip mismatch:\n  in : %q\n  out: %q", text, formatTermOpts(got, writeOpts{quoted: true}))
			}
		}
	}
	if bad > 0 {
		t.Fatalf("%d round-trip failures", bad)
	}
}

func TestArithAgainstBig(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	ops := []string{"+", "-", "*", "//", "mod", "rem", "div", "gcd", "/\\", "\\/", "xor"}
	for i := 0; i < 5000; i++ {
		mk1 := func() *big.Int {
			b := new(big.Int).Rand(r, new(big.Int).Lsh(big.NewInt(1), uint(r.Intn(100)+1)))
			if r.Intn(2) == 0 {
				b.Neg(b)
			}
			return b
		}
		a, b := mk1(), mk1()
		op := ops[r.Intn(len(ops))]
		if (op == "//" || op == "mod" || op == "rem" || op == "div") && b.Sign() == 0 {
			continue
		}
		want := new(big.Int)
		switch op {
		case "+":
			want.Add(a, b)
		case "-":
			want.Sub(a, b)
		case "*":
			want.Mul(a, b)
		case "//":
			want.Quo(a, b)
		case "rem":
			want.Rem(a, b)
		case "mod":
			want.Rem(a, b)
			if want.Sign() != 0 && (want.Sign() < 0) != (b.Sign() < 0) {
				want.Add(want, b)
			}
		case "div":
			want = floorDivBig(a, b)
		case "gcd":
			want.GCD(nil, nil, new(big.Int).Abs(a), new(big.Int).Abs(b))
		case "/\\":
			want.And(a, b)
		case "\\/":
			want.Or(a, b)
		case "xor":
			want.Xor(a, b)
		}
		expr := &Compound{Fn: mkAtom(op), Args: []Term{normBig(a), normBig(b)}}
		got, err := tm.eval(expr)
		if err != nil {
			t.Fatalf("%v %s %v: %v", a, op, b, err)
		}
		if cmpNum(got, normBig(want)) != 0 {
			t.Fatalf("%v %s %v = %v, want %v", a, op, b, got, want)
		}
	}
}

func TestStandardOrderIsTotal(t *testing.T) {
	r := rand.New(rand.NewSource(3))
	var ts []Term
	vars := []*Var{tm.newVar(), tm.newVar(), tm.newVar()}
	for i := 0; i < 300; i++ {
		ts = append(ts, randTerm(r, 3, vars))
	}
	for i := 0; i < 20000; i++ {
		a, b, c := ts[r.Intn(len(ts))], ts[r.Intn(len(ts))], ts[r.Intn(len(ts))]
		ab, ba := compareTerms(a, b), compareTerms(b, a)
		if ab != -ba {
			t.Fatalf("antisymmetry violated: %s vs %s: %d %d", formatTerm(a, true), formatTerm(b, true), ab, ba)
		}
		if ab <= 0 && compareTerms(b, c) <= 0 && compareTerms(a, c) > 0 {
			t.Fatalf("transitivity violated: %s %s %s", formatTerm(a, true), formatTerm(b, true), formatTerm(c, true))
		}
	}
}

func TestUnifyMakesTermsIdentical(t *testing.T) {
	r := rand.New(rand.NewSource(11))
	for i := 0; i < 5000; i++ {
		vars := []*Var{tm.newVar(), tm.newVar(), tm.newVar()}
		a, b := randTerm(r, 3, vars), randTerm(r, 3, vars)
		mark := len(tm.trail)
		oldhb := tm.hb
		tm.hb = 1 << 62
		ok := tm.unify(a, b)
		same := compareTerms(a, b) == 0
		tm.undoTrail(mark)
		tm.hb = oldhb
		if ok != same && ok {
			t.Fatalf("unify succeeded but terms differ: %s / %s", formatTerm(a, true), formatTerm(b, true))
		}
		if ok && !tm.tryUnify(a, b) {
			t.Fatalf("unify not repeatable")
		}
	}
}

func TestSortTerms(t *testing.T) {
	r := rand.New(rand.NewSource(5))
	for i := 0; i < 200; i++ {
		var ts []Term
		for j := 0; j < 30; j++ {
			ts = append(ts, randTerm(r, 2, nil))
		}
		s := sortTerms(append([]Term(nil), ts...), true)
		for j := 1; j < len(s); j++ {
			if compareTerms(s[j-1], s[j]) >= 0 {
				t.Fatalf("sort/2 output not strictly ascending")
			}
		}
	}
}

func seedFromEnv(def int64) int64 {
	if v, err := strconv.ParseInt(os.Getenv("HORN_SEED"), 10, 64); err == nil {
		return v
	}
	return def
}

func roundTripN() int {
	if v, err := strconv.Atoi(os.Getenv("HORN_FUZZ_N")); err == nil {
		return v
	}
	return 20000
}
