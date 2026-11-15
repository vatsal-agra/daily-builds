package sok

import (
	"os"
	"strings"
	"testing"
)

func mustParse(t *testing.T, s string) *Level {
	t.Helper()
	lv, err := Parse(s)
	if err != nil {
		t.Fatalf("parse: %v\n%s", err, s)
	}
	return lv
}

func TestParseErrors(t *testing.T) {
	cases := map[string]string{
		"":                     "empty level",
		"###\n#@#\n###":        "no boxes",
		"#####\n#@$$.#\n#####": "2 boxes but 1 goals",
		"#####\n#@@$.#\n#####": "exactly one player",
		"#####\n#$.#\n#####":   "exactly one player",
		"#####\n#@$x#\n#####":  "illegal character 'x'",
		"#####\n#@$.\n#####":   "not enclosed",
		"#####\n#@ $.\n#####":  "box or goal on the grid edge",
	}
	for in, want := range cases {
		_, err := Parse(in)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("Parse(%q) error = %v, want substring %q", in, err, want)
		}
	}
	if _, err := Parse("#####\n#@$x#\n#####"); err == nil || err.(*ParseError).Line != 2 {
		t.Errorf("error line number wrong: %v", err)
	}
}

func TestParseFormatRoundTrip(t *testing.T) {
	src := "#######\n#  .  #\n# $*$ #\n#  .@ #\n#. $  #\n#######\n"
	lv := mustParse(t, src)
	if got := lv.String(); got != src {
		t.Errorf("round trip mismatch:\n%s\nvs\n%s", got, src)
	}
	lv2 := mustParse(t, "#####\n#+$ #\n#   #\n#####\n")
	if !lv2.Goal[lv2.Player] {
		t.Error("'+' must put the player on a goal")
	}
}

func TestParseCRLFAndComments(t *testing.T) {
	lvs, err := ParsePack(";junk\n\n;Title A\r\n#####\r\n#@$.#\r\n#####\r\n\r\n#####\n#@$.#\n#####\n")
	if err != nil || len(lvs) != 2 {
		t.Fatalf("pack: %v %d", err, len(lvs))
	}
	if lvs[0].Name != "Title A" || lvs[1].Name != "Level 2" {
		t.Errorf("names: %q %q", lvs[0].Name, lvs[1].Name)
	}
	_, err = ParsePack("#####\n#@$.#\n#####\n\n#####\n#@ .#\n#####\n")
	if err == nil || !strings.Contains(err.Error(), "line 5") || !strings.Contains(err.Error(), "level 2") {
		t.Errorf("pack error should cite level 2 / line 5, got %v", err)
	}
}

func TestReplayRules(t *testing.T) {
	lv := mustParse(t, "#######\n#@$ . #\n#######\n")
	if r, err := lv.Verify("RR"); err != nil || r.Pushes != 2 || r.Moves != 2 || !r.Solved {
		t.Fatalf("RR: %+v %v", r, err)
	}
	if _, err := lv.Replay("L"); err == nil || !strings.Contains(err.Error(), "wall") {
		t.Errorf("walking into wall: %v", err)
	}
	if _, err := lv.Replay("RRRR"); err == nil || !strings.Contains(err.Error(), "push blocked") {
		t.Errorf("pushing box into wall: %v", err)
	}
	if _, err := lv.Replay("Rq"); err == nil || !strings.Contains(err.Error(), "illegal character") {
		t.Errorf("illegal char: %v", err)
	}
	if _, err := lv.Verify("R"); err == nil || !strings.Contains(err.Error(), "unsolved") {
		t.Errorf("legal-but-unsolved must fail Verify: %v", err)
	}
	two := mustParse(t, "#########\n#@$$ .. #\n#########\n")
	if _, err := two.Replay("R"); err == nil || !strings.Contains(err.Error(), "push blocked") {
		t.Errorf("box-behind-box push must be illegal: %v", err)
	}
}

func TestDeadSquaresAndPushDist(t *testing.T) {
	lv := mustParse(t, "#######\n#.    #\n#     #\n#  @$ #\n#     #\n#######\n")
	a := Analyze(lv)
	at := func(x, y int) int { return y*lv.W + x }
	for _, c := range [][2]int{{5, 1}, {5, 4}, {1, 4}, {5, 2}} { // right wall + corners not on goal row/col
		if !a.Dead[at(c[0], c[1])] {
			t.Errorf("cell %v should be dead", c)
		}
	}
	for _, c := range [][2]int{{1, 1}, {1, 2}, {2, 1}, {3, 3}, {4, 3}} {
		if a.Dead[at(c[0], c[1])] {
			t.Errorf("cell %v should be alive", c)
		}
	}
	// box at (4,3) to goal (1,1): needs 3 pushes left + 2 up = 5
	if d := a.PushDist[0][at(4, 3)]; d != 5 {
		t.Errorf("push distance = %d, want 5", d)
	}
}

