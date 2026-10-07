package model

import (
	"math/big"
	"strings"
	"testing"
)

const sample = `
\ a comment
Maximize
 obj: 3 x + 2 y - z + 5
Subject To
 c1: x + y <= 4
 c2: x - y >= -2
 c3: 2 x + 3 y
     + z = 7
 r1: -1 <= x - z <= 3
 3/2 x + 0.5 y >= 1
Bounds
 0 <= x <= 10
 y free
 z >= -5
Integer
 x
End
`

func TestParseSample(t *testing.T) {
	m, err := Parse(sample)
	if err != nil {
		t.Fatal(err)
	}
	if !m.Maximize || len(m.Vars) != 3 || len(m.Rows) != 5 {
		t.Fatalf("shape: max=%v vars=%d rows=%d", m.Maximize, len(m.Vars), len(m.Rows))
	}
	if m.ObjConst.Cmp(big.NewRat(5, 1)) != 0 {
		t.Fatalf("const %v", m.ObjConst)
	}
	x, y, z := m.Vars[m.VarIndex("x")], m.Vars[m.VarIndex("y")], m.Vars[m.VarIndex("z")]
	if !x.Int || x.Hi.Cmp(big.NewRat(10, 1)) != 0 || y.Lo != nil || y.Hi != nil || z.Lo.Cmp(big.NewRat(-5, 1)) != 0 {
		t.Fatalf("bounds wrong: %+v %+v %+v", x, y, z)
	}
	r1 := m.Rows[3]
	if r1.Lo.Cmp(big.NewRat(-1, 1)) != 0 || r1.Hi.Cmp(big.NewRat(3, 1)) != 0 {
		t.Fatalf("range row: %v %v", r1.Lo, r1.Hi)
	}
	if m.Rows[4].Name != "c5" || m.Rows[4].Entries[0].V.Cmp(big.NewRat(3, 2)) != 0 {
		t.Fatalf("unnamed row / fraction: %+v", m.Rows[4])
	}
}

func TestRoundTrip(t *testing.T) {
	m, err := Parse(sample)
	if err != nil {
		t.Fatal(err)
	}
	m2, err := Parse(Format(m))
	if err != nil {
		t.Fatal(err)
	}
	if Format(m2) != Format(m) {
		t.Fatalf("format not stable:\n%s\n---\n%s", Format(m), Format(m2))
	}
}

func TestConstantsOnBothSides(t *testing.T) {
	m, err := Parse("Minimize\n o: x + y\nSubject To\n c: x + 3 >= 2 y - 4\nEnd")
	if err != nil {
		t.Fatal(err)
	}
	// x - 2y >= -7
	r := m.Rows[0]
	if r.Lo.Cmp(big.NewRat(-7, 1)) != 0 || r.Hi != nil {
		t.Fatalf("rhs %v", r.Lo)
	}
	got := map[string]int64{}
	for _, e := range r.Entries {
		got[m.Vars[e.J].Name] = e.V.Num().Int64()
	}
	if got["x"] != 1 || got["y"] != -2 {
		t.Fatalf("coefs %v", got)
	}
}

func TestDuplicateTermsCombine(t *testing.T) {
	m, err := Parse("Minimize\n o: x + x + y\nSubject To\n c: x + y + x <= 4\nEnd")
	if err != nil {
		t.Fatal(err)
	}
	if m.Vars[0].Obj.Cmp(big.NewRat(2, 1)) != 0 || m.Rows[0].Entries[0].V.Cmp(big.NewRat(2, 1)) != 0 {
		t.Fatal("terms not combined")
	}
}

func TestNegativeUpperBoundDropsLower(t *testing.T) {
	m, err := Parse("Minimize\n o: x\nSubject To\n c: x >= -9\nBounds\n x <= -2\nEnd")
	if err != nil {
		t.Fatal(err)
	}
	if m.Vars[0].Lo != nil || m.Vars[0].Hi.Cmp(big.NewRat(-2, 1)) != 0 {
		t.Fatal("negative upper bound should free the lower bound")
	}
}

func TestParseErrors(t *testing.T) {
	cases := []struct{ name, src, want string }{
		{"no objective", "Subject To\n c: x <= 1\nEnd", "no objective"},
		{"missing op", "Minimize\n o: x\nSubject To\n c: x + y\nEnd", "no comparison"},
		{"empty row", "Minimize\n o: x\nSubject To\n c: 0 <= 5\nEnd", "no variables"},
		{"bad char", "Minimize\n o: x $ y\nEnd", "unexpected character"},
		{"unknown bound var", "Minimize\n o: x\nSubject To\n c: x <= 1\nBounds\n w <= 3\nEnd", "unknown variable"},
		{"bad bounds order", "Minimize\n o: x\nSubject To\n c: x <= 1\nBounds\n 5 <= x <= 2\nEnd", "lower bound"},
		{"dup row", "Minimize\n o: x\nSubject To\n c: x <= 1\n c: x >= 0\nEnd", "duplicate"},
		{"three ops", "Minimize\n o: x\nSubject To\n c: 1 <= x <= 2 <= 3\nEnd", "at most two"},
		{"int unknown", "Minimize\n o: x\nSubject To\n c: x <= 1\nInteger\n q\nEnd", "unknown variable"},
		{"inf in row", "Minimize\n o: x\nSubject To\n c: x <= inf\nEnd", "bounds section"},
		{"dangling sign", "Minimize\n o: x +\nEnd", "expected"},
		{"two objectives", "Minimize\n o: x\nMaximize\n p: x\nEnd", "more than one"},
		{"stray text", "x + y\nEnd", "section header"},
		{"range mix", "Minimize\n o: x\nSubject To\n c: 1 <= x >= 0\nEnd", "same direction"},
	}
	for _, c := range cases {
		_, err := Parse(c.src)
		if err == nil {
			t.Errorf("%s: expected an error", c.name)
			continue
		}
		if !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: error %q does not mention %q", c.name, err.Error(), c.want)
		}
	}
}

func TestErrorPositionAndCaret(t *testing.T) {
	_, err := Parse("Minimize\n o: x\nSubject To\n c: x + y @ 3 <= 4\nEnd")
	pe, ok := err.(*ParseError)
	if !ok {
		t.Fatalf("want ParseError, got %T %v", err, err)
	}
	if pe.Line != 4 || pe.Col != 11 {
		t.Fatalf("position %d:%d", pe.Line, pe.Col)
	}
	if !strings.Contains(pe.Error(), "^") {
		t.Fatal("missing caret")
	}
}

func TestSectionKeywordsCaseInsensitive(t *testing.T) {
	m, err := Parse("MAXIMISE\n o: x\nSUBJECT TO\n c: x <= 1\nBINARIES\n x\nEND")
	if err != nil {
		t.Fatal(err)
	}
	if !m.Maximize || !m.Vars[0].Int || m.Vars[0].Hi.Cmp(big.NewRat(1, 1)) != 0 {
		t.Fatal("keywords/binary")
	}
}

func TestScientificAndFractionNumbers(t *testing.T) {
	m, err := Parse("Minimize\n o: 1.5e1 x + 2/4 y\nSubject To\n c: x + y >= 1e-1\nEnd")
	if err != nil {
		t.Fatal(err)
	}
	if m.Vars[0].Obj.Cmp(big.NewRat(15, 1)) != 0 || m.Vars[1].Obj.Cmp(big.NewRat(1, 2)) != 0 || m.Rows[0].Lo.Cmp(big.NewRat(1, 10)) != 0 {
		t.Fatal("number parsing")
	}
}
