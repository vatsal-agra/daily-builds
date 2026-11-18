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

func TestValidatorDiagnoses(t *testing.T) {
	twisted := Solved()
	twisted.CO[0] = 1
	flipped := Solved()
	flipped.EO[3] = 1
	swapped := Solved()
	swapped.EP[0], swapped.EP[1] = swapped.EP[1], swapped.EP[0]
	cases := []struct {
		name, facelets, want string
	}{
		{"twisted corner", twisted.Facelets(), "twisted"},
		{"flipped edge", flipped.Facelets(), "flipped"},
		{"swapped pair parity", swapped.Facelets(), "parity"},
		{"too short", SolvedFacelets[:53], "54 letters"},
		{"bad letter", SolvedFacelets[:53] + "X", "invalid letter"},
		{"bad census", SolvedFacelets[:53] + "R", "9 times"},
		{"moved centers", "UUUURUUUU" + SolvedFacelets[9:13] + "U" + SolvedFacelets[14:], "center"},
	}
	for _, tc := range cases {
		_, err := ParseFacelets(tc.facelets)
		if err == nil || !contains(err.Error(), tc.want) {
			t.Errorf("%s: got %v, want error containing %q", tc.name, err, tc.want)
		}
	}
	// opposite colors on one corner / duplicate edge
	f := []byte(SolvedFacelets)
	f[8], f[9] = f[9], f[8] // swap U9 and R1 stickers: corner URF becomes R U F
	if _, err := ParseFacelets(string(f)); err == nil {
		t.Error("expected error for mis-colored corner")
	}
	// lowercase and whitespace are accepted
	if _, err := ParseFacelets("  " + lower(SolvedFacelets[:27]) + "\n" + SolvedFacelets[27:]); err != nil {
		t.Errorf("lowercase/whitespace should parse: %v", err)
	}
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

func lower(s string) string {
	b := []byte(s)
	for i := range b {
		b[i] += 'a' - 'A'
	}
	return string(b)
}

func TestParseMovesEdgeCases(t *testing.T) {
	ok := map[string]string{
		"R2'": "R2", "R'2": "R2", "R3": "R'", "R22": "", "": "", "  ": "", "(R U)": "R U", "R’": "R'",
		"RUR'U'": "R U R' U'", "F B' ,L": "F B' L", "U2 U2": "U2 U2",
	}
	for in, want := range ok {
		ms, err := ParseMoves(in)
		if err != nil {
			t.Errorf("%q: %v", in, err)
			continue
		}
		if FormatMoves(ms) != want {
			t.Errorf("%q -> %q, want %q", in, FormatMoves(ms), want)
		}
	}
	for _, in := range []string{"x", "R U M", "Rw", "r", "R U z", "J", "R-", "1", "R4"} {
		if _, err := ParseMoves(in); err == nil {
			t.Errorf("%q should be rejected", in)
		}
	}
}

func TestSimplifyPreservesCube(t *testing.T) {
	r := rand.New(rand.NewSource(9))
	for i := 0; i < 2000; i++ {
		ms := randSeq(r, r.Intn(30))
		s := Simplify(ms)
		if FromMoves(s) != FromMoves(ms) {
			t.Fatalf("simplify changed the cube: %s -> %s", FormatMoves(ms), FormatMoves(s))
		}
		if len(s) > len(ms) {
			t.Fatal("simplify grew the sequence")
		}
		if again := Simplify(s); len(again) != len(s) {
			t.Fatalf("simplify not idempotent: %s -> %s", FormatMoves(s), FormatMoves(again))
		}
	}
	got, _ := ParseMoves("R L R' U U' D' D")
	if FormatMoves(Simplify(got)) != "L" {
		t.Errorf("R L R' U U' D' D -> %s", FormatMoves(Simplify(got)))
	}
}

func TestSolverKnownHardStates(t *testing.T) {
	superflip, _ := ParseMoves("U R2 F B R B2 R U2 L B2 R U' D' R2 F R' L B2 U2 F2")
	checker, _ := ParseMoves("U2 D2 R2 L2 F2 B2")
	for name, ms := range map[string][]Move{"superflip": superflip, "checkerboard-ish": checker, "solved": nil, "single": {Move(4)}} {
		c := FromMoves(ms)
		res, err := Solve(c, Options{Target: 22, TimeLimit: 500e6})
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if PhysicalFaceletsFrom(c.Facelets(), res.Moves) != SolvedFacelets {
			t.Fatalf("%s: physical check failed", name)
		}
		if len(res.Moves) > 24 {
			t.Errorf("%s: %d moves is unexpectedly long", name, len(res.Moves))
		}
	}
	if _, err := Solve(Cube{}, Options{}); err == nil {
		t.Error("zero cube must be rejected")
	}
}

func TestGiveUp(t *testing.T) {
	c := RandomState(rand.New(rand.NewSource(4)))
	_, err := Solve(c, Options{MaxLen: 12, HardLimit: 300e6})
	if err == nil {
		t.Fatal("expected failure for MaxLen 12 on a random state")
	}
}

func TestRandomGenerators(t *testing.T) {
	r := rand.New(rand.NewSource(11))
	seen := map[[8]uint8]bool{}
	for i := 0; i < 300; i++ {
		c := RandomState(r)
		if err := c.Check(); err != nil {
			t.Fatal(err)
		}
		seen[c.CP] = true
		ms := RandomMoves(r, 25)
		if len(ms) != 25 {
			t.Fatal("wrong scramble length")
		}
		for j := 1; j < len(ms); j++ {
			if ms[j].Face() == ms[j-1].Face() {
				t.Fatal("same face twice in a row")
			}
		}
	}
	if len(seen) < 250 {
		t.Errorf("random states look non-uniform: only %d distinct corner perms of 300", len(seen))
	}
}
