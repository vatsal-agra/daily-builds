package main

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var sharedMatrix *EqMatrix

func matrix(t *testing.T) *EqMatrix {
	t.Helper()
	if sharedMatrix == nil {
		t.Setenv("XDG_CACHE_HOME", t.TempDir())
		m, err := BuildEqMatrix(800, 1, nil)
		if err != nil {
			t.Fatal(err)
		}
		sharedMatrix = m
	}
	return sharedMatrix
}

func TestClassGridAndNames(t *testing.T) {
	seen := map[string]bool{}
	total := 0
	for id := 0; id < nClass; id++ {
		n := ClassName(id)
		if seen[n] {
			t.Fatalf("duplicate class name %s", n)
		}
		seen[n] = true
		back, err := ClassID(n)
		if err != nil || back != id {
			t.Fatalf("ClassID(%s) = %d,%v want %d", n, back, err, id)
		}
		total += len(classComboList(id))
	}
	if total != 1326 {
		t.Fatalf("classes cover %d combos, want 1326", total)
	}
	if ClassName(0) != "AA" || ClassName(1) != "AKs" || ClassName(13) != "AKo" || ClassName(168) != "22" {
		t.Fatal("grid orientation wrong")
	}
	if _, err := ClassID("AK"); err == nil {
		t.Fatal("AK without suffix must be rejected")
	}
}

func TestEquityMatrixSanity(t *testing.T) {
	m := matrix(t)
	aa, _ := ClassID("AA")
	kk, _ := ClassID("KK")
	s72, _ := ClassID("72o")
	if e := m.Eq[aa][kk]; !near(e, 0.82, 0.04) {
		t.Fatalf("AA vs KK %v", e)
	}
	if e := m.Eq[aa][s72]; e < 0.8 {
		t.Fatalf("AA vs 72o %v", e)
	}
	for i := 0; i < nClass; i += 7 {
		for j := 0; j < nClass; j += 11 {
			if !near(m.Eq[i][j]+m.Eq[j][i], 1, 1e-6) {
				t.Fatal("equities must be complementary")
			}
		}
	}
	// weights: AA vs AA has 6*1 = 6 non-conflicting combo pairs (C(4,2)*C(2,2) ordered)
	if m.W[aa][aa] != 6 {
		t.Fatalf("AA-vs-AA weight %v want 6", m.W[aa][aa])
	}
	var tot float64
	for i := 0; i < nClass; i++ {
		for j := 0; j < nClass; j++ {
			tot += m.W[i][j]
		}
	}
	if tot != 1326*1225 {
		t.Fatalf("total weight %v want %v", tot, 1326*1225)
	}
}

func TestPushFoldEquilibriumProperties(t *testing.T) {
	m := matrix(t)
	aa, _ := ClassID("AA")
	s72, _ := ClassID("72o")
	a5s, _ := ClassID("A5s")
	var prev *PushFold
	for _, st := range []float64{4, 8, 12, 20} {
		pf, err := SolvePushFold(m, st, 3000)
		if err != nil {
			t.Fatal(err)
		}
		if pf.Gap > 1e-3 {
			t.Fatalf("stack %v: not an equilibrium, gap %v", st, pf.Gap)
		}
		if pf.Shove[aa] < 0.99 || pf.Call[aa] < 0.99 {
			t.Fatalf("stack %v: AA must always shove and call", st)
		}
		if st >= 12 && pf.Shove[s72] > 0.01 {
			t.Fatalf("stack %v: 72o should fold from the SB", st)
		}
		if prev != nil && !(pf.ShovePct < prev.ShovePct+0.5 && pf.CallPct < prev.CallPct+0.5) {
			t.Fatalf("ranges must tighten as stacks deepen: %+v vs %+v", pf.ShovePct, prev.ShovePct)
		}
		if st == 10 || st == 8 {
			if pf.ShovePct < 50 || pf.ShovePct > 70 {
				t.Fatalf("stack %v shove%% %v outside published range", st, pf.ShovePct)
			}
		}
		prev = pf
	}
	// 10bb: A5s is a shove and a call, matching published charts.
	pf, _ := SolvePushFold(m, 10, 3000)
	if pf.Shove[a5s] < 0.9 {
		t.Fatalf("A5s should shove at 10bb: %v", pf.Shove[a5s])
	}
	if pf.CallPct < 30 || pf.CallPct > 45 {
		t.Fatalf("10bb call%% %v", pf.CallPct)
	}
	// SB is at a positional disadvantage at depth (value negative) and the game is zero-sum-consistent.
	if pf.SBValue > 0 {
		t.Fatalf("SB value at 10bb should be negative: %v", pf.SBValue)
	}
	// Nash gap proves optimality: no deviation helps. Spot check by forcing SB to shove 72o.
	dev := pf.Shove
	dev[s72] = 1
	if v := sbValue(m, 10, &dev, &pf.Call); v > pf.SBValue+1e-3 {
		t.Fatalf("shoving 72o improved SB: %v > %v", v, pf.SBValue)
	}
	if _, err := SolvePushFold(m, 0.2, 10); err == nil {
		t.Fatal("tiny stack must be rejected")
	}
}

