package parse

import (
	"bytes"
	"math/rand"
	"strings"
	"testing"

	"bayou/internal/bn"
)

func sameNet(t *testing.T, a, b *bn.Network) {
	t.Helper()
	if len(a.Vars) != len(b.Vars) {
		t.Fatalf("variable count %d vs %d", len(a.Vars), len(b.Vars))
	}
	for v := range a.Vars {
		x, y := a.Vars[v], b.Vars[v]
		if x.Name != y.Name || strings.Join(x.States, "|") != strings.Join(y.States, "|") {
			t.Fatalf("variable %d differs: %v vs %v", v, x, y)
		}
		if len(x.Parents) != len(y.Parents) {
			t.Fatalf("%s parents differ", x.Name)
		}
		for i := range x.Parents {
			if x.Parents[i] != y.Parents[i] {
				t.Fatalf("%s parents differ", x.Name)
			}
		}
		for i := range x.CPT {
			if x.CPT[i] != y.CPT[i] {
				t.Fatalf("%s CPT[%d] %v vs %v (must round-trip bit-exactly)", x.Name, i, x.CPT[i], y.CPT[i])
			}
		}
	}
}

func TestBNRoundTripRandom(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for i := 0; i < 200; i++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 1 + rng.Intn(12), MaxParents: 3, MaxCard: 4, ZeroProb: 0.2, Sharp: 0.4})
		m, err := ParseBN("rt", FormatBN(n))
		if err != nil {
			t.Fatalf("trial %d: %v\n%s", i, err, FormatBN(n))
		}
		sameNet(t, n, m)
	}
}

func TestBIFRoundTripRandom(t *testing.T) {
	rng := rand.New(rand.NewSource(2))
	for i := 0; i < 200; i++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 1 + rng.Intn(10), MaxParents: 3, MaxCard: 4, ZeroProb: 0.2})
		var buf bytes.Buffer
		if err := WriteBIF(&buf, n); err != nil {
			t.Fatal(err)
		}
		m, err := ParseBIF("rt", buf.String())
		if err != nil {
			t.Fatalf("trial %d: %v\n%s", i, err, buf.String())
		}
		sameNet(t, n, m)
	}
}

func TestAwkwardNamesRoundTrip(t *testing.T) {
	n := bn.New("my \"net\"")
	a, _ := n.AddVar("var with space", []string{"*", "has,comma", `quo"te`, "back\\slash", "#hash", "a=b"})
	b, _ := n.AddVar("0", []string{"1", "2"})
	n.SetParents(b, []int{a})
	for i := range n.Vars[b].CPT {
		n.Vars[b].CPT[i] = 0.5
	}
	m, err := ParseBN("rt", FormatBN(n))
	if err != nil {
		t.Fatalf("%v\n%s", err, FormatBN(n))
	}
	sameNet(t, n, m)
	if m.Name != n.Name {
		t.Fatalf("network name %q lost", m.Name)
	}
}

func TestQuotedStarIsAStateNotAWildcard(t *testing.T) {
	src := "network X\nvar A { \"*\", b }\nvar B { u, v }\ncpt A = 0.5, 0.5\ncpt B | A {\n \"*\": 1, 0\n b: 0, 1\n}\n"
	n, err := ParseBN("x", src)
	if err != nil {
		t.Fatal(err)
	}
	if n.Vars[1].CPT[0] != 1 || n.Vars[1].CPT[2] != 0 || n.Vars[1].CPT[3] != 1 {
		t.Fatalf("quoted star treated as wildcard: %v", n.Vars[1].CPT)
	}
}

func TestParserAcceptsBOMCRLFSpacesFractions(t *testing.T) {
	src := "\xef\xbb\xbfnetwork X\r\nvar A { a, b }\r\nvar B { u, v, w }\r\ncpt A = 1/4 3/4   # fractions, no comma\r\ncpt B | A { a: 0.2 0.3 0.5\r\n  b: 0.1,\r\n  0.1, 0.8 }\r\n"
	n, err := ParseBN("x", src)
	if err != nil {
		t.Fatal(err)
	}
	if n.Vars[0].CPT[0] != 0.25 || n.Vars[1].CPT[5] != 0.8 {
		t.Fatalf("bad values %v %v", n.Vars[0].CPT, n.Vars[1].CPT)
	}
}