func TestFreezeDeadlock(t *testing.T) {
	lv := mustParse(t, "#########\n#       #\n# .  .  #\n#       #\n#   @   #\n# $  $  #\n#########\n")
	a := Analyze(lv)
	at := func(x, y int) int { return y*lv.W + x }
	mk := func(cells ...int) []bool {
		g := make([]bool, lv.W*lv.H)
		for _, c := range cells {
			g[c] = true
		}
		return g
	}
	// 2x2 block in open floor, none on goal: frozen.
	sq := mk(at(4, 3), at(5, 3), at(4, 4), at(5, 4))
	if !a.FreezeDeadlock(sq, at(4, 3)) {
		t.Error("2x2 block off-goal must be a freeze deadlock")
	}
	// Single box in the open: fine.
	if a.FreezeDeadlock(mk(at(4, 3)), at(4, 3)) {
		t.Error("lone box in open floor is not frozen")
	}
	// Box in a corner on a non-goal: frozen (and a dead square).
	if !a.FreezeDeadlock(mk(at(1, 1)), at(1, 1)) {
		t.Error("corner box must be deadlocked")
	}
	// Two boxes side by side against the wall: frozen pair, not on goals.
	if !a.FreezeDeadlock(mk(at(3, 1), at(4, 1)), at(3, 1)) {
		t.Error("two adjacent boxes along a wall (no goals there) must be deadlocked")
	}
	// Same 2x2 block but all on goals: no deadlock.
	g := mustParse(t, "#######\n#     #\n# **  #\n# **@ #\n#     #\n#######\n")
	ga := Analyze(g)
	gat := func(x, y int) int { return y*g.W + x }
	gb := make([]bool, g.W*g.H)
	for _, c := range []int{gat(2, 2), gat(3, 2), gat(2, 3), gat(3, 3)} {
		gb[c] = true
	}
	if ga.FreezeDeadlock(gb, gat(2, 2)) {
		t.Error("frozen block entirely on goals is fine")
	}
}

func TestSolverKnownAndOracle(t *testing.T) {
	pack, err := os.ReadFile("../levels/starter.txt")
	if err != nil {
		t.Fatal(err)
	}
	lvs, err := ParsePack(string(pack))
	if err != nil {
		t.Fatal(err)
	}
	for _, lv := range lvs {
		sol, err := Solve(lv, Options{})
		if err != nil {
			t.Fatalf("%s: %v", lv.Name, err)
		}
		if want := bruteOptimalPushes(lv, 500000); want != sol.Pushes {
			t.Errorf("%s: solver %d pushes, oracle %d", lv.Name, sol.Pushes, want)
		}
		if r, err := lv.Verify(sol.Moves); err != nil || r.Pushes != sol.Pushes || r.Moves != sol.WalkMoves {
			t.Errorf("%s: verify %v %+v", lv.Name, err, r)
		}
	}
	first, _ := Solve(lvs[0], Options{})
	if first.Pushes != 8 {
		t.Errorf("First Steps (Microban #1) needs 8 pushes, got %d", first.Pushes)
	}
}

func TestSolverEdgeOutcomes(t *testing.T) {
	s0 := mustParse(t, "####\n#@*#\n####\n")
	if sol, err := Solve(s0, Options{}); err != nil || sol.Pushes != 0 || sol.Moves != "" {
		t.Errorf("already solved: %+v %v", sol, err)
	}
	// boxes glued to the top wall with goals elsewhere: provably unsolvable.
	u := mustParse(t, "######\n#@$$ #\n#   .#\n#   .#\n######\n")
	if _, err := Solve(u, Options{}); err != ErrUnsolvable {
		t.Errorf("want ErrUnsolvable, got %v", err)
	}
	// Needs a pull that doesn't exist: box in the corner, goal elsewhere.
	c := mustParse(t, "#####\n#$ .#\n# @ #\n#####\n")
	if _, err := Solve(c, Options{}); err != ErrUnsolvable {
		t.Errorf("corner box: want ErrUnsolvable, got %v", err)
	}
	// Budget error on a level that needs more than 1 expansion.
	pack, _ := os.ReadFile("../levels/generated.txt")
	lvs, _ := ParsePack(string(pack))
	if _, err := Solve(lvs[len(lvs)-1], Options{MaxNodes: 5}); err != ErrBudget {
		t.Errorf("want ErrBudget, got %v", err)
	}
}

func TestHeuristicAdmissible(t *testing.T) {
	pack, _ := os.ReadFile("../levels/generated.txt")
	lvs, _ := ParsePack(string(pack))
	for _, lv := range lvs[:4] {
		sol, err := Solve(lv, Options{})
		if err != nil {
			t.Fatal(err)
		}
		s := &solver{lv: lv, an: Analyze(lv)}
		nb := len(lv.Boxes)
		s.hungC = make([][]int, nb+1)
		for i := range s.hungC {
			s.hungC[i] = make([]int, nb+1)
		}
		s.hungU, s.hungV, s.hungP, s.hungW, s.hungMn = make([]int, nb+1), make([]int, nb+1), make([]int, nb+1), make([]int, nb+1), make([]int, nb+1)
		bx := make([]uint16, nb)
		for i, b := range lv.Boxes {
			bx[i] = uint16(b)
		}
		if h := s.heuristic(bx); h > sol.Pushes || h <= 0 {
			t.Errorf("%s: h=%d must be in (0, %d]", lv.Name, h, sol.Pushes)
		}
	}
}

