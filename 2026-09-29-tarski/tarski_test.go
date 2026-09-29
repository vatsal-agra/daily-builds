package main

import (
	"bytes"
	"fmt"
	"strings"
	"testing"
)

func mustEngine(t *testing.T, src string) *Engine {
	t.Helper()
	e, err := build(src)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	if err := e.Run(); err != nil {
		t.Fatalf("run: %v", err)
	}
	return e
}

func ask(t *testing.T, e *Engine, q string) string {
	t.Helper()
	p, err := Parse(q)
	if err != nil {
		t.Fatal(err)
	}
	r, err := e.Ask(p.Queries[0])
	if err != nil {
		t.Fatalf("ask %s: %v", q, err)
	}
	return r.Format()
}

// ---- feature 1: parser ----

func TestParserBasics(t *testing.T) {
	p, err := Parse(`% c
/* block */ p(a, "s t", -4, X, _) :- q(X), not r(X), X >= 1 + 2 * 3, Y = X mod 2. // tail
?- p(A,B,C,D,E).
z.`)
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Rules) != 2 || len(p.Queries) != 1 {
		t.Fatalf("rules=%d queries=%d", len(p.Rules), len(p.Queries))
	}
	r := p.Rules[0]
	if len(r.Body) != 4 || r.Body[1].Kind != LNeg || r.Body[2].Kind != LCmp {
		t.Fatalf("bad body %v", r.Body)
	}
	if got := r.Body[2].R.String(); got != "(1 + (2 * 3))" {
		t.Fatalf("precedence: %s", got)
	}
	if r.Head.Args[2].C != Int(-4) || r.Head.Args[1].C != Str("s t") {
		t.Fatalf("head consts: %v", r.Head.Args)
	}
	if p.Rules[1].Head.Pred != "z" || len(p.Rules[1].Head.Args) != 0 {
		t.Fatal("zero-arity fact")
	}
}

func TestParserErrors(t *testing.T) {
	cases := map[string]string{
		"p(X) :- q(X)":             "expected \".\"",
		"p(X :- q.":                "expected \")\"",
		"p() .":                    "empty argument list",
		"p(X) :- X 3.":             "comparison operator",
		"P(x).":                    "predicate name",
		"p(\"abc":                  "unterminated string",
		"/* nope":                  "unterminated block comment",
		"p(1) $ q.":                "unexpected character",
		"p(99999999999999999999).": "out of range",
		"p(sum(*)) :- q.":          "needs a variable",
	}
	for src, want := range cases {
		_, err := Parse(src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: got %v, want substring %q", src, err, want)
		}
	}
	_, err := Parse("a(1).\nb(2) :-\n  c(3) d.")
	pe, ok := err.(*ParseError)
	if !ok || pe.Line != 3 {
		t.Fatalf("line tracking: %v", err)
	}
}

// ---- feature 2: semi-naive recursion ----

func chainProg(n int, rec string) string {
	var b strings.Builder
	for i := 0; i < n-1; i++ {
		fmt.Fprintf(&b, "edge(%d,%d).\n", i, i+1)
	}
	return b.String() + "path(X,Y) :- edge(X,Y).\n" + rec
}

func TestTransitiveClosureCounts(t *testing.T) {
	for _, rec := range []string{"path(X,Z) :- path(X,Y), edge(Y,Z).", "path(X,Z) :- edge(X,Y), path(Y,Z).", "path(X,Z) :- path(X,Y), path(Y,Z)."} {
		e := mustEngine(t, chainProg(30, rec))
		if got := len(e.Rels["path"].Tuples); got != 30*29/2 {
			t.Errorf("%s: %d paths, want %d", rec, got, 30*29/2)
		}
	}
}

func TestMutualRecursion(t *testing.T) {
	e := mustEngine(t, `next(0,1). next(1,2). next(2,3). next(3,4). next(4,5).
even(0).
even(N) :- odd(M), next(M,N).
odd(N) :- even(M), next(M,N).`)
	if got := ask(t, e, "?- even(X)."); got != "X = 0\nX = 2\nX = 4\n(3 answers)\n" {
		t.Fatalf("even: %q", got)
	}
	if got := ask(t, e, "?- odd(X)."); got != "X = 1\nX = 3\nX = 5\n(3 answers)\n" {
		t.Fatalf("odd: %q", got)
	}
}

