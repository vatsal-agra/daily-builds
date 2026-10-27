package bn

import (
	"math"
	"math/rand"
	"strings"
	"testing"
)

func TestCPTFactorAgreesWithLogJoint(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for trial := 0; trial < 100; trial++ {
		n := Random(rng, RandomOpts{Vars: 2 + rng.Intn(8), MaxParents: 3, MaxCard: 3, ZeroProb: 0.1})
		asg := make([]int, len(n.Vars))
		for v := range asg {
			asg[v] = rng.Intn(n.Card(v))
		}
		prod := 1.0
		m := map[int]int{}
		for v, s := range asg {
			m[v] = s
		}
		for v := range n.Vars {
			prod *= n.CPTFactor(v).At(m)
		}
		lj := n.LogJoint(asg)
		if prod == 0 {
			if !math.IsInf(lj, -1) {
				t.Fatalf("joint zero but LogJoint %g", lj)
			}
			continue
		}
		if math.Abs(math.Log(prod)-lj) > 1e-9 {
			t.Fatalf("product of CPT factors %g vs LogJoint %g", math.Log(prod), lj)
		}
	}
}

func TestTopoOrderAndCycles(t *testing.T) {
	n := New("x")
	for _, name := range []string{"c", "a", "b"} {
		n.AddVar(name, []string{"0", "1"})
	}
	n.SetParents(0, []int{1, 2}) // c ← a, b
	n.SetParents(2, []int{1})    // b ← a
	pos := map[int]int{}
	for i, v := range n.TopoOrder() {
		pos[v] = i
	}
	if !(pos[1] < pos[2] && pos[2] < pos[0]) {
		t.Fatalf("order %v violates parents-first", pos)
	}
	n.SetParents(1, []int{0}) // a ← c closes a cycle
	errs := n.Validate()
	if len(errs) == 0 || !strings.Contains(errs[0].Error(), "cycle") {
		t.Fatalf("cycle not detected: %v", errs)
	}
}

func TestValidateFindsAllRowProblems(t *testing.T) {
	n := New("x")
	n.AddVar("A", []string{"0", "1"})
	n.Vars[0].CPT = []float64{0.4, 0.4}
	n.AddVar("B", []string{"0", "1"})
	n.Vars[1].CPT = []float64{1.2, -0.2}
	if errs := n.Validate(); len(errs) < 3 {
		t.Fatalf("expected row-sum and range errors for both variables, got %v", errs)
	}
	n.SetParents(1, []int{1})
	if errs := n.Validate(); len(errs) == 0 || !strings.Contains(errs[0].Error(), "own parent") {
		t.Fatalf("self parent: %v", errs)
	}
}

func TestSamplingFrequencies(t *testing.T) {
	n := New("x")
	n.AddVar("A", []string{"0", "1", "2"})
	copy(n.Vars[0].CPT, []float64{0.2, 0.5, 0.3})
	rng := rand.New(rand.NewSource(2))
	cnt := make([]float64, 3)
	N := 100000
	for i := 0; i < N; i++ {
		cnt[n.Sample(rng)[0]]++
	}
	for s, p := range []float64{0.2, 0.5, 0.3} {
		if math.Abs(cnt[s]/float64(N)-p) > 0.005 {
			t.Fatalf("state %d sampled %.4f want %.2f", s, cnt[s]/float64(N), p)
		}
	}
	// zero-probability states must never be drawn
	n.Vars[0].CPT = []float64{0, 1, 0}
	for i := 0; i < 10000; i++ {
		if n.Sample(rng)[0] != 1 {
			t.Fatal("drew a zero-probability state")
		}
	}
}

func TestParseEvidenceAndVarList(t *testing.T) {
	n := New("x")
	n.AddVar("Rain", []string{"yes", "no"})
	n.AddVar("Sprinkler", []string{"on", "off"})
	ev, err := n.ParseEvidence([]string{"Rain=yes", " Sprinkler = off ", "Rain=yes"})
	if err != nil || ev[0] != 0 || ev[1] != 1 {
		t.Fatalf("%v %v", ev, err)
	}
	for _, bad := range [][]string{{"Rain=yes", "Rain=no"}, {"Rain"}, {"Rian=yes"}, {"Rain=maybe"}} {
		if _, err := n.ParseEvidence(bad); err == nil {
			t.Errorf("accepted %v", bad)
		}
	}
	if _, err := n.ParseEvidence([]string{"Rian=yes"}); err == nil || !strings.Contains(err.Error(), `did you mean "Rain"`) {
		t.Errorf("no suggestion: %v", err)
	}
	if ids, err := n.ParseVarList("Rain, Rain ,Sprinkler,"); err != nil || len(ids) != 2 {
		t.Errorf("%v %v", ids, err)
	}
}

func TestAddVarRejectsBadNames(t *testing.T) {
	n := New("x")
	if _, err := n.AddVar("", []string{"a", "b"}); err == nil {
		t.Error("empty name")
	}
	if _, err := n.AddVar("bad\nname", []string{"a", "b"}); err == nil {
		t.Error("newline in name")
	}
	if _, err := n.AddVar("v", []string{"a", "b\t"}); err == nil {
		t.Error("tab in state")
	}
	if _, err := n.AddVar("v", []string{"a", ""}); err == nil {
		t.Error("empty state")
	}
}

func TestRandomIsDeterministicAndValid(t *testing.T) {
	a := Random(rand.New(rand.NewSource(5)), RandomOpts{Vars: 15, MaxParents: 3, MaxCard: 4, ZeroProb: 0.3, Sharp: 0.3})
	b := Random(rand.New(rand.NewSource(5)), RandomOpts{Vars: 15, MaxParents: 3, MaxCard: 4, ZeroProb: 0.3, Sharp: 0.3})
	if errs := a.Validate(); len(errs) > 0 {
		t.Fatal(errs)
	}
	for v := range a.Vars {
		for i := range a.Vars[v].CPT {
			if a.Vars[v].CPT[i] != b.Vars[v].CPT[i] {
				t.Fatal("Random not deterministic")
			}
		}
	}
}
