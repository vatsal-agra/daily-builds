package cube

import (
	"math/rand"
	"testing"
)

func TestSolvedFacelets(t *testing.T) {
	if Solved().Facelets() != SolvedFacelets {
		t.Fatal("solved facelets mismatch")
	}
	if NewPhysical().Facelets() != SolvedFacelets {
		t.Fatal("physical solved mismatch")
	}
}

func TestFourTurnsIdentity(t *testing.T) {
	for f := 0; f < 6; f++ {
		c := Solved()
		for i := 0; i < 4; i++ {
			c = c.Apply(Move(f * 3))
		}
		if !c.IsSolved() {
			t.Fatalf("face %d: four turns not identity", f)
		}
		if Solved().Apply(Move(f*3)).Apply(Move(f*3+1)) != Solved().Apply(Move(f*3+2)) {
			t.Fatalf("face %d: X then X2 != X'", f)
		}
	}
}

func TestUMoveFacelets(t *testing.T) {
	got := Solved().Apply(Move(U * 3)).Facelets()
	want := "UUUUUUUUU" + "BBBRRRRRR" + "RRRFFFFFF" + "DDDDDDDDD" + "FFFLLLLLL" + "LLLBBBBBB"
	if got != want {
		t.Fatalf("U move:\n got %s\nwant %s", got, want)
	}
}

func randSeq(r *rand.Rand, n int) []Move {
	ms := make([]Move, n)
	for i := range ms {
		ms[i] = Move(r.Intn(18))
	}
	return ms
}

// The cubie model and the 3-D physical model must agree on thousands of random sequences.
func TestCubieMatchesPhysical(t *testing.T) {
	r := rand.New(rand.NewSource(1))
	for i := 0; i < 3000; i++ {
		ms := randSeq(r, 1+r.Intn(40))
		a := FromMoves(ms).Facelets()
		b := PhysicalFacelets(ms)
		if a != b {
			t.Fatalf("seq %s:\ncubie    %s\nphysical %s", FormatMoves(ms), a, b)
		}
	}
}

func TestInverseAndRoundTrip(t *testing.T) {
	r := rand.New(rand.NewSource(2))
	for i := 0; i < 500; i++ {
		ms := randSeq(r, 30)
		c := FromMoves(ms)
		if !c.Mul(c.Inverse()).IsSolved() {
			t.Fatal("cube inverse")
		}
		if !c.ApplySeq(InvertSeq(ms)).IsSolved() {
			t.Fatal("sequence inverse")
		}
		c2, err := ParseFacelets(c.Facelets())
		if err != nil || c2 != c {
			t.Fatalf("facelet round trip failed: %v", err)
		}
		if err := c.Check(); err != nil {
			t.Fatal(err)
		}
	}
}

func TestCoordinateRoundTrips(t *testing.T) {
	for i := 0; i < nTwist; i++ {
		c := Solved()
		c.setTwist(i)
		if c.twist() != i {
			t.Fatal("twist", i)
		}
	}
	for i := 0; i < nFlip; i++ {
		c := Solved()
		c.setFlip(i)
		if c.flip() != i {
			t.Fatal("flip", i)
		}
	}
	seen := map[[12]uint8]bool{}
	for i := 0; i < nSlice; i++ {
		c := Solved()
		c.setSlice(i)
		if c.slice() != i {
			t.Fatal("slice", i)
		}
		seen[c.EP] = true
	}
	if len(seen) != nSlice || Solved().slice() != solvedSlice {
		t.Fatal("slice not bijective / solved index wrong")
	}
	for i := 0; i < nPerm8; i += 7 {
		var p [8]uint8
		permUnrank(p[:], i)
		if permRank(p[:]) != i {
			t.Fatal("perm", i)
		}
	}
}

func TestSolverOnRandomStates(t *testing.T) {
	r := rand.New(rand.NewSource(3))
	total := 0
	for i := 0; i < 40; i++ {
		c := RandomState(r)
		if err := c.Check(); err != nil {
			t.Fatal(err)
		}
		res, err := Solve(c, Options{Target: 24, MaxLen: 30})
		if err != nil {
			t.Fatal(err)
		}
		if !c.ApplySeq(res.Moves).IsSolved() {
			t.Fatal("not solved")
		}
		// independent physical check
		start := c.Facelets()
		if PhysicalFaceletsFrom(start, res.Moves) != SolvedFacelets {
			t.Fatal("physical check failed")
		}
		total += len(res.Moves)
	}
	t.Logf("mean length %.2f", float64(total)/40)
}

func TestAnalyzeKnownOrders(t *testing.T) {
	cases := map[string]int{
		"R U R' U'": 6, "R U": 105, "R U2 D' B D'": 1260, "U": 4, "U2": 2, "R2 L2 U2 D2 F2 B2": 2,
		"": 1, "F R U R' U' F'": 6, "R U R' U R U2 R'": 6,
	}
	for alg, want := range cases {
		ms, err := ParseMoves(alg)
		if err != nil {
			t.Fatal(err)
		}
		a := Analyze(ms)
		if a.Order != want || a.OrderCycles != a.Order {
			t.Errorf("%q: order %d (cycles %d), want %d", alg, a.Order, a.OrderCycles, want)
		}
	}
}

func TestOrderFormulaAgreesOnRandom(t *testing.T) {
	r := rand.New(rand.NewSource(5))
	for i := 0; i < 300; i++ {
		a := Analyze(randSeq(r, 1+r.Intn(25)))
		if a.Order != a.OrderCycles {
			t.Fatalf("brute %d vs cycles %d", a.Order, a.OrderCycles)
		}
	}
}