func TestSemiNaiveDoesLessWorkSameModel(t *testing.T) {
	src := chainProg(60, "path(X,Z) :- path(X,Y), edge(Y,Z).")
	a, b := mustEngine(t, src), mustEngine(t, src)
	_ = a
	n, err := build(src)
	if err != nil {
		t.Fatal(err)
	}
	n.Naive = true
	if err := n.Run(); err != nil {
		t.Fatal(err)
	}
	if !sameModel(n, b) {
		t.Fatal("models differ")
	}
	if b.Stats.Probes*10 > n.Stats.Probes {
		t.Fatalf("semi-naive should probe >10x less: %d vs %d", b.Stats.Probes, n.Stats.Probes)
	}
}

func TestSelfJoinAndConstants(t *testing.T) {
	e := mustEngine(t, `e(1,1). e(1,2). e(2,2). e(3,1).
loop(X) :- e(X,X).
from1(Y) :- e(1,Y).
sym(X,Y) :- e(X,Y), e(Y,X), X != Y.`)
	if got := ask(t, e, "?- loop(X)."); got != "X = 1\nX = 2\n(2 answers)\n" {
		t.Fatalf("%q", got)
	}
	if got := ask(t, e, "?- sym(X,Y)."); got != "no answers.\n" {
		t.Fatalf("%q", got)
	}
}

// ---- feature 3: negation, safety, stratification ----

func TestStratifiedNegation(t *testing.T) {
	e := mustEngine(t, `node(a). node(b). node(c). node(d).
edge(a,b). edge(b,c).
reach(X,Y) :- edge(X,Y).
reach(X,Z) :- reach(X,Y), edge(Y,Z).
iso(X) :- node(X), not reach(a,X), X != a.`)
	if got := ask(t, e, "?- iso(X)."); got != "X = d\n(1 answer)\n" {
		t.Fatalf("%q", got)
	}
	if e.Strata.Level["iso"] <= e.Strata.Level["reach"] {
		t.Fatal("iso must be in a later stratum than reach")
	}
	e2 := mustEngine(t, "ok :- not bad.\nbad :- f(1).\nf(2).")
	if ask(t, e2, "?- ok.") != "true.\n" || ask(t, e2, "?- bad.") != "false.\n" {
		t.Fatal("zero-arity negation")
	}
}

func TestRejectsUnstratifiable(t *testing.T) {
	for src, want := range map[string]string{
		"win(X) :- move(X,Y), not win(Y).":                    "negation of win",
		"p(X) :- q(X), not r(X). r(X) :- s(X), not p(X).":     "negation of",
		"t(count(*)) :- t(_).":                                "aggregation of t",
		"a(X) :- b(X). b(X) :- c(X). c(X) :- d(X), not a(X).": "a -> ",
	} {
		_, err := build(src)
		if err == nil || !strings.Contains(err.Error(), "not stratifiable") || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: %v", src, err)
		}
	}
}

func TestSafetyChecks(t *testing.T) {
	for src, want := range map[string]string{
		"p(X) :- q(Y).":           "head variable X",
		"p(X) :- q(X), not r(Y).": "Y",
		"p(X) :- X > 1.":          "not bound",
		"p(X) :- q(X), Y > 1.":    "Y",
		"p(X).":                   "ground",
		"p(a). p(a,b).":           "argument(s)",
		"p(sum(X)) :- q(Y).":      "aggregate variable X",
		"p(X) :- X = Y, Y = X.":   "not bound",
	} {
		_, err := build(src)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: got %v, want %q", src, err, want)
		}
	}
}

// ---- feature 4: arithmetic, queries, provenance ----

func TestArithmetic(t *testing.T) {
	e := mustEngine(t, `n(1). n(2). n(7). n(-7).
sq(X,Y) :- n(X), Y = X * X.
m(X,Y) :- n(X), Y = X mod 3.
d(X,Y) :- n(X), Y = X / 2 + 1.
big(X) :- n(X), X * 2 > 10 - 1.
lin(X,Y) :- n(X), 2 * X + 1 = Y.`)
	if got := ask(t, e, "?- sq(7,Y)."); got != "Y = 49\n(1 answer)\n" {
		t.Fatal(got)
	}
	if got := ask(t, e, "?- m(-7,Y)."); got != "Y = 2\n(1 answer)\n" { // floored mod
		t.Fatal(got)
	}
	if got := ask(t, e, "?- d(7,Y)."); got != "Y = 4\n(1 answer)\n" {
		t.Fatal(got)
	}
	if got := ask(t, e, "?- big(X)."); got != "X = 7\n(1 answer)\n" {
		t.Fatal(got)
	}
	if got := ask(t, e, "?- lin(2,Y)."); got != "Y = 5\n(1 answer)\n" {
		t.Fatal(got)
	}
}