func TestParserErrors(t *testing.T) {
	cases := []struct{ name, src, want string }{
		{"empty", "", "no variables"},
		{"only comment", "# nothing here\n", "no variables"},
		{"dup var", "var A {a,b}\nvar A {a,b}\n", "duplicate variable"},
		{"one state", "var A {a}\ncpt A = 1\n", "at least 2 states"},
		{"dup state", "var A {a,a}\n", "duplicate state"},
		{"missing cpt", "var A {a,b}\n", `no cpt`},
		{"undeclared", "cpt A = 1\n", "undeclared variable"},
		{"two cpts", "var A {a,b}\ncpt A = 1,0\ncpt A = 0,1\n", "already has a cpt"},
		{"bad sum", "var A {a,b}\ncpt A = 0.5, 0.6\n", "sums to"},
		{"negative", "var A {a,b}\ncpt A = -0.5, 1.5\n", "not in [0,1]"},
		{"count", "var A {a,b}\ncpt A = 1\n", "expected 2 probabilities"},
		{"not number", "var A {a,b}\ncpt A = x, y\n", "not a number"},
		{"nan", "var A {a,b}\ncpt A = NaN, 1\n", "not a number"},
		{"inf", "var A {a,b}\ncpt A = Inf, 0\n", "not a number"},
		{"unknown parent", "var A {a,b}\ncpt A | Z { a: 1,0\n b: 1,0 }\n", "unknown parent"},
		{"self parent", "var A {a,b}\ncpt A | A { a: 1,0\n b: 1,0 }\n", "own parent"},
		{"cycle", "var A {a,b}\nvar B {a,b}\ncpt A | B { a: 1,0\n b: 1,0 }\ncpt B | A { a: 1,0\n b: 1,0 }\n", "cycle"},
		{"missing row", "var A {a,b}\nvar B {a,b}\ncpt A = 1,0\ncpt B | A { a: 1,0 }\n", "no row for A=b"},
		{"dup row", "var A {a,b}\nvar B {a,b}\ncpt A = 1,0\ncpt B | A { a: 1,0\n a: 0,1\n b: 1,0 }\n", "listed twice"},
		{"bad parent state", "var A {a,b}\nvar B {a,b}\ncpt A = 1,0\ncpt B | A { a: 1,0\n zz: 0,1 }\n", `no state "zz"`},
		{"row arity", "var A {a,b}\nvar B {a,b}\ncpt A = 1,0\ncpt B | A { a, a: 1,0 }\n", "names 2 parent states"},
		{"junk", "hello\n", "unknown declaration"},
		{"unterminated string", "network \"abc\nvar A {a,b}\n", "unterminated string"},
		{"unterminated comment", "/* oops\nvar A {a,b}\n", "unterminated"},
		{"unclosed brace", "var A {a,b\n", "expected"},
	}
	for _, c := range cases {
		_, err := ParseBN("t.bn", c.src)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: want error containing %q, got %v", c.name, c.want, err)
		}
		if err != nil && !strings.HasPrefix(err.Error(), "t.bn:") {
			t.Errorf("%s: error lacks position: %v", c.name, err)
		}
	}
}

func TestErrorPositions(t *testing.T) {
	_, err := ParseBN("f.bn", "network X\nvar A { a, b }\ncpt A = 0.5, zap\n")
	pe, ok := err.(*Error)
	if !ok || pe.Line != 3 || pe.Col != 14 {
		t.Fatalf("want error at 3:14, got %v", err)
	}
}

func TestWildcardPrecedence(t *testing.T) {
	src := "var A {x,y}\nvar B {u,v}\nvar C {p,q}\ncpt A = .5,.5\ncpt B = .5,.5\ncpt C | A, B {\n *, *: 0.5, 0.5\n x, u: 1, 0\n y, *: 0, 1\n}\n"
	n, err := ParseBN("x", src)
	if err != nil {
		t.Fatal(err)
	}
	want := []float64{1, 0, 0.5, 0.5, 0, 1, 0, 1} // rows: xu xv yu yv
	for i, w := range want {
		if n.Vars[2].CPT[i] != w {
			t.Fatalf("CPT=%v want %v", n.Vars[2].CPT, want)
		}
	}
}

