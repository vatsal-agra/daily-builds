package infer

import (
	"math"
	"math/rand"
	"testing"

	"bayou/internal/bn"
	"bayou/internal/graph"
)

// Brute force mutual information I(T;X|e) from the enumerated joint P(T,X|e).
func bruteMI(t *testing.T, n *bn.Network, tv, x int, ev bn.Evidence) float64 {
	r, err := Enumerate(n, []int{tv, x}, ev)
	if err != nil {
		t.Fatal(err)
	}
	p := r.Posterior.Probs()
	ct, cx := n.Card(tv), n.Card(x)
	pt, px := make([]float64, ct), make([]float64, cx)
	idx := func(a, b int) int { // scope is sorted by variable id
		if tv < x {
			return a*cx + b
		}
		return b*ct + a
	}
	for a := 0; a < ct; a++ {
		for b := 0; b < cx; b++ {
			pt[a] += p[idx(a, b)]
			px[b] += p[idx(a, b)]
		}
	}
	mi := 0.0
	for a := 0; a < ct; a++ {
		for b := 0; b < cx; b++ {
			if q := p[idx(a, b)]; q > 0 {
				mi += q * math.Log(q/(pt[a]*px[b]))
			}
		}
	}
	return mi
}

func TestVOIEqualsMutualInformation(t *testing.T) {
	rng := rand.New(rand.NewSource(55))
	for trial := 0; trial < 60; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 4 + rng.Intn(5), MaxParents: 2, MaxCard: 3, ZeroProb: 0.1})
		ev := randomEvidence(rng, n, 0.2)
		var hidden []int
		for v := range n.Vars {
			if _, o := ev[v]; !o {
				hidden = append(hidden, v)
			}
		}
		if len(hidden) < 2 {
			continue
		}
		tv := hidden[rng.Intn(len(hidden))]
		res, err := ValueOfInformation(n, []int{tv}, ev)
		if err == ErrImpossible {
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		if len(res.Rows) != len(hidden)-1 {
			t.Fatalf("expected %d candidates, got %d", len(hidden)-1, len(res.Rows))
		}
		for i, row := range res.Rows {
			if row.Gain < 0 {
				t.Fatal("negative gain")
			}
			if i > 0 && row.Gain > res.Rows[i-1].Gain+1e-12 {
				t.Fatal("rows not sorted")
			}
			want := bruteMI(t, n, tv, row.Var, ev)
			if math.Abs(row.Gain-want) > 1e-9 {
				t.Fatalf("trial %d: gain of %s about %s = %.10f, brute-force I = %.10f", trial, n.Vars[row.Var].Name, n.Vars[tv].Name, row.Gain, want)
			}
			// probabilities of outcomes sum to 1
			s := 0.0
			for _, o := range row.Outcomes {
				s += o.Prob
			}
			if math.Abs(s-1) > 1e-9 {
				t.Fatalf("outcome probabilities sum to %g", s)
			}
			// d-separated candidates carry exactly no information
			if graph.DSeparated(n, []int{tv}, []int{row.Var}, keys(ev)) && row.Gain > 1e-9 {
				t.Fatalf("d-separated variable has gain %g", row.Gain)
			}
		}
	}
}

func keys(ev bn.Evidence) []int {
	var ks []int
	for k := range ev {
		ks = append(ks, k)
	}
	return ks
}

func TestVOIOnCarMakesSense(t *testing.T) {
	n := load(t, "car.bn")
	target := n.MustID("BatteryDead")
	ev, _ := n.ParseEvidence([]string{"Starts=no"})
	res, err := ValueOfInformation(n, []int{target}, ev)
	if err != nil {
		t.Fatal(err)
	}
	top := n.Vars[res.Rows[0].Var].Name
	if top != "EngineCranks" && top != "Lights" && top != "Radio" {
		t.Fatalf("most informative test for a dead battery should be a battery symptom, got %s", top)
	}
	// Given the car does not start, the fuel gauge is weakly relevant (it explains the failure away from the
	// battery) but far less informative than a direct battery symptom; with the engine known to crank it is d-separated.
	gain := map[string]float64{}
	for _, r := range res.Rows {
		gain[n.Vars[r.Var].Name] = r.Gain
	}
	if !(gain["FuelGauge"] > 0 && gain["FuelGauge"] < gain["EngineCranks"]/5) {
		t.Fatalf("gains %v", gain)
	}
	ev2, _ := n.ParseEvidence([]string{"Starts=no", "FuelEmpty=no", "FuelPumpBad=no"})
	res2, err := ValueOfInformation(n, []int{target}, ev2)
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range res2.Rows {
		if n.Vars[r.Var].Name == "FuelGauge" && r.Gain > 1e-12 {
			t.Fatalf("FuelGauge should be irrelevant once fuel is known: %g", r.Gain)
		}
	}
	// joint target
	if _, err := ValueOfInformation(n, []int{target, n.MustID("FuelEmpty")}, ev); err != nil {
		t.Fatal(err)
	}
	if _, err := ValueOfInformation(n, nil, ev); err == nil {
		t.Fatal("empty target accepted")
	}
	if _, err := ValueOfInformation(n, []int{target}, bn.Evidence{target: 0}); err == nil {
		t.Fatal("observed target accepted")
	}
}
