package infer

import (
	"errors"
	"math"
	"math/rand"
	"testing"
	"time"

	"bayou/internal/bn"
)

// chain builds X0→X1→…→X(n-1), each binary, with the given persistence.
func chain(n int, stay float64) *bn.Network {
	net := bn.New("chain")
	for i := 0; i < n; i++ {
		net.AddVar("X"+itoa(i), []string{"0", "1"})
		if i > 0 {
			net.SetParents(i, []int{i - 1})
			copy(net.Vars[i].CPT, []float64{stay, 1 - stay, 1 - stay, stay})
		} else {
			copy(net.Vars[0].CPT, []float64{0.5, 0.5})
		}
	}
	return net
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	s := ""
	for ; i > 0; i /= 10 {
		s = string(rune('0'+i%10)) + s
	}
	return s
}

// P(X0=0, X1=1, X2=0, ...) alternating on a sticky chain is ~ 0.5·0.01^(n-1):
// far below float64's range for n=400. Log-space bookkeeping must survive it.
func TestLongChainEvidenceDoesNotUnderflow(t *testing.T) {
	n := 400
	net := chain(n, 0.99)
	ev := bn.Evidence{}
	for i := 0; i < n; i++ {
		ev[i] = i % 2
	}
	want := math.Log(0.5) + float64(n-1)*math.Log(0.01)
	start := time.Now()
	lpe, err := LogEvidence(net, ev)
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(lpe-want) > 1e-6 {
		t.Fatalf("VE log P(e) = %g, want %g", lpe, want)
	}
	jt, err := NewJT(net)
	if err != nil {
		t.Fatal(err)
	}
	cal, err := jt.Calibrate(ev)
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(cal.LogEvidence-want) > 1e-6 {
		t.Fatalf("JT log P(e) = %g, want %g", cal.LogEvidence, want)
	}
	if time.Since(start) > 10*time.Second {
		t.Fatal("too slow")
	}
}

func TestLongChainPosteriorMatchesClosedForm(t *testing.T) {
	// With X0=0 observed, P(Xk=0) = ½(1+(2s-1)^k) on a symmetric chain.
	n, stay := 1500, 0.9
	net := chain(n, stay)
	jt, err := NewJT(net)
	if err != nil {
		t.Fatal(err)
	}
	cal, err := jt.Calibrate(bn.Evidence{0: 0})
	if err != nil {
		t.Fatal(err)
	}
	for _, k := range []int{1, 2, 5, 20, 100, 1499} {
		want := 0.5 * (1 + math.Pow(2*stay-1, float64(k)))
		if got := cal.Marginal(k).Probs()[0]; math.Abs(got-want) > 1e-9 {
			t.Fatalf("P(X%d=0) = %.12f want %.12f", k, got, want)
		}
	}
	r, err := VE(net, []int{n - 1}, bn.Evidence{0: 0})
	if err != nil {
		t.Fatal(err)
	}
	want := 0.5 * (1 + math.Pow(2*stay-1, float64(n-1)))
	if got := r.Posterior.Probs()[0]; math.Abs(got-want) > 1e-9 {
		t.Fatalf("VE: %g want %g", got, want)
	}
}

func TestIntractableNetworksFailGracefully(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	net := bn.Random(rng, bn.RandomOpts{Vars: 150, MaxParents: 4, MaxCard: 3, EdgeProb: 0.9})
	if _, err := NewJT(net); err == nil {
		t.Fatal("NewJT accepted a network with enormous treewidth")
	}
	_, err := VE(net, []int{149}, bn.Evidence{0: 0})
	if !errors.Is(err, ErrTooLarge) {
		t.Fatalf("VE should return ErrTooLarge, got %v", err)
	}
	_, err = MAP(net, []int{149, 148}, bn.Evidence{0: 0})
	if !errors.Is(err, ErrTooLarge) {
		t.Fatalf("MAP should return ErrTooLarge, got %v", err)
	}
	if _, err := Enumerate(net, []int{1}, nil); err == nil {
		t.Fatal("Enumerate accepted a huge joint")
	}
}

func TestQueryValidation(t *testing.T) {
	net := chain(3, 0.9)
	if _, err := VE(net, []int{1, 1}, nil); err == nil {
		t.Error("duplicate query var accepted")
	}
	if _, err := VE(net, []int{1}, bn.Evidence{1: 0}); err == nil {
		t.Error("query var that is also evidence accepted")
	}
	if _, err := VE(net, []int{9}, nil); err == nil {
		t.Error("out-of-range query accepted")
	}
	if _, err := VE(net, []int{1}, bn.Evidence{0: 5}); err == nil {
		t.Error("out-of-range evidence state accepted")
	}
	jt, _ := NewJT(net)
	if _, err := jt.Calibrate(bn.Evidence{7: 0}); err == nil {
		t.Error("JT accepted unknown evidence variable")
	}
	// impossible evidence → ErrImpossible from all three engines
	net.Vars[1].CPT = []float64{1, 0, 1, 0} // X1 is always 0
	for name, f := range map[string]func() error{
		"ve":  func() error { _, e := VE(net, []int{2}, bn.Evidence{1: 1}); return e },
		"jt":  func() error { _, e := jt.Calibrate(bn.Evidence{1: 1}); return e },
		"map": func() error { _, e := MAP(net, []int{2}, bn.Evidence{1: 1}); return e },
		"enu": func() error { _, e := Enumerate(net, []int{2}, bn.Evidence{1: 1}); return e },
	} {
		if name == "jt" {
			jt.Reparam()
		}
		if err := f(); !errors.Is(err, ErrImpossible) {
			t.Errorf("%s: want ErrImpossible, got %v", name, err)
		}
	}
}

// Barren nodes (descendants that are neither queried nor observed) sum to one
// and must be pruned: querying the root of a 2000-variable chain touches nothing else.
func TestBarrenNodePruning(t *testing.T) {
	net := chain(2000, 0.9)
	r, err := VE(net, []int{0}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if r.Eliminated != 0 {
		t.Fatalf("eliminated %d variables to answer a prior root query", r.Eliminated)
	}
	r, err = VE(net, []int{10}, bn.Evidence{12: 1})
	if err != nil {
		t.Fatal(err)
	}
	if r.Eliminated != 11 { // X0..X12 minus the query X10 and evidence X12
		t.Fatalf("eliminated %d, want 11", r.Eliminated)
	}
}

func TestMAPTieBreaksToLowestState(t *testing.T) {
	net := bn.New("tie")
	net.AddVar("A", []string{"x", "y", "z"})
	copy(net.Vars[0].CPT, []float64{0.25, 0.25, 0.5})
	net.AddVar("B", []string{"p", "q"})
	net.SetParents(1, []int{0})
	copy(net.Vars[1].CPT, []float64{0.5, 0.5, 0.5, 0.5, 0.5, 0.5})
	r, err := MAP(net, []int{1}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if r.Assign[1] != 0 {
		t.Fatalf("tie should resolve to the first state, got %d", r.Assign[1])
	}
	r, _ = MAP(net, []int{0}, nil)
	if r.Assign[0] != 2 {
		t.Fatalf("A's mode is z, got %d", r.Assign[0])
	}
}
