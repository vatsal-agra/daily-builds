// Package learn estimates Bayesian-network parameters (maximum likelihood with
// Dirichlet smoothing, and expectation-maximisation for missing or latent
// data) and learns structure by score-based hill climbing.
package learn

import (
	"fmt"
	"math"
	"math/rand"
	"strings"

	"bayou/internal/bn"
	"bayou/internal/factor"
	"bayou/internal/infer"
	"bayou/internal/parse"
)

// Simulate draws n rows from the network. Variables in hidden are dropped from
// the dataset (latent); every remaining cell is blanked independently with
// probability missingRate (missing completely at random).
func Simulate(net *bn.Network, n int, rng *rand.Rand, missingRate float64, hidden []int) *parse.Dataset {
	hide := map[int]bool{}
	for _, h := range hidden {
		hide[h] = true
	}
	ds := &parse.Dataset{}
	for v := range net.Vars {
		if !hide[v] {
			ds.Cols = append(ds.Cols, v)
		}
	}
	order := net.TopoOrder()
	for i := 0; i < n; i++ {
		a := net.SampleOrdered(rng, order)
		row := make([]int, len(ds.Cols))
		for k, v := range ds.Cols {
			row[k] = a[v]
			if missingRate > 0 && rng.Float64() < missingRate {
				row[k] = parse.Missing
			}
		}
		ds.Rows = append(ds.Rows, row)
	}
	return ds
}

