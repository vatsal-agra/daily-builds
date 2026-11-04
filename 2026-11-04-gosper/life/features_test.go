package life

import (
	"math/rand"
	"strings"
	"testing"
)

func lib(t *testing.T, name string) *Pattern {
	t.Helper()
	p, ok := LookupPattern(name)
	if !ok {
		t.Fatalf("no pattern %s", name)
	}
	return p
}

func TestParseRule(t *testing.T) {
	for in, want := range map[string]string{"B3/S23": "B3/S23", "b36s23": "B36/S23", "S23/B3": "B3/S23", "23/3": "B3/S23", "B2/S": "B2/S", "B3S23": "B3/S23"} {
		r, err := ParseRule(in)
		if err != nil || r.String() != want {
			t.Errorf("%q -> %v %v, want %s", in, r, err, want)
		}
	}
	for _, bad := range []string{"", "B0/S23", "B3/S9", "B3/S23/C3", "hello", "B3"} {
		if _, err := ParseRule(bad); err == nil {
			t.Errorf("%q should fail", bad)
		}
	}
}

func TestKnownFacts(t *testing.T) {
	cases := []struct {
		name      string
		gen, pop  uint64
		settledAt uint64
	}{{"rpentomino", 1103, 116, 1103}, {"acorn", 5206, 633, 5206}}
	for _, c := range cases {
		p := lib(t, c.name)
		st, err := FindSettle(Life, p.Cells, 6000, 22)
		if err != nil {
			t.Fatal(err)
		}
		if !st.Settled || st.AtGen != c.settledAt || st.FinalPop != c.pop || !st.HorizonOK {
			t.Errorf("%s: %+v", c.name, *st)
		}
	}
	pr, _ := FindPeriod(Life, lib(t, "diehard").Cells, 300)
	if pr.Kind != KindDies || pr.DiesAt != 130 {
		t.Errorf("diehard %+v", pr)
	}
	pr, _ = FindPeriod(Life, lib(t, "glider").Cells, 50)
	if pr.Kind != KindSpaceship || pr.Period != 4 || pr.Dx != 1 || pr.Dy != 1 || pr.Speed() != "1c/4 diagonal" {
		t.Errorf("glider %+v", pr)
	}
	pr, _ = FindPeriod(Life, lib(t, "lwss").Cells, 50)
	if pr.Kind != KindSpaceship || pr.Period != 4 || abs64(pr.Dx)+abs64(pr.Dy) != 2 || pr.Speed() != "2c/4 orthogonal" {
		t.Errorf("lwss %+v", pr)
	}
	for name, per := range map[string]int{"block": 1, "beehive": 1, "blinker": 2, "toad": 2, "beacon": 2, "pentadecathlon": 15} {
		pr, _ := FindPeriod(Life, lib(t, name).Cells, 50)
		if pr.Period != per || (per == 1) != (pr.Kind == KindStill) {
			t.Errorf("%s %+v", name, pr)
		}
	}
}

func TestLargeJumpsMatchNaive(t *testing.T) {
	for _, c := range []struct {
		name string
		j    int
	}{{"gosper-gun", 9}, {"gosper-gun", 8}, {"rpentomino", 10}, {"acorn", 11}} {
		p := lib(t, c.name)
		s := NewSim(Life)
		_ = s.SetCells(append([]Point(nil), p.Cells...), false)
		if err := s.StepPow(c.j); err != nil {
			t.Fatal(err)
		}
		nv := NewNaive(Life, p.Cells)
		nv.StepN(1 << uint(c.j))
		if !nv.EqualSim(s, 0, 0) {
			t.Errorf("%s 2^%d mismatch", c.name, c.j)
		}
	}
}

func TestGunGrowthLinear(t *testing.T) {
	p := lib(t, "gosper-gun")
	cps, gc, err := GrowthReport(Life, p.Cells, 30)
	if err != nil || gc.Label != "linear growth" || gc.Exponent < 0.95 || gc.Exponent > 1.05 {
		t.Fatalf("%v %+v", err, gc)
	}
	// exact: one glider (5 cells) per 30 generations
	last := cps[len(cps)-1]
	if got := float64(last.Pop) / float64(last.Gen); got < 1.0/6-0.001 || got > 1.0/6+0.001 {
		t.Errorf("density %.5f want 1/6", got)
	}
	_, gc, _ = GrowthReport(Life, lib(t, "glider").Cells, 20)
	if gc.Label != "bounded (settles)" {
		t.Errorf("glider %+v", gc)
	}
	r, _ := ParseRule("B1/S12345")
	_, gc, _ = GrowthReport(r, []Point{{0, 0}, {1, 0}}, 20)
	if gc.Label != "quadratic growth" {
		t.Errorf("B1/S12345 growth %+v", gc)
	}
}