func TestRuntimeErrors(t *testing.T) {
	for src, want := range map[string]string{
		"a(1). p(X) :- a(Y), X = 5 / (Y - 1).": "division by zero",
		"a(\"x\"). p(X) :- a(Y), X = Y + 1.":   "non-integer",
		"n(0). n(X) :- n(Y), X = Y + 1.":       "derivation limit",
	} {
		e, err := build(src)
		if err != nil {
			t.Fatal(err)
		}
		e.MaxFacts = 1000
		err = e.Run()
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: %v", src, err)
		}
	}
}

func TestQueries(t *testing.T) {
	e := mustEngine(t, "p(1,a). p(2,b). p(3,a).")
	if got := ask(t, e, "?- p(X,a), X > 1."); got != "X = 3\n(1 answer)\n" {
		t.Fatal(got)
	}
	if got := ask(t, e, "?- p(X,Y), p(Z,Y), X < Z."); got != "X = 1, Y = a, Z = 3\n(1 answer)\n" {
		t.Fatal(got)
	}
	if got := ask(t, e, "?- p(9,_)."); got != "false.\n" {
		t.Fatal(got)
	}
	q, _ := Parse("?- nope(X).")
	if _, err := e.Ask(q.Queries[0]); err == nil || !strings.Contains(err.Error(), "unknown predicate") {
		t.Fatalf("unknown pred: %v", err)
	}
	q, _ = Parse("?- p(X), Y > 1.")
	if _, err := e.Ask(q.Queries[0]); err == nil {
		t.Fatal("unsafe query should error")
	}
}

func TestProvenance(t *testing.T) {
	e := mustEngine(t, `edge(a,b). edge(b,c). edge(c,d). blocked(z).
path(X,Y) :- edge(X,Y).
path(X,Z) :- path(X,Y), edge(Y,Z).
ok(X,Y) :- path(X,Y), not blocked(Y), X != Y.`)
	pred, tu, err := ParseFact("ok(a, d)")
	if err != nil {
		t.Fatal(err)
	}
	s, err := e.Why(pred, tu)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"ok(a, d)", "path(a, d)", "edge(c, d)  [fact]", "not blocked(d)  ✓", "a != d  ✓", "edge(a, b)  [fact]"} {
		if !strings.Contains(s, want) {
			t.Errorf("proof missing %q:\n%s", want, s)
		}
	}
	if _, err := e.Why("ok", []Val{Str("d"), Str("a")}); err == nil {
		t.Fatal("underivable fact must error")
	}
	// every derived fact's proof is finite/acyclic: sizes are bounded by total facts
	for _, r := range e.Rels {
		for i := range r.Tuples {
			if n := e.ProofSize(FactRef{r.Name, i}); n < 1 || n > 1000 {
				t.Fatalf("proof size %d", n)
			}
		}
	}
}

// ---- stretch: aggregates ----