// Fit returns a copy of net (same structure) whose CPTs are the smoothed
// maximum-likelihood estimates from ds:
//
//	P(x | pa) = (count(x,pa) + alpha) / (count(pa) + alpha*|x|)
//
// Each family is counted over the rows in which the whole family is observed
// (available-case analysis). A family never observed anywhere is an error:
// use EM for latent variables. Parent configurations with no data fall back to
// uniform (alpha > 0) or are reported as an error (alpha == 0).
func Fit(net *bn.Network, ds *parse.Dataset, alpha float64) (*bn.Network, error) {
	if alpha < 0 || math.IsNaN(alpha) {
		return nil, fmt.Errorf("smoothing alpha must be >= 0, got %g", alpha)
	}
	col := map[int]int{}
	for i, v := range ds.Cols {
		col[v] = i
	}
	out := net.Clone()
	for v := range net.Vars {
		fam := append([]int{v}, net.Vars[v].Parents...)
		for _, u := range fam {
			if _, ok := col[u]; !ok {
				return nil, fmt.Errorf("variable %s (needed by the family of %s) is latent; use EM instead of plain maximum likelihood", net.Vars[u].Name, net.Vars[v].Name)
			}
		}
		c := net.Card(v)
		counts := make([]float64, net.ParentConfigs(v)*c)
		used := 0
		for _, row := range ds.Rows {
			ok := row[col[v]] != parse.Missing
			assign := make([]int, len(net.Vars))
			for _, p := range net.Vars[v].Parents {
				if row[col[p]] == parse.Missing {
					ok = false
				}
				assign[p] = row[col[p]]
			}
			if !ok {
				continue
			}
			used++
			counts[net.RowIndex(v, assign)*c+row[col[v]]]++
		}
		if used == 0 && len(ds.Rows) > 0 {
			return nil, fmt.Errorf("no row has the whole family of %s observed", net.Vars[v].Name)
		}
		if err := normalizeCounts(out, v, counts, alpha, false); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// normalizeCounts writes (counts+alpha)/(total+alpha*c) into v's CPT rows. A row
// with no mass keeps its previous values when keepEmpty is set, else becomes
// uniform if alpha>0 and an error if alpha==0.
func normalizeCounts(net *bn.Network, v int, counts []float64, alpha float64, keepEmpty bool) error {
	c := net.Card(v)
	cpt := net.Vars[v].CPT
	for r := 0; r < net.ParentConfigs(v); r++ {
		tot := 0.0
		for s := 0; s < c; s++ {
			tot += counts[r*c+s]
		}
		switch {
		case tot+alpha*float64(c) <= 0:
			if keepEmpty {
				continue
			}
			return fmt.Errorf("variable %s: parent configuration %s never occurs in the data; use a smoothing alpha > 0", net.Vars[v].Name, net.RowLabel(v, r))
		default:
			for s := 0; s < c; s++ {
				cpt[r*c+s] = (counts[r*c+s] + alpha) / (tot + alpha*float64(c))
			}
		}
	}
	return nil
}

// LogLikelihood returns sum over rows of log P(observed cells of the row).
func LogLikelihood(net *bn.Network, ds *parse.Dataset) (float64, error) {
	jt, err := infer.NewJT(net)
	if err != nil {
		return 0, err
	}
	return logLik(net, jt, ds, nil)
}

type group struct {
	ev    bn.Evidence
	count int
}

// groupRows collapses identical evidence patterns.
func groupRows(net *bn.Network, ds *parse.Dataset) []group {
	idx := map[string]int{}
	var gs []group
	var sb strings.Builder
	for _, row := range ds.Rows {
		sb.Reset()
		for _, s := range row {
			fmt.Fprintf(&sb, "%d,", s)
		}
		k := sb.String()
		if i, ok := idx[k]; ok {
			gs[i].count++
			continue
		}
		ev := bn.Evidence{}
		for i, s := range row {
			if s != parse.Missing {
				ev[ds.Cols[i]] = s
			}
		}
		idx[k] = len(gs)
		gs = append(gs, group{ev, 1})
	}
	return gs
}

func logLik(net *bn.Network, jt *infer.JT, ds *parse.Dataset, acc map[int][]float64) (float64, error) {
	total := 0.0
	for gi, g := range groupRows(net, ds) {
		cal, err := jt.Calibrate(g.ev)
		if err != nil {
			if err == infer.ErrImpossible {
				return math.Inf(-1), fmt.Errorf("data pattern %d (%s) has probability zero under the model", gi, net.EvidenceString(g.ev))
			}
			return 0, err
		}
		total += float64(g.count) * cal.LogEvidence
		if acc != nil {
			for v := range net.Vars {
				addFamily(net, v, cal.Family(v), float64(g.count), acc[v])
			}
		}
	}
	return total, nil
}

// addFamily adds w*P(v,pa|e) into a CPT-layout count vector.
func addFamily(net *bn.Network, v int, fam *factor.Factor, w float64, into []float64) {
	probs := fam.Probs()
	c := net.Card(v)
	cnt := make([]int, len(fam.Vars))
	assign := make([]int, len(net.Vars))
	for i := range probs {
		for k, u := range fam.Vars {
			assign[u] = cnt[k]
		}
		into[net.RowIndex(v, assign)*c+assign[v]] += w * probs[i]
		for k := len(cnt) - 1; k >= 0; k-- {
			if cnt[k]++; cnt[k] < fam.Card[k] {
				break
			}
			cnt[k] = 0
		}
	}
}

// EMOptions configures EM.
type EMOptions struct {
	MaxIter  int     // default 200
	Tol      float64 // stop when log-likelihood gain < Tol (default 1e-7)
	Alpha    float64 // Dirichlet pseudo-count in the M-step (default 0; use >0 to avoid zeros)
	Restarts int     // extra random restarts (default 0)
	Seed     int64
	Random   bool // start the first run from random CPTs instead of net's values
}

// EMResult describes an EM run.
type EMResult struct {
	Net       *bn.Network
	LogLik    []float64 // after each iteration (index 0 = starting parameters)
	Converged bool
	Restart   int // which restart produced the winner
}

// EM fits the CPTs of net to ds, which may have missing cells and may omit
// variables entirely (latent). The expected sufficient statistics in the E-step
// come from junction-tree calibration under each row's observed evidence.
// Log-likelihood never decreases (up to rounding) and the best of all restarts
// is returned.
func EM(net *bn.Network, ds *parse.Dataset, o EMOptions) (*EMResult, error) {
	if o.MaxIter == 0 {
		o.MaxIter = 200
	}
	if o.Tol == 0 {
		o.Tol = 1e-7
	}
	if o.Alpha < 0 {
		return nil, fmt.Errorf("alpha must be >= 0")
	}
	if len(ds.Rows) == 0 {
		return nil, fmt.Errorf("the dataset has no rows")
	}
	rng := rand.New(rand.NewSource(o.Seed))
	var best *EMResult
	for r := 0; r <= o.Restarts; r++ {
		start := net.Clone()
		if o.Random || r > 0 {
			randomizeCPTs(start, rng)
		}
		res, err := emRun(start, ds, o)
		if err != nil {
			return nil, err
		}
		res.Restart = r
		if best == nil || res.LogLik[len(res.LogLik)-1] > best.LogLik[len(best.LogLik)-1] {
			best = res
		}
	}
	return best, nil
}

func randomizeCPTs(net *bn.Network, rng *rand.Rand) {
	for v := range net.Vars {
		c := net.Card(v)
		for r := 0; r < net.ParentConfigs(v); r++ {
			row := net.Vars[v].CPT[r*c : (r+1)*c]
			sum := 0.0
			for s := range row {
				row[s] = 0.2 + rng.Float64()
				sum += row[s]
			}
			for s := range row {
				row[s] /= sum
			}
		}
	}
}

func emRun(net *bn.Network, ds *parse.Dataset, o EMOptions) (*EMResult, error) {
	jt, err := infer.NewJT(net)
	if err != nil {
		return nil, err
	}
	res := &EMResult{Net: net}
	prev := math.Inf(-1)
	for it := 0; it <= o.MaxIter; it++ {
		acc := map[int][]float64{}
		for v := range net.Vars {
			acc[v] = make([]float64, len(net.Vars[v].CPT))
		}
		ll, err := logLik(net, jt, ds, acc)
		if err != nil {
			return nil, err
		}
		res.LogLik = append(res.LogLik, ll)
		if it > 0 && ll-prev < o.Tol {
			res.Converged = true
			break
		}
		prev = ll
		if it == o.MaxIter {
			break
		}
		for v := range net.Vars {
			if err := normalizeCounts(net, v, acc[v], o.Alpha, true); err != nil {
				return nil, err
			}
		}
		jt.Reparam()
	}
	return res, nil
}

// KLJoint returns KL(truth || learned) of the joint distributions, computed
// exactly through the chain rule: sum over variables of the expected
// row-wise KL under the truth's family marginals. Both networks must have
// identical structure and state spaces.
func KLJoint(truth, learned *bn.Network) (float64, error) {
	if len(truth.Vars) != len(learned.Vars) {
		return 0, fmt.Errorf("networks have different numbers of variables")
	}
	for v := range truth.Vars {
		a, b := truth.Vars[v], learned.Vars[v]
		if a.Name != b.Name || len(a.States) != len(b.States) || len(a.Parents) != len(b.Parents) {
			return 0, fmt.Errorf("variable %s differs in structure between the two networks", a.Name)
		}
		for i := range a.Parents {
			if a.Parents[i] != b.Parents[i] {
				return 0, fmt.Errorf("variable %s has different parents", a.Name)
			}
		}
	}
	jt, err := infer.NewJT(truth)
	if err != nil {
		return 0, err
	}
	cal, err := jt.Calibrate(nil)
	if err != nil {
		return 0, err
	}
	kl := 0.0
	for v := range truth.Vars {
		fam := make([]float64, len(truth.Vars[v].CPT))
		addFamily(truth, v, cal.Family(v), 1, fam)
		for i, w := range fam {
			if w == 0 {
				continue
			}
			p := truth.Vars[v].CPT[i]
			q := learned.Vars[v].CPT[i]
			if p == 0 {
				continue
			}
			if q == 0 {
				return math.Inf(1), nil
			}
			// w = P(pa)·p(x|pa); contribution w·log(p/q)
			kl += w * math.Log(p/q)
		}
	}
	return kl, nil
}

// MaxCPTDiff is the largest absolute difference between two networks' CPT entries.
func MaxCPTDiff(a, b *bn.Network) float64 {
	d := 0.0
	for v := range a.Vars {
		for i := range a.Vars[v].CPT {
			d = math.Max(d, math.Abs(a.Vars[v].CPT[i]-b.Vars[v].CPT[i]))
		}
	}
	return d
}