func TestIORoundTrips(t *testing.T) {
	rng := rand.New(rand.NewSource(5))
	for i := 0; i < 50; i++ {
		pts := soup(rng, 1+rng.Intn(60), 1+rng.Intn(60), rng.Float64())
		for j := range pts {
			pts[j].X -= 7
			pts[j].Y -= 9
		}
		for _, text := range []string{EncodeRLE(pts, Life, "x"), EncodeCells(pts, "x")} {
			p, err := ParsePattern(text)
			if err != nil {
				t.Fatal(err, text)
			}
			if len(pts) > 0 && !samePoints(mustNorm(p.Cells), mustNorm(pts)) {
				t.Fatalf("round trip differs:\n%s", text)
			}
		}
		s := NewSim(Life)
		_ = s.SetCells(append([]Point(nil), pts...), false)
		_ = s.Step(uint64(rng.Intn(50)))
		s2, err := LoadMacrocell(s.WriteMacrocell(), Life)
		if err != nil || s2.Gen != s.Gen || s2.Population() != s.Population() {
			t.Fatalf("mc %v", err)
		}
		a, _ := s.Cells(0)
		b, _ := s2.Cells(0)
		if !samePoints(mustNorm(a), mustNorm(b)) {
			t.Fatal("mc cells differ")
		}
	}
}

func mustNorm(p []Point) []Point { n, _, _ := normalise(p); return n }

func TestParseErrors(t *testing.T) {
	for _, bad := range []string{"x = 1\n2o", "x=1,y=1\n3a!", "", "x = 1, y = 1, rule = B0/S\no!"} {
		if _, err := ParseRLE(bad); err == nil {
			t.Errorf("RLE %q should fail", bad)
		}
	}
	if _, err := ParseCells("OO\nOX"); err == nil {
		t.Error("cells with X should fail")
	}
	for _, bad := range []string{"", "[M2]\n4 9 0 0 0\n", "[M2]\n#R B3/S23\nxyz\n", "[M2]\n3 0 0 0 0\n"} {
		if _, err := LoadMacrocell(bad, Life); err == nil {
			t.Errorf("MC %q should fail", bad)
		}
	}
	p, err := ParseRLE("#N n\n#C c\nx = 3, y = 1, rule = B36/S23\n3o!")
	if err != nil || p.Name != "n" || p.Rule.String() != "B36/S23" || len(p.Cells) != 3 {
		t.Errorf("%+v %v", p, err)
	}
}

func TestGetBBoxAndEdges(t *testing.T) {
	s := NewSim(Life)
	if _, _, _, _, ok := s.BBox(); ok || s.Population() != 0 {
		t.Error("empty sim")
	}
	if err := s.SetCells([]Point{{1 << 60, 0}}, false); err == nil {
		t.Error("out-of-range cell accepted")
	}
	rng := rand.New(rand.NewSource(9))
	pts := soup(rng, 40, 40, 0.3)
	_ = s.SetCells(append([]Point(nil), pts...), false)
	x0, y0, x1, y1, _ := s.BBox()
	bx0, by0, bx1, by1 := boundsOf(pts)
	if x0 != bx0 || y0 != by0 || x1 != bx1 || y1 != by1 {
		t.Error("bbox")
	}
	set := map[Point]bool{}
	for _, p := range pts {
		set[p] = true
	}
	for y := int64(-3); y < 45; y++ {
		for x := int64(-3); x < 45; x++ {
			if s.Get(x, y) != set[Point{x, y}] {
				t.Fatalf("Get(%d,%d)", x, y)
			}
		}
	}
	if s.Get(1<<40, 5) {
		t.Error("far Get")
	}
}