// Parsers must never panic, whatever bytes they are fed.
func TestParsersNeverPanicOnGarbage(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	seed, _ := ParseBN("s", "network X\nvar A { a, b }\nvar B { c, d }\ncpt A = 0.5, 0.5\ncpt B | A {\n a: 1, 0\n b: 0.5, 0.5\n}\n")
	good := FormatBN(seed)
	var bif bytes.Buffer
	WriteBIF(&bif, seed)
	for i := 0; i < 4000; i++ {
		for _, base := range []string{good, bif.String()} {
			b := []byte(base)
			for k := 0; k < 1+rng.Intn(6); k++ {
				switch rng.Intn(3) {
				case 0:
					b[rng.Intn(len(b))] = byte(rng.Intn(256))
				case 1:
					p := rng.Intn(len(b))
					b = append(b[:p], b[min(len(b), p+1+rng.Intn(8)):]...)
				default:
					p := rng.Intn(len(b))
					b = append(b[:p], append([]byte("{},:|=\"#/*\n"[rng.Intn(11):][:1]), b[p:]...)...)
				}
				if len(b) == 0 {
					b = []byte("x")
				}
			}
			ParseBN("fuzz", string(b))
			ParseBIF("fuzz", string(b))
		}
	}
}

func TestCSVStateNamedLikeMissingMarker(t *testing.T) {
	n := bn.New("x")
	n.AddVar("A", []string{"none", "some"})
	n.AddVar("B", []string{"NA", "yes"})
	ds, err := ReadCSV(n, strings.NewReader("A,B\nnone,NA\n?,yes\nsome,\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := [][]int{{0, 0}, {Missing, 1}, {1, Missing}}
	for r := range want {
		for c := range want[r] {
			if ds.Rows[r][c] != want[r][c] {
				t.Fatalf("rows=%v want %v", ds.Rows, want)
			}
		}
	}
	var buf bytes.Buffer
	if err := WriteCSV(&buf, n, ds); err != nil {
		t.Fatal(err)
	}
	ds2, err := ReadCSV(n, &buf)
	if err != nil {
		t.Fatal(err)
	}
	for r := range want {
		for c := range want[r] {
			if ds2.Rows[r][c] != want[r][c] {
				t.Fatalf("CSV did not round-trip: %v", ds2.Rows)
			}
		}
	}
}

func TestCSVErrors(t *testing.T) {
	n := bn.New("x")
	n.AddVar("A", []string{"a", "b"})
	n.AddVar("B", []string{"c", "d"})
	cases := []struct{ src, want string }{
		{"", "empty"},
		{"A,Z\n", `"Z" is not a variable`},
		{"A,A\n", "twice"},
		{"A,B\na\n", "1 fields"},
		{"A,B\na,zzz\n", `"zzz" is not a state`},
	}
	for _, c := range cases {
		_, err := ReadCSV(n, strings.NewReader(c.src))
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: want %q got %v", c.src, c.want, err)
		}
	}
	// BOM and blank lines are tolerated
	ds, err := ReadCSV(n, strings.NewReader("\xef\xbb\xbfA,B\n\na,c\n\n"))
	if err != nil || len(ds.Rows) != 1 {
		t.Fatalf("%v %v", ds, err)
	}
}

func TestRowsAreRenormalizedButExactRowsUntouched(t *testing.T) {
	n, err := ParseBN("x", "var A {a,b,c}\ncpt A = 0.3333, 0.3333, 0.3333\n") // sums to 0.9999: rejected
	if err == nil {
		t.Fatalf("0.9999 should fail validation, got %v", n.Vars[0].CPT)
	}
	n, err = ParseBN("x", "var A {a,b}\ncpt A = 0.5, 0.5000004\n")
	if err != nil {
		t.Fatal(err)
	}
	if s := n.Vars[0].CPT[0] + n.Vars[0].CPT[1]; s != 1 && (s < 1-1e-15 || s > 1+1e-15) {
		t.Fatalf("row not renormalised: sums to %.17g", s)
	}
	n, _ = ParseBN("x", "var A {a,b}\ncpt A = 0.1, 0.9\n")
	if n.Vars[0].CPT[0] != 0.1 || n.Vars[0].CPT[1] != 0.9 {
		t.Fatal("an already normalised row was modified")
	}
}

// A quoted "*" is a state name, so a lone "*" row must NOT fill the other parent states.
func TestQuotedStarRowDoesNotFillOtherRows(t *testing.T) {
	src := "var A { \"*\", b }\nvar B { u, v }\ncpt A = .5,.5\ncpt B | A {\n \"*\": 1, 0\n}\n"
	if _, err := ParseBN("x", src); err == nil || !strings.Contains(err.Error(), "no row for A=b") {
		t.Fatalf("want a missing-row error, got %v", err)
	}
	// ...while a bare * is a wildcard and does fill them
	src = "var A { x, b }\nvar B { u, v }\ncpt A = .5,.5\ncpt B | A {\n *: 1, 0\n}\n"
	if _, err := ParseBN("x", src); err != nil {
		t.Fatal(err)
	}
}
