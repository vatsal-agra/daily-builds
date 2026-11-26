package main

import (
	"math"
	"math/rand"
	"strings"
	"testing"
)

func solve(t *testing.T, g Game, iters int) (*Tree, Profile) {
	t.Helper()
	tr, err := Compile(g)
	if err != nil {
		t.Fatal(err)
	}
	s := NewSolver(tr)
	for i := 0; i < iters; i++ {
		s.Step()
	}
	return tr, s.Average()
}

func near(a, b, tol float64) bool { return math.Abs(a-b) <= tol }

func TestKuhnSolvesToTheoreticalValue(t *testing.T) {
	tr, prof := solve(t, Kuhn{}, 3000)
	if v := tr.Value(prof); !near(v, -1.0/18, 1e-4) {
		t.Fatalf("Kuhn value %v want -1/18", v)
	}
	if e, _, _ := tr.Exploitability(prof); e > 1e-3 {
		t.Fatalf("exploitability %v", e)
	}
	// Equilibrium family: P0 bets Jack with alpha in [0,1/3], Kings with 3*alpha.
	ji, _ := tr.SetIndex("0J:")
	ki, _ := tr.SetIndex("0K:")
	alpha, kb := prof[ji][1], prof[ki][1]
	if alpha < -1e-3 || alpha > 1.0/3+1e-2 || !near(kb, 3*alpha, 0.03) {
		t.Fatalf("not on the Kuhn equilibrium family: J bet %v K bet %v", alpha, kb)
	}
	// P1 with Queen facing a bet calls 1/3, P1 with Jack always folds, King always calls.
	qi, _ := tr.SetIndex("1Q:b")
	if !near(prof[qi][1], 1.0/3, 0.02) {
		t.Fatalf("P1 Q call freq %v want 1/3", prof[qi][1])
	}
}

func TestLeducSolvesToKnownValue(t *testing.T) {
	tr, prof := solve(t, Leduc{}, 1500)
	if len(tr.Sets) != 288 {
		t.Fatalf("leduc info sets %d", len(tr.Sets))
	}
	if v := tr.Value(prof); !near(v, -0.08565, 0.002) {
		t.Fatalf("Leduc value %v want ≈ -0.0856", v)
	}
	if e, _, _ := tr.Exploitability(prof); e > 0.001 {
		t.Fatalf("exploitability %v", e)
	}
}

func TestExploitabilityMonotoneish(t *testing.T) {
	tr, _ := Compile(Leduc{})
	s := NewSolver(tr)
	var e [3]float64
	for i, n := range []int{5, 50, 500} {
		for s.Iter < n {
			s.Step()
		}
		e[i], _, _ = tr.Exploitability(s.Average())
	}
	if !(e[0] > e[1] && e[1] > e[2]) {
		t.Fatalf("exploitability not decreasing: %v", e)
	}
}

func TestBestResponseAgainstKnownBots(t *testing.T) {
	tr, _ := Compile(Kuhn{})
	nit, _ := tr.BotProfile("nit")
	// vs a player who folds to everything and never bets, bet always: win exactly 1 per hand.
	if e, b0, b1 := tr.Exploitability(nit); !near(e, 1, 1e-9) || !near(b0, 1, 1e-9) || !near(b1, 1, 1e-9) {
		t.Fatalf("nit exploitability %v %v %v", e, b0, b1)
	}
	u := tr.Uniform()
	if e, _, _ := tr.Exploitability(u); e <= 0.1 {
		t.Fatalf("uniform should be quite exploitable, got %v", e)
	}
}

