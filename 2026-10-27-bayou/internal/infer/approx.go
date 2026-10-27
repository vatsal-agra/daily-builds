package infer

import (
	"fmt"
	"math"
	"math/rand"

	"bayou/internal/bn"
	"bayou/internal/factor"
)

// ApproxResult is the outcome of a sampling-based posterior estimate.
type ApproxResult struct {
	Posterior *factor.Factor // estimated P(query | evidence), normalised
	Samples   int            // samples drawn (after burn-in/thinning for Gibbs)
	ESS       float64        // effective sample size (importance weights / chains)
	LogPe     float64        // estimate of log P(evidence); -Inf if no sample had weight (LW only)
	Rhat      float64        // Gibbs: split-chain Gelman–Rubin statistic (max over cells), 1 = converged
}

// queryIndex maps a full assignment to the row-major index (query[0] slowest).
type queryIndex struct {
	query []int
	card  []int
	size  int
}

func newQueryIndex(net *bn.Network, q []int) queryIndex {
	qi := queryIndex{query: q, card: make([]int, len(q)), size: 1}
	for i, v := range q {
		qi.card[i] = net.Card(v)
		qi.size *= qi.card[i]
	}
	return qi
}

func (qi queryIndex) index(a []int) int {
	idx := 0
	for i, v := range qi.query {
		idx = idx*qi.card[i] + a[v]
	}
	return idx
}

// posterior converts counts in query order to a factor over sorted variables.
func (qi queryIndex) factor(counts []float64) *factor.Factor {
	f := factor.New(qi.query, qi.card, nil)
	for i := range f.Val {
		f.Val[i] = 0
	}
	pos := make([]int, len(qi.query)) // position of each query var within the sorted scope
	for i, v := range qi.query {
		for k, u := range f.Vars {
			if u == v {
				pos[i] = k
			}
		}
	}
	stride := make([]int, len(f.Vars))
	acc := 1
	for k := len(f.Vars) - 1; k >= 0; k-- {
		stride[k] = acc
		acc *= f.Card[k]
	}
	cnt := make([]int, len(qi.query))
	for idx := 0; idx < qi.size; idx++ {
		r := idx
		for i := len(qi.query) - 1; i >= 0; i-- {
			cnt[i] = r % qi.card[i]
			r /= qi.card[i]
		}
		t := 0
		for i := range qi.query {
			t += cnt[i] * stride[pos[i]]
		}
		f.Val[t] = counts[idx]
	}
	f.LogScale = 0
	n, ok := f.Normalized()
	if !ok {
		return f
	}
	return n
}

// LikelihoodWeighting estimates P(query | ev): evidence variables are clamped
// and each sample carries the weight Π P(e | parents). It is unbiased and
// needs no burn-in, but degrades when the evidence is unlikely (watch ESS).
func LikelihoodWeighting(net *bn.Network, query []int, ev bn.Evidence, n int, seed int64) (*ApproxResult, error) {
	if err := checkQuery(net, query, ev); err != nil {
		return nil, err
	}
	if n < 1 {
		return nil, fmt.Errorf("need at least 1 sample")
	}
	if len(query) == 0 {
		return nil, fmt.Errorf("need at least one query variable")
	}
	rng := rand.New(rand.NewSource(seed))
	order := net.TopoOrder()
	qi := newQueryIndex(net, query)
	counts := make([]float64, qi.size)
	var sw, sw2 float64
	a := make([]int, len(net.Vars))
	for i := 0; i < n; i++ {
		w := 1.0
		for _, v := range order {
			c := net.Card(v)
			r := net.RowIndex(v, a)
			if s, obs := ev[v]; obs {
				a[v] = s
				w *= net.Vars[v].CPT[r*c+s]
			} else {
				a[v] = bn.Categorical(rng, net.Vars[v].CPT[r*c:(r+1)*c])
			}
		}
		if w == 0 {
			continue
		}
		counts[qi.index(a)] += w
		sw += w
		sw2 += w * w
	}
	if sw == 0 {
		return nil, fmt.Errorf("%w (or too unlikely for %d samples: every sample had weight zero)", ErrImpossible, n)
	}
	return &ApproxResult{Posterior: qi.factor(counts), Samples: n, ESS: sw * sw / sw2, LogPe: math.Log(sw / float64(n))}, nil
}

// GibbsOptions configures Gibbs sampling.
type GibbsOptions struct {
	Samples int // recorded sweeps per chain
	Burn    int // discarded sweeps per chain (default Samples/5)
	Chains  int // independent chains (default 4)
	Seed    int64
}