func TestAggregates(t *testing.T) {
	e := mustEngine(t, `emp(ann, eng, 100). emp(bob, eng, 100). emp(cy, ops, 70). emp(di, ops, 90). emp(ed, hr, 50).
n(D, count(*)) :- emp(_, D, _).
nn(D, count(P)) :- emp(P, D, _).
tot(D, sum(S)) :- emp(_, D, S).
hi(D, max(S)) :- emp(_, D, S).
lo(D, min(S)) :- emp(_, D, S).
grand(sum(S)) :- emp(_, _, S).
first(min(P)) :- emp(P, _, _).
top(D) :- hi(D, M), grand(G), M * 4 + 20 > G.`)
	for q, want := range map[string]string{
		"?- n(eng,X).":   "X = 2\n(1 answer)\n",
		"?- nn(ops,X).":  "X = 2\n(1 answer)\n",
		"?- tot(eng,X).": "X = 200\n(1 answer)\n", // duplicates of equal salary both count
		"?- tot(ops,X).": "X = 160\n(1 answer)\n",
		"?- hi(ops,X).":  "X = 90\n(1 answer)\n",
		"?- lo(ops,X).":  "X = 70\n(1 answer)\n",
		"?- grand(X).":   "X = 410\n(1 answer)\n",
		"?- first(X).":   "X = ann\n(1 answer)\n",
		"?- top(D).":     "D = eng\n(1 answer)\n",
	} {
		if got := ask(t, e, q); got != want {
			t.Errorf("%s: %q want %q", q, got, want)
		}
	}
	if s, err := e.Why("tot", []Val{Str("eng"), Int(200)}); err != nil || !strings.Contains(s, "aggregated over 2") {
		t.Fatalf("agg provenance: %v %s", err, s)
	}
	if _, err := build("s(a). t(sum(X)) :- s(X)."); err != nil {
		t.Fatal(err)
	}
	e3, _ := build("s(a). t(sum(X)) :- s(X).")
	if err := e3.Run(); err == nil || !strings.Contains(err.Error(), "non-integer") {
		t.Fatalf("sum over symbol: %v", err)
	}
}

// ---- stretch: bench + REPL + CLI ----

func TestBenchRuns(t *testing.T) {
	var b bytes.Buffer
	if err := bench(&b, 40); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(b.String(), "identical models") {
		t.Fatal(b.String())
	}
}

func TestREPL(t *testing.T) {
	var out bytes.Buffer
	in := strings.NewReader("e(a,b).\ne(b,c).\nr(X,Y) :- e(X,Y).\nr(X,Z) :- r(X,Y), e(Y,Z).\n?- r(a,Z).\n:why r(a,c)\nbad(X) :- not bad(X).\n?- r(c,a).\n:facts r\n:quit\n")
	repl(in, &out, "")
	s := out.String()
	for _, want := range []string{"Z = b", "Z = c", "r(a, c)  [line 4", "not stratifiable", "false.", "r(b, c)."} {
		if !strings.Contains(s, want) {
			t.Errorf("repl output missing %q:\n%s", want, s)
		}
	}
	// a rejected line must not poison the session
	if strings.Count(s, "ok\n") != 4 {
		t.Errorf("expected 4 accepted statements:\n%s", s)
	}
}

func TestCLI(t *testing.T) {
	var out, errb bytes.Buffer
	if code := run([]string{"run", "examples/family.dl"}, &out, &errb); code != 0 || !strings.Contains(out.String(), "X = gina") {
		t.Fatalf("code=%d err=%s", code, errb.String())
	}
	out.Reset()
	if code := run([]string{"check", "examples/access.dl"}, &out, &errb); code != 0 || !strings.Contains(out.String(), "stratum 2") {
		t.Fatalf("check: %d %s", code, out.String())
	}
	out.Reset()
	errb.Reset()
	if code := run([]string{"run", "no/such/file.dl"}, &out, &errb); code != 1 || !strings.Contains(errb.String(), "error:") {
		t.Fatalf("missing file: %d %s", code, errb.String())
	}
	if code := run([]string{"bogus"}, &out, &errb); code != 2 {
		t.Fatal("unknown command should exit 2")
	}
	if code := run(nil, &out, &errb); code != 2 {
		t.Fatal("no args should exit 2")
	}
	out.Reset()
	if code := run([]string{"why", "examples/graph.dl", "on_cycle(a)"}, &out, &errb); code != 0 || !strings.Contains(out.String(), "reach(a, a)") {
		t.Fatalf("why: %d %s", code, out.String())
	}
	errb.Reset()
	if code := run([]string{"why", "examples/graph.dl", "on_cycle(e)"}, &out, &errb); code != 1 || !strings.Contains(errb.String(), "not derivable") {
		t.Fatalf("why false: %d %s", code, errb.String())
	}
}

func TestExamplesWorkNaiveAndSemiNaive(t *testing.T) {
	for _, f := range []string{"family", "graph", "pointsto", "access"} {
		var a, b, e bytes.Buffer
		if run([]string{"run", "examples/" + f + ".dl"}, &a, &e) != 0 || run([]string{"run", "-naive", "examples/" + f + ".dl"}, &b, &e) != 0 {
			t.Fatalf("%s failed: %s", f, e.String())
		}
		if a.String() != b.String() {
			t.Errorf("%s: naive and semi-naive answers differ", f)
		}
	}
}