func TestBudgetAndRecovery(t *testing.T) {
	r, _ := ParseRule("B2/S")
	rng := rand.New(rand.NewSource(2))
	s := NewSim(r)
	s.U.Budget = 20000
	_ = s.SetCells(soup(rng, 60, 60, 0.5), true)
	err := s.Step(400)
	if err != ErrBudget {
		t.Fatalf("want ErrBudget, got %v", err)
	}
	// sim must still be usable at its last good state
	g := s.Gen
	s.U.Budget = 0
	if err := s.Step(3); err != nil || s.Gen != g+3 {
		t.Fatalf("after budget: %v gen %d->%d", err, g, s.Gen)
	}
}

func TestCensus(t *testing.T) {
	o := CensusOptions{Rule: Life, Soups: 120, Size: 16, Density: 0.5, Gens: 600, Seed: 4, Workers: 1}
	a, err := Census(o)
	if err != nil {
		t.Fatal(err)
	}
	o.Workers = 4
	b, _ := Census(o)
	if a.TotalObj != b.TotalObj || len(a.Objects) != len(b.Objects) {
		t.Error("census not deterministic across worker counts")
	}
	rows := a.Sorted()
	if rows[0].Name != "block" {
		t.Errorf("most common object %q, want block", rows[0].Name)
	}
	for _, want := range []string{"blinker", "beehive"} {
		if a.Objects[want] == 0 {
			t.Errorf("no %s found", want)
		}
	}
	if _, err := Census(CensusOptions{Rule: Life}); err == nil {
		t.Error("bad options accepted")
	}
	for _, o := range knownObjects {
		p, _ := ParseRLE(o.rle)
		if got := Identify(Life, p.Cells); got != o.name {
			t.Errorf("Identify %s = %s", o.name, got)
		}
	}
	// orientation/phase invariance: rotated, evolved glider is still a glider
	g := lib(t, "glider").Cells
	rot := make([]Point, len(g))
	for i, p := range g {
		rot[i] = Point{-p.Y, p.X}
	}
	if Identify(Life, rot) != "glider" {
		t.Error("rotated glider")
	}
}

func TestRenderAndReport(t *testing.T) {
	s := NewSim(Life)
	_ = s.SetCells(lib(t, "gosper-gun").Cells, true)
	_ = s.Step(1 << 40)
	img := RenderImage(s, FitView(s, 300, 300), 300, 300, DarkTheme)
	lit := 0
	for i := 0; i < len(img.Pix); i += 4 {
		if img.Pix[i] != DarkTheme.BG.R || img.Pix[i+1] != DarkTheme.BG.G {
			lit++
		}
	}
	if lit < 100 {
		t.Errorf("zoomed-out render nearly blank (%d px)", lit)
	}
	s2 := NewSim(Life)
	_ = s2.SetCells(lib(t, "block").Cells, true)
	img = RenderImage(s2, FitView(s2, 100, 100), 100, 100, LightTheme)
	if img.RGBAAt(50, 50) == LightTheme.BG && img.RGBAAt(40, 40) == LightTheme.BG && img.RGBAAt(60, 60) == LightTheme.BG {
		t.Error("block not drawn")
	}
	p := lib(t, "glider")
	pr, _ := FindPeriod(Life, p.Cells, 50)
	h, err := HTMLReport(ReportData{Name: "g<script>", Rule: Life, Cells: p.Cells, Snaps: []uint64{0, 4}, Period: pr, PopCurve: []uint64{5, 5, 5}})
	if err != nil || !strings.Contains(h, "Spaceship p4") || strings.Contains(h, "g<script>") || !strings.Contains(h, "data:image/png;base64,") {
		t.Errorf("report: %v", err)
	}
}

func TestCompactKeepsCanonical(t *testing.T) {
	s := NewSim(Life)
	_ = s.SetCells(lib(t, "rpentomino").Cells, true)
	s.MaxNodes = 300
	if err := s.Step(1103); err != nil {
		t.Fatal(err)
	}
	if s.Population() != 116 {
		t.Errorf("pop %d", s.Population())
	}
	if s.U.Empty(5) != s.U.Empty(5) || s.U.join(s.U.Empty(4), s.U.Empty(4), s.U.Empty(4), s.U.Empty(4)) != s.U.Empty(5) {
		t.Error("empty nodes not canonical after compaction")
	}
}
