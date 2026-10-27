package infer

import (
	"math"
	"math/rand"
	"testing"

	"bayou/internal/bn"
	"bayou/internal/graph"
)

// Numeric check of d-separation soundness and (generic) completeness:
// separated ⇒ exactly independent; connected ⇒ dependent for generic parameters.
func TestDSeparationAgreesWithNumericIndependence(t *testing.T) {
	rng := rand.New(rand.NewSource(13))
	sep, conn := 0, 0
	for trial := 0; trial < 120; trial++ {
		n := bn.Random(rng, bn.RandomOpts{Vars: 4 + rng.Intn(5), MaxParents: 3, MaxCard: 3, EdgeProb: 0.5})
		a, b := rng.Intn(len(n.Vars)), rng.Intn(len(n.Vars))
		if a == b {
			continue
		}
		var z []int
		for v := range n.Vars {
			if v != a && v != b && rng.Float64() < 0.3 {
				z = append(z, v)
			}
		}
		// maximum over z-assignments of |P(a,b|z) - P(a|z)P(b|z)|
		dev := 0.0
		zc := make([]int, len(z))
		for {
			ev := bn.Evidence{}
			for i, v := range z {
				ev[v] = zc[i]
			}
			ab, err := Enumerate(n, []int{a, b}, ev)
			if err == nil {
				ma, _ := Enumerate(n, []int{a}, ev)
				mb, _ := Enumerate(n, []int{b}, ev)
				pab, pa, pb := ab.Posterior.Probs(), ma.Posterior.Probs(), mb.Posterior.Probs()
				for i := range pa {
					for j := range pb {
						// posterior joint is over sorted vars; locate indices
						var p float64
						if a < b {
							p = pab[i*len(pb)+j]
						} else {
							p = pab[j*len(pa)+i]
						}
						dev = math.Max(dev, math.Abs(p-pa[i]*pb[j]))
					}
				}
			}
			k := len(zc) - 1
			for ; k >= 0; k-- {
				if zc[k]++; zc[k] < n.Card(z[k]) {
					break
				}
				zc[k] = 0
			}
			if k < 0 {
				break
			}
		}
		if graph.DSeparated(n, []int{a}, []int{b}, z) {
			sep++
			if dev > 1e-9 {
				t.Fatalf("trial %d: d-separated but dependent (dev %g)", trial, dev)
			}
		} else {
			conn++
			if dev < 1e-7 {
				t.Fatalf("trial %d: d-connected but numerically independent (dev %g)", trial, dev)
			}
		}
	}
	if sep < 15 || conn < 15 {
		t.Fatalf("weak coverage: %d separated, %d connected", sep, conn)
	}
}