func TestBestResponseIsAtLeastAnyOtherResponse(t *testing.T) {
	tr, prof := solve(t, Leduc{}, 50) // deliberately unconverged
	for _, bot := range BotNames() {
		b, _ := tr.BotProfile(bot)
		_, br0 := tr.BestResponse(prof, 0)
		v := tr.Value(tr.Compose(b, prof))
		if v > br0+1e-9 {
			t.Fatalf("bot %s beats the 'best response' as P0: %v > %v", bot, v, br0)
		}
		_, br1 := tr.BestResponse(prof, 1)
		if v1 := -tr.Value(tr.Compose(prof, b)); v1 > br1+1e-9 {
			t.Fatalf("bot %s beats the 'best response' as P1", bot)
		}
	}
}

func TestStrategyRoundTrip(t *testing.T) {
	tr, prof := solve(t, Kuhn{}, 200)
	path := t.TempDir() + "/k.json"
	if err := SaveStrategy(path, tr.ToFile(prof, 200)); err != nil {
		t.Fatal(err)
	}
	f, err := LoadStrategy(path)
	if err != nil {
		t.Fatal(err)
	}
	back, err := tr.FromFile(f)
	if err != nil {
		t.Fatal(err)
	}
	for i := range prof {
		for a := range prof[i] {
			if !near(prof[i][a], back[i][a], 1e-9) {
				t.Fatal("mismatch after round trip")
			}
		}
	}
	lt, _ := Compile(Leduc{})
	if _, err := lt.FromFile(f); err == nil {
		t.Fatal("kuhn strategy accepted for leduc")
	}
}

func TestFiveCardCategoryCounts(t *testing.T) {
	want := [9]int{1302540, 1098240, 123552, 54912, 10200, 5108, 3744, 624, 40}
	var got [9]int
	h := make([]int, 5)
	var rec func(start, k int)
	total := 0
	rec = func(start, k int) {
		if k == 5 {
			got[CategoryOf(Eval(h))]++
			total++
			return
		}
		for c := start; c < 52; c++ {
			h[k] = c
			rec(c+1, k+1)
		}
	}
	rec(0, 0)
	if total != 2598960 || got != want {
		t.Fatalf("category counts %v want %v", got, want)
	}
}