// Gibbs estimates P(query | ev) by Markov-chain Monte Carlo: each hidden
// variable is resampled from its conditional given its Markov blanket. Chains
// start from independent likelihood-weighting draws that are consistent with
// the evidence; the split-chain R̂ diagnostic is returned so the caller can see
// whether they agree. Gibbs can fail to mix when the CPTs contain hard
// constraints (deterministic nodes) — R̂ then flags it.
func Gibbs(net *bn.Network, query []int, ev bn.Evidence, o GibbsOptions) (*ApproxResult, error) {
	if err := checkQuery(net, query, ev); err != nil {
		return nil, err
	}
	if len(query) == 0 {
		return nil, fmt.Errorf("need at least one query variable")
	}
	if o.Chains == 0 {
		o.Chains = 4
	}
	if o.Samples < 4 || o.Chains < 1 {
		return nil, fmt.Errorf("Gibbs needs at least 4 samples and 1 chain")
	}
	if o.Burn == 0 {
		o.Burn = o.Samples / 5
	}
	order := net.TopoOrder()
	children := net.Children()
	qi := newQueryIndex(net, query)
	var hidden []int
	for v := range net.Vars {
		if _, obs := ev[v]; !obs {
			hidden = append(hidden, v)
		}
	}
	counts := make([]float64, qi.size)
	series := make([][][]float64, o.Chains) // chain → cell → indicator series
	for ch := 0; ch < o.Chains; ch++ {
		rng := rand.New(rand.NewSource(o.Seed + int64(ch)*7919 + 1))
		a, err := initState(net, order, ev, rng)
		if err != nil {
			return nil, err
		}
		series[ch] = make([][]float64, qi.size)
		for c := range series[ch] {
			series[ch][c] = make([]float64, 0, o.Samples)
		}
		w := make([]float64, 0, 8)
		for sweep := 0; sweep < o.Burn+o.Samples; sweep++ {
			for _, v := range hidden {
				c := net.Card(v)
				w = w[:0]
				for s := 0; s < c; s++ {
					a[v] = s
					p := net.Vars[v].CPT[net.RowIndex(v, a)*c+s]
					for _, ch := range children[v] {
						if p == 0 {
							break
						}
						p *= net.Vars[ch].CPT[net.RowIndex(ch, a)*net.Card(ch)+a[ch]]
					}
					w = append(w, p)
				}
				a[v] = bn.Categorical(rng, w)
			}
			if sweep >= o.Burn {
				idx := qi.index(a)
				counts[idx]++
				for c := 0; c < qi.size; c++ {
					x := 0.0
					if c == idx {
						x = 1
					}
					series[ch][c] = append(series[ch][c], x)
				}
			}
		}
	}
	return &ApproxResult{Posterior: qi.factor(counts), Samples: o.Samples * o.Chains, ESS: batchMeansESS(series), Rhat: splitRhat(series), LogPe: math.NaN()}, nil
}

// initState draws likelihood-weighted states until one has positive joint probability.
func initState(net *bn.Network, order []int, ev bn.Evidence, rng *rand.Rand) ([]int, error) {
	a := make([]int, len(net.Vars))
	for try := 0; try < 100000; try++ {
		w := 1.0
		for _, v := range order {
			c := net.Card(v)
			r := net.RowIndex(v, a)
			if s, obs := ev[v]; obs {
				a[v] = s
				w *= net.Vars[v].CPT[r*c+s]
			} else {
				a[v] = bn.Categorical(rng, net.Vars[v].CPT[r*c:(r+1)*c])
			}
		}
		if w > 0 {
			return a, nil
		}
	}
	return nil, fmt.Errorf("%w: could not find a starting state consistent with the evidence", ErrImpossible)
}

// splitRhat computes the maximum over cells of the split-chain Gelman–Rubin
// statistic of the indicator series (each chain is split in two halves).
func splitRhat(series [][][]float64) float64 {
	worst := 1.0
	cells := len(series[0])
	for c := 0; c < cells; c++ {
		var halves [][]float64
		for _, ch := range series {
			s := ch[c]
			h := len(s) / 2
			halves = append(halves, s[:h], s[h:2*h])
		}
		n := float64(len(halves[0]))
		m := float64(len(halves))
		means := make([]float64, len(halves))
		var W float64
		for j, h := range halves {
			mu := 0.0
			for _, x := range h {
				mu += x
			}
			mu /= n
			means[j] = mu
			v := 0.0
			for _, x := range h {
				v += (x - mu) * (x - mu)
			}
			W += v / (n - 1)
		}
		W /= m
		gm := 0.0
		for _, mu := range means {
			gm += mu
		}
		gm /= m
		B := 0.0
		for _, mu := range means {
			B += (mu - gm) * (mu - gm)
		}
		B *= n / (m - 1)
		if W == 0 {
			if B > 0 {
				return math.Inf(1) // chains disagree and none moves: stuck
			}
			continue
		}
		r := math.Sqrt(((n-1)/n*W + B/n) / W)
		if r > worst {
			worst = r
		}
	}
	return worst
}

// batchMeansESS estimates the effective sample size of the worst-mixing
// posterior cell: with K batch means of the indicator series, the variance of
// the sample mean is ≈ var(batch means)/K, and ESS = var(series)/that. Chains
// are independent so their ESS values add.
func batchMeansESS(series [][][]float64) float64 {
	const K = 20
	worst := math.Inf(1)
	for c := range series[0] {
		total := 0.0
		for _, ch := range series {
			s := ch[c]
			n := len(s) / K * K
			if n < K*2 {
				return float64(len(s) * len(series))
			}
			bl := n / K
			mean := 0.0
			for _, x := range s[:n] {
				mean += x
			}
			mean /= float64(n)
			v := 0.0
			for _, x := range s[:n] {
				v += (x - mean) * (x - mean)
			}
			v /= float64(n - 1)
			bm := 0.0
			for b := 0; b < K; b++ {
				m := 0.0
				for _, x := range s[b*bl : (b+1)*bl] {
					m += x
				}
				m = m/float64(bl) - mean
				bm += m * m
			}
			bm /= float64(K - 1)
			if v == 0 || bm == 0 {
				total += float64(n)
				continue
			}
			total += math.Min(float64(n), v/(bm/K))
		}
		if total < worst {
			worst = total
		}
	}
	return worst
}