func TestEqMatrixDeterministic(t *testing.T) {
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	a, _ := BuildEqMatrix(60, 5, nil)
	// second call hits the cache, third (different dir) recomputes: all identical
	b, _ := BuildEqMatrix(60, 5, nil)
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	c, _ := BuildEqMatrix(60, 5, nil)
	for i := 0; i < nClass; i += 5 {
		for j := 0; j < nClass; j += 3 {
			if math.Abs(a.Eq[i][j]-c.Eq[i][j]) > 1e-6 || math.Abs(a.Eq[i][j]-b.Eq[i][j]) > 1e-6 {
				t.Fatal("matrix not reproducible")
			}
		}
	}
	if _, err := BuildEqMatrix(3, 1, nil); err == nil {
		t.Fatal("too few samples must error")
	}
}

func TestPlaySessionScripted(t *testing.T) {
	g := Kuhn{}
	tr, prof := solve(t, g, 500)
	var out strings.Builder
	// bad input, hint, ambiguity, then valid moves; ends by EOF
	script := "\nfrobnicate\nhint\n1\n2\n1\n2\n1\n2\n1\n"
	net, hands, err := PlaySession(PlayConfig{Tree: tr, Game: g, Prof: prof, Seat: -1, Hands: 2, Seed: 4}, strings.NewReader(script), &out)
	if err != nil {
		t.Fatal(err)
	}
	s := out.String()
	for _, want := range []string{"Hand 1", "Hand 2", "you are P0", "you are P1", "is not one of", "equilibrium play here", "Result:", "Session over: "} {
		if !strings.Contains(s, want) {
			t.Errorf("transcript missing %q:\n%s", want, s)
		}
	}
	if hands != 2 {
		t.Fatalf("hands %d\n%s", hands, s)
	}
	if math.Abs(net) > 4 {
		t.Fatalf("net %v impossible for 2 Kuhn hands", net)
	}
	// EOF/quit mid-hand ends cleanly
	out.Reset()
	if _, h, err := PlaySession(PlayConfig{Tree: tr, Game: g, Prof: prof, Seat: 0, Seed: 1}, strings.NewReader("quit\n"), &out); err != nil || h != 0 || !strings.Contains(out.String(), "no hands completed") {
		t.Fatalf("quit handling: %v %d\n%s", err, h, out.String())
	}
}

func TestHintEVsAreIndifferentAtEquilibrium(t *testing.T) {
	tr, prof := solve(t, Kuhn{}, 20000)
	// P1 holding the Queen facing a bet is the textbook indifference point: fold = call = -1.
	si, _ := tr.SetIndex("1Q:b")
	v := tr.ActionValues(prof, si)
	if !near(v[0], -1, 1e-6) || !near(v[1], -1, 0.02) {
		t.Fatalf("Q facing bet values %v want both -1", v)
	}
	// King facing a bet: calling is strictly right.
	ki, _ := tr.SetIndex("1K:b")
	kv := tr.ActionValues(prof, ki)
	if kv[1] <= kv[0] {
		t.Fatalf("K should call: %v", kv)
	}
	// weighted EV over all first-player infosets equals the game value
	var ev float64
	for _, c := range []string{"J", "Q", "K"} {
		i, _ := tr.SetIndex("0" + c + ":")
		av := tr.ActionValues(prof, i)
		ev += (prof[i][0]*av[0] + prof[i][1]*av[1]) / 3
	}
	if !near(ev, tr.Value(prof), 1e-3) {
		t.Fatalf("EV across hint tables %v != game value %v", ev, tr.Value(prof))
	}
}