func hand(t *testing.T, s string) []int {
	t.Helper()
	c, err := ParseCards(s)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestEvalOrderingAndSevenCards(t *testing.T) {
	order := []string{
		"7c5d4h3s2c9d8h", // high card (no straight/flush)
		"AsAd5h4c3d9c2h", // wheel straight beats pair? A-2-3-4-5 straight
	}
	_ = order
	cases := []struct{ better, worse string }{
		{"AsKsQsJsTs2d3c", "KcKdKhKs2d3c4h"}, // royal > quads
		{"AsAdAh2c2d7c9h", "KcKdKh2h2s7d9c"}, // boat A > boat K
		{"AsAdAh2c2d7c9h", "AsAdAhKcQd7c9h"}, // boat > trips
		{"2c3c4c5c7c9dKh", "AsAdAhKcQd7c9h"}, // flush > trips
		{"AsKd2c3h4d5s9c", "KsKdQh8c4d3s2c"}, // wheel straight > pair
		{"6c5d4h3s2c9d9h", "AsKd2c3h4d5s9c"}, // six-high straight > wheel
		{"AsAdKcKd9h2c3d", "AsAdKcQd9h2c3d"}, // two pair beats pair
		{"AsKdQcJd9h2c3d", "AsKdQcJd8h2c3d"}, // kicker
		{"AsAdKcKd9h9c3d", "AsAdKcKd8h8c3d"}, // best two pair of three
	}
	for _, c := range cases {
		if Eval(hand(t, c.better)) <= Eval(hand(t, c.worse)) {
			t.Errorf("%s should beat %s (%s vs %s)", c.better, c.worse, DescribeScore(Eval(hand(t, c.better))), DescribeScore(Eval(hand(t, c.worse))))
		}
	}
	if Eval(hand(t, "AsAdKcKd9h2c3d")) != Eval(hand(t, "AhAcKsKh9d2d3s")) {
		t.Error("suits must not matter")
	}
	// the board plays: both players tie
	if Eval(hand(t, "AsKsQsJsTs2d3c")) != Eval(hand(t, "AsKsQsJsTs4d5c")) {
		t.Error("royal on board should tie")
	}
	if d := DescribeScore(Eval(hand(t, "AsAdAh2c2d7c9h"))); d != "Full house, As full of 2s" {
		t.Errorf("describe: %s", d)
	}
}

func TestRangeParsing(t *testing.T) {
	cases := map[string]int{
		"AA": 6, "AKs": 4, "AKo": 12, "AK": 16, "QQ+": 18, "AJs+": 12, "77-55": 18,
		"A5s-A2s": 16, "T9s-54s": 24, "AhKd": 1, "random": 1326, "AA, KK": 12, "AKs,AKs": 4,
		"ATo+": 48, "22+": 78, "KQo-KTo": 36,
	}
	for spec, n := range cases {
		r, err := ParseRange(spec)
		if err != nil {
			t.Errorf("%s: %v", spec, err)
			continue
		}
		if len(r) != n {
			t.Errorf("%s: %d combos, want %d", spec, len(r), n)
		}
	}
	for _, bad := range []string{"", "AAs", "XX", "AKx", "AA-KQ", "A5s-K2o", "AhAh", "Ah", "AKs-AQo"} {
		if _, err := ParseRange(bad); err == nil {
			t.Errorf("%q should be rejected", bad)
		}
	}
}

func eq(t *testing.T, board, dead string, specs ...string) *EquityResult {
	t.Helper()
	var rs [][]Combo
	for _, s := range specs {
		r, err := ParseRange(s)
		if err != nil {
			t.Fatal(err)
		}
		rs = append(rs, r)
	}
	o := EquityOpts{}
	if board != "" {
		o.Board = hand(t, board)
	}
	if dead != "" {
		o.Dead = hand(t, dead)
	}
	res, err := Equity(rs, o)
	if err != nil {
		t.Fatal(err)
	}
	return res
}

func TestEquityKnownMatchups(t *testing.T) {
	r := eq(t, "", "", "AhAs", "KdKc")
	if !r.Exact || !near(r.Equity[0], 0.8126, 0.002) {
		t.Fatalf("AA v KK %v exact=%v", r.Equity[0], r.Exact)
	}
	r = eq(t, "", "", "AsKs", "QhQd")
	if !near(r.Equity[0], 0.4621, 0.002) {
		t.Fatalf("AKs v QQ %v", r.Equity[0])
	}
	// equities of all players sum to 1
	r = eq(t, "", "", "AhAs", "KdKc", "QdQc")
	if s := r.Equity[0] + r.Equity[1] + r.Equity[2]; !near(s, 1, 1e-9) {
		t.Fatalf("multiway sum %v", s)
	}
	// river: made hand vs made hand is deterministic
	r = eq(t, "AcKd2h7s9d", "", "AhAd", "KhKs")
	if r.Equity[0] != 1 || r.Equity[1] != 0 {
		t.Fatalf("river %v", r.Equity)
	}
	// identical hands on a board tie
	r = eq(t, "AcKd2h7s9d", "", "QhQd", "QcQs")
	if r.Equity[0] != 0.5 {
		t.Fatalf("expected chop, got %v", r.Equity)
	}
	// flush draw vs top pair on flop is a classic ~ 45/55
	r = eq(t, "Ks7s2d", "", "AsQs", "KhKd")
	if !near(r.Equity[0], 0.2556, 0.003) {
		t.Fatalf("nut flush draw + overs vs set %v", r.Equity[0])
	}
}

func TestEquityMonteCarloMatchesExactAndIsSeeded(t *testing.T) {
	a, _ := ParseRange("AhKh")
	b, _ := ParseRange("QsQd")
	ex, _ := Equity([][]Combo{a, b}, EquityOpts{})
	mc, _ := Equity([][]Combo{a, b}, EquityOpts{ExactLimit: 1, Samples: 300000, Seed: 7})
	mc2, _ := Equity([][]Combo{a, b}, EquityOpts{ExactLimit: 1, Samples: 300000, Seed: 7})
	if mc.Exact || !ex.Exact {
		t.Fatal("mode selection wrong")
	}
	if !near(mc.Equity[0], ex.Equity[0], 4*mc.StdErr[0]+1e-9) {
		t.Fatalf("mc %v ± %v vs exact %v", mc.Equity[0], mc.StdErr[0], ex.Equity[0])
	}
	if mc.Equity[0] != mc2.Equity[0] {
		t.Fatal("same seed must reproduce")
	}
}

func TestEquityErrors(t *testing.T) {
	a, _ := ParseRange("AhKh")
	b, _ := ParseRange("AhKd")
	if _, err := Equity([][]Combo{a, b}, EquityOpts{}); err == nil || !strings.Contains(err.Error(), "conflict") {
		t.Fatalf("overlapping fixed hands should error, got %v", err)
	}
	if _, err := Equity([][]Combo{a}, EquityOpts{}); err == nil {
		t.Fatal("one player")
	}
	c, _ := ParseRange("QsQd")
	if _, err := Equity([][]Combo{a, c}, EquityOpts{Board: hand(t, "Ah7d2c")}); err == nil {
		t.Fatal("hand blocked by board should error")
	}
	if _, err := Equity([][]Combo{a, c}, EquityOpts{Board: hand(t, "7d2c")}); err == nil {
		t.Fatal("2-card board")
	}
}

func TestSevenCardEvalEqualsBestFiveOfSeven(t *testing.T) {
	rng := rand.New(rand.NewSource(99))
	deck := make([]int, 52)
	for i := range deck {
		deck[i] = i
	}
	for trial := 0; trial < 60000; trial++ {
		rng.Shuffle(52, func(i, j int) { deck[i], deck[j] = deck[j], deck[i] })
		seven := deck[:7]
		want := uint32(0)
		for skip1 := 0; skip1 < 7; skip1++ {
			for skip2 := skip1 + 1; skip2 < 7; skip2++ {
				var five []int
				for i, c := range seven {
					if i != skip1 && i != skip2 {
						five = append(five, c)
					}
				}
				if v := Eval(five); v > want {
					want = v
				}
			}
		}
		if got := Eval(seven); got != want {
			t.Fatalf("7-card eval %x != best-5 %x for %v", got, want, seven)
		}
	}
}

func TestRegressionLeducAntesAndFoldSentinel(t *testing.T) {
	tr, _ := Compile(Leduc{})
	nit, _ := tr.BotProfile("nit")
	if e, _, _ := tr.Exploitability(nit); !near(e, 1, 1e-9) {
		t.Fatalf("a bot that folds to everything must lose exactly the 1-chip ante: %v", e)
	}
	// a check-down showdown with both players calling stations wins/loses only the ante
	st, _ := tr.BotProfile("station")
	if v := tr.Value(st); !near(v, 0, 1e-9) {
		t.Fatalf("station mirror should be 0, got %v", v)
	}
}

func TestResolveStrategyErrors(t *testing.T) {
	tr, _ := Compile(Kuhn{})
	if _, err := ResolveStrategy(tr, "nobody", 10); err == nil || !strings.Contains(err.Error(), "station") {
		t.Fatalf("expected helpful error, got %v", err)
	}
}

func TestCLIValidation(t *testing.T) {
	bad := [][]string{
		{"play", "kuhn", "-hands", "-1"}, {"equity", "-n", "-5", "AA", "KK"}, {"solve", "kuhn", "-iters", "0"},
		{"match", "kuhn", "-hands", "0"}, {"exploit", "kuhn", "solved", "-iters", "0"}, {"nope"},
	}
	for _, a := range bad {
		var sb strings.Builder
		if err := runTo(a, &sb, strings.NewReader("")); err == nil {
			t.Errorf("%v should fail", a)
		}
	}
}