func TestMatchingBeatsNearestGoal(t *testing.T) {
	pack, _ := os.ReadFile("../levels/generated.txt")
	lvs, _ := ParsePack(string(pack))
	lv := lvs[4]
	a, _ := Solve(lv, Options{})
	b, _ := Solve(lv, Options{NoMatching: true})
	if a.Pushes != b.Pushes {
		t.Fatalf("both heuristics must find the same optimum: %d vs %d", a.Pushes, b.Pushes)
	}
	if a.Expanded > b.Expanded {
		t.Errorf("Hungarian bound expanded %d > nearest-goal %d", a.Expanded, b.Expanded)
	}
}

func TestGeneratorDeterministicSolvableRated(t *testing.T) {
	o := GenOptions{W: 9, H: 8, Boxes: 3, Seed: 42, Attempts: 60, WallDens: 0.12, MinPushes: 8}
	g1, err := Generate(o)
	if err != nil {
		t.Fatal(err)
	}
	g2, _ := Generate(o)
	if g1.Level.String() != g2.Level.String() || g1.Solution.Moves != g2.Solution.Moves {
		t.Error("same seed+options must give an identical level")
	}
	o.Seed = 43
	g3, _ := Generate(o)
	if g3 != nil && g3.Level.String() == g1.Level.String() {
		t.Error("different seeds should differ")
	}
	if g1.Solution.Pushes < 8 {
		t.Errorf("min-pushes violated: %d", g1.Solution.Pushes)
	}
	if _, err := g1.Level.Verify(g1.Solution.Moves); err != nil {
		t.Errorf("generated solution fails verification: %v", err)
	}
	if g1.Rating == "" || g1.Rated == 0 {
		t.Error("rating/stats missing")
	}
	// the printed level must parse back into the same puzzle
	back := mustParse(t, g1.Level.String())
	if back.String() != g1.Level.String() {
		t.Error("generated level does not round-trip through XSB")
	}
}

func TestGeneratorManyAreSolvable(t *testing.T) {
	n := 0
	for seed := int64(1); seed <= 12; seed++ {
		g, err := Generate(GenOptions{W: 8, H: 8, Boxes: 2 + int(seed%3), Seed: seed, Attempts: 20, WallDens: 0.1})
		if err != nil {
			continue
		}
		n++
		if _, err := g.Level.Verify(g.Solution.Moves); err != nil {
			t.Errorf("seed %d: %v", seed, err)
		}
		if g.Solution.Pushes < 1 {
			t.Errorf("seed %d: 0-push level generated", seed)
		}
	}
	if n < 8 {
		t.Errorf("only %d/12 seeds produced a level", n)
	}
}

func TestGeneratorValidation(t *testing.T) {
	bad := []GenOptions{
		{W: 4, H: 8, Boxes: 1}, {W: 8, H: 8, Boxes: 0}, {W: 8, H: 8, Boxes: 13},
		{W: 5, H: 5, Boxes: 6}, {W: 8, H: 8, Boxes: 2, WallDens: 0.9}, {W: 41, H: 8, Boxes: 2},
	}
	for _, o := range bad {
		if _, err := Generate(o); err == nil {
			t.Errorf("expected validation error for %+v", o)
		}
	}
	if _, err := Generate(GenOptions{W: 9, H: 9, Boxes: 2, Seed: 1, Attempts: 5, MinPushes: 10000}); err != ErrNoCandidate {
		t.Errorf("impossible min-pushes should give ErrNoCandidate, got %v", err)
	}
}

func TestBuildHTML(t *testing.T) {
	lv := mustParse(t, ";<script>alert(1)</script>\n#####\n#@$.#\n#####\n")
	page, levels, err := BuildHTML(`A "quoted" <title>`, []*Level{lv}, nil, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if len(levels) != 1 || levels[0].Solution != "R" || levels[0].Pushes != 1 {
		t.Errorf("levels: %+v", levels)
	}
	if strings.Contains(page, "<script>alert") || strings.Contains(page, "A \"quoted\" <title>") {
		t.Error("user-controlled text must be escaped in the page")
	}
	if strings.Count(page, "</script>") != 1 {
		t.Errorf("exactly one closing script tag expected, got %d", strings.Count(page, "</script>"))
	}
	if _, _, err := BuildHTML("x", []*Level{lv}, []*Solution{{Moves: "L"}}, Options{}); err == nil {
		t.Error("bad solution must be refused")
	}
	u := mustParse(t, "######\n#@$$ #\n#   .#\n#   .#\n######\n")
	if _, _, err := BuildHTML("x", []*Level{u}, nil, Options{}); err == nil {
		t.Error("unsolvable level must be refused")
	}
}