func TestMatchAgreesWithExactAndExploitersWin(t *testing.T) {
	g := Leduc{}
	tr, prof := solve(t, g, 800)
	for _, bot := range BotNames() {
		b, _ := tr.BotProfile(bot)
		r, err := Match(tr, g, prof, b, 60000, 11)
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(r.Mean-r.ExactEV) > 4.5*r.StdErr+1e-9 {
			t.Errorf("%s: simulated %v ± %v vs exact %v", bot, r.Mean, r.StdErr, r.ExactEV)
		}
		if r.ExactEV <= 0 {
			t.Errorf("solved strategy should beat %s, EV %v", bot, r.ExactEV)
		}
		if r.Exploitab < r.ExactEV-1e-9 {
			t.Errorf("a best response must win at least as much as the solved strategy vs %s", bot)
		}
		if r.AExploitab > 0.002 {
			t.Errorf("solved strategy exploitability %v", r.AExploitab)
		}
	}
	if _, err := Match(tr, g, prof, prof, 0, 1); err == nil {
		t.Fatal("0 hands must error")
	}
}

func TestSolvedStrategyEarnsNothingAgainstItself(t *testing.T) {
	g := Kuhn{}
	tr, prof := solve(t, g, 4000)
	r, _ := Match(tr, g, prof, prof, 50000, 3)
	if !near(r.ExactEV, 0, 1e-3) || math.Abs(r.Mean) > 4.5*r.StdErr {
		t.Fatalf("mirror match %v exact %v", r.Mean, r.ExactEV)
	}
}

func TestCLIEndToEnd(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "k.json")
	run1 := func(args ...string) string {
		t.Helper()
		var sb strings.Builder
		if err := runTo(args, &sb, strings.NewReader("")); err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		return sb.String()
	}
	if o := run1("solve", "kuhn", "-iters", "1500", "-out", file); !strings.Contains(o, "-0.0555") && !strings.Contains(o, "-0.0556") {
		t.Fatalf("solve output: %s", o)
	}
	if o := run1("exploit", "kuhn", file); !strings.Contains(o, "exploitability") {
		t.Fatal(o)
	}
	if o := run1("show", "kuhn", "-strategy", file); !strings.Contains(o, "1Q:b") {
		t.Fatal(o)
	}
	if o := run1("match", "kuhn", "-vs", file, "-hands", "2000"); !strings.Contains(o, "exact EV") {
		t.Fatal(o)
	}
	if o := run1("exploit", "leduc", "maniac"); !strings.Contains(o, "2.36") {
		t.Fatal(o)
	}
	if o := run1("equity", "AhAs", "KdKc"); !strings.Contains(o, "81.2") {
		t.Fatal(o)
	}
	if o := run1("help"); !strings.Contains(o, "pushfold") {
		t.Fatal(o)
	}
	// a Kuhn strategy fed to Leduc must be rejected, a corrupted file too
	var sb strings.Builder
	if err := runTo([]string{"exploit", "leduc", file}, &sb, nil); err == nil {
		t.Fatal("wrong-game strategy accepted")
	}
	os.WriteFile(file, []byte(`{"game":"kuhn","infosets":{"0J:":{"actions":["check","bet"],"probs":[0.9,0.9]}}}`), 0o644)
	if err := runTo([]string{"exploit", "kuhn", file}, &sb, nil); err == nil {
		t.Fatal("corrupt strategy accepted")
	}
}

func TestReportContainsEverything(t *testing.T) {
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	var sb strings.Builder
	if err := WriteReport(&sb, 200, []float64{8}, 200, nil); err != nil {
		t.Fatal(err)
	}
	h := sb.String()
	for _, want := range []string{"<!doctype html>", "Convergence", "Kuhn poker equilibrium", "first betting round", "Exploiting the weak", "Heads-up push/fold", "Small blind shoves", "Big blind calls", "<svg", "maniac", "prefers-color-scheme"} {
		if !strings.Contains(h, want) {
			t.Errorf("report missing %q", want)
		}
	}
	if strings.Count(h, "<b style=") != 2*169 {
		t.Errorf("expected two 169-cell grids, got %d cells", strings.Count(h, "<b style="))
	}
	if strings.Contains(h, "NaN") || strings.Contains(h, "Inf") {
		t.Error("report contains NaN/Inf")
	}
}

func TestCLIPlayEndToEnd(t *testing.T) {
	var sb strings.Builder
	err := runTo([]string{"play", "leduc", "-hands", "3", "-seat", "0", "-strategy", "station", "-seed", "2"}, &sb, strings.NewReader("bet\nbet\nbet\nbet\nbet\nbet\nbet\nbet\nbet\ncall\ncall\ncall\ncall\ncall\ncall\n"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(sb.String(), "Session over") {
		t.Fatal(sb.String())
	}
}
