package bn

import (
	"fmt"
	"math/rand"
)

// RandomOpts controls Random.
type RandomOpts struct {
	Vars       int     // number of variables
	MaxParents int     // per variable
	MaxCard    int     // states per variable in [2, MaxCard]
	EdgeProb   float64 // chance each allowed parent slot is filled (0 → 0.5)
	ZeroProb   float64 // chance a CPT entry is forced to zero (deterministic-ish nodes)
	Sharp      float64 // Dirichlet concentration; <1 gives peaked CPTs (0 → 1)
}

// Random builds a random valid network deterministically from the seed. The
// variable order is a topological order (parents have smaller ids), which
// keeps the generator simple while covering every DAG shape.
func Random(rng *rand.Rand, o RandomOpts) *Network {
	if o.MaxCard < 2 {
		o.MaxCard = 2
	}
	if o.EdgeProb == 0 {
		o.EdgeProb = 0.5
	}
	if o.Sharp == 0 {
		o.Sharp = 1
	}
	n := New(fmt.Sprintf("random-%d", o.Vars))
	for i := 0; i < o.Vars; i++ {
		card := 2 + rng.Intn(o.MaxCard-1)
		st := make([]string, card)
		for s := range st {
			st[s] = fmt.Sprintf("s%d", s)
		}
		n.AddVar(fmt.Sprintf("X%d", i), st)
	}
	for v := 0; v < o.Vars; v++ {
		var ps []int
		cand := rng.Perm(v)
		for _, p := range cand {
			if len(ps) < o.MaxParents && rng.Float64() < o.EdgeProb {
				ps = append(ps, p)
			}
		}
		// keep parents sorted descending-insensitive but deterministic
		sortInts(ps)
		n.SetParents(v, ps)
		c := n.Card(v)
		for r := 0; r < n.ParentConfigs(v); r++ {
			row := n.Vars[v].CPT[r*c : (r+1)*c]
			sum := 0.0
			for s := range row {
				row[s] = gammaSample(rng, o.Sharp)
				if rng.Float64() < o.ZeroProb {
					row[s] = 0
				}
				sum += row[s]
			}
			if sum == 0 {
				row[rng.Intn(c)] = 1
				sum = 1
			}
			for s := range row {
				row[s] /= sum
			}
		}
	}
	return n
}

func sortInts(a []int) {
	for i := 1; i < len(a); i++ {
		for j := i; j > 0 && a[j] < a[j-1]; j-- {
			a[j], a[j-1] = a[j-1], a[j]
		}
	}
}

// gammaSample draws Gamma(shape,1) (Marsaglia–Tsang, with the shape<1 boost).
func gammaSample(rng *rand.Rand, shape float64) float64 {
	if shape < 1 {
		return gammaSample(rng, shape+1) * pow(rng.Float64(), 1/shape)
	}
	d := shape - 1.0/3
	c := 1 / sqrt(9*d)
	for {
		x := rng.NormFloat64()
		v := 1 + c*x
		if v <= 0 {
			continue
		}
		v = v * v * v
		u := rng.Float64()
		if u < 1-0.0331*x*x*x*x || ln(u) < 0.5*x*x+d*(1-v+ln(v)) {
			return d * v
		}
	}
}
