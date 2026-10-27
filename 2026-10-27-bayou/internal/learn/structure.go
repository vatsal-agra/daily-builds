package learn

import (
	"fmt"
	"math"
	"math/rand"
	"sort"

	"bayou/internal/bn"
	"bayou/internal/parse"
)

// Score selects the structure-scoring function.
type Score int

const (
	BIC  Score = iota // log-likelihood − ½·log N·(free parameters)
	K2                // Cooper–Herskovits marginal likelihood, Dirichlet(1) prior on each CPT entry
	BDeu              // Heckerman et al. likelihood-equivalent Dirichlet score (equivalent sample size ESS)
)

func (s Score) String() string { return [...]string{"bic", "k2", "bdeu"}[s] }

// ParseScore reads "bic", "k2" or "bdeu".
func ParseScore(s string) (Score, error) {
	switch s {
	case "bic":
		return BIC, nil
	case "k2":
		return K2, nil
	case "bdeu":
		return BDeu, nil
	}
	return 0, fmt.Errorf("unknown score %q (want bic, k2 or bdeu)", s)
}

// StructureOptions configures HillClimb.
type StructureOptions struct {
	Score      Score
	MaxParents int     // per variable (default 3)
	ESS        float64 // BDeu equivalent sample size (default 1)
	Tabu       int     // length of the tabu list of recently reversed moves (default 10)
	MaxSteps   int     // safety cap (default 10 000)
	Patience   int     // stop after this many steps without a new best graph (default 25)
	Restarts   int     // random restarts after the first climb (perturb then re-climb)
	Seed       int64
}

// Move is one search step.
type Move struct {
	Kind     string // "add", "delete" or "reverse"
	From, To int    // the edge From → To (for reverse: the edge before reversal)
	Gain     float64
}

// StructureResult is the learned graph.
type StructureResult struct {
	Parents [][]int // parent lists per variable (sorted)
	Score   float64
	Steps   []Move
	Rows    int // rows used (rows with a missing cell are dropped)
	Dropped int
	// Restarted is true when the winner came from a perturbed restart, in which case
	// Steps describes that run only (it does not start from the empty graph).
	Restarted bool
}

type scorer struct {
	net    *bn.Network
	cols   [][]int // cols[v][row]
	n      int
	opt    StructureOptions
	cache  map[string]float64
	card   []int
	logN   float64
	nrows  int
	lgamma func(float64) float64
}

func lgamma(x float64) float64 { v, _ := math.Lgamma(x); return v }

func newScorer(net *bn.Network, ds *parse.Dataset, opt StructureOptions) (*scorer, error) {
	col := map[int]int{}
	for i, v := range ds.Cols {
		col[v] = i
	}
	for v := range net.Vars {
		if _, ok := col[v]; !ok {
			return nil, fmt.Errorf("structure learning needs every variable as a data column; %s is missing", net.Vars[v].Name)
		}
	}
	s := &scorer{net: net, opt: opt, cache: map[string]float64{}, card: make([]int, len(net.Vars)), lgamma: lgamma}
	s.cols = make([][]int, len(net.Vars))
	for _, row := range ds.Rows {
		complete := true
		for _, x := range row {
			if x == parse.Missing {
				complete = false
				break
			}
		}
		if !complete {
			continue
		}
		for v := range net.Vars {
			s.cols[v] = append(s.cols[v], row[col[v]])
		}
		s.n++
	}
	for v := range s.card {
		s.card[v] = net.Card(v)
	}
	if s.n < 2 {
		return nil, fmt.Errorf("need at least 2 complete rows to learn structure (have %d of %d)", s.n, len(ds.Rows))
	}
	s.logN = math.Log(float64(s.n))
	s.nrows = len(ds.Rows)
	return s, nil
}

// family returns the (decomposable) score contribution of v with the given parents.
func (s *scorer) family(v int, parents []int) float64 {
	key := fmt.Sprint(v, parents)
	if x, ok := s.cache[key]; ok {
		return x
	}
	c := s.card[v]
	q := 1
	for _, p := range parents {
		q *= s.card[p]
	}
	counts := make([]float64, q*c)
	for r := 0; r < s.n; r++ {
		cfg := 0
		for _, p := range parents {
			cfg = cfg*s.card[p] + s.cols[p][r]
		}
		counts[cfg*c+s.cols[v][r]]++
	}
	score := 0.0
	switch s.opt.Score {
	case BIC:
		for j := 0; j < q; j++ {
			tot := 0.0
			for k := 0; k < c; k++ {
				tot += counts[j*c+k]
			}
			for k := 0; k < c; k++ {
				if n := counts[j*c+k]; n > 0 {
					score += n * math.Log(n/tot)
				}
			}
		}
		score -= 0.5 * s.logN * float64(q*(c-1))
	case K2:
		for j := 0; j < q; j++ {
			tot := 0.0
			for k := 0; k < c; k++ {
				tot += counts[j*c+k]
				score += s.lgamma(counts[j*c+k] + 1)
			}
			score += s.lgamma(float64(c)) - s.lgamma(tot+float64(c))
		}
	case BDeu:
		ess := s.opt.ESS
		aj := ess / float64(q)
		ajk := ess / float64(q*c)
		for j := 0; j < q; j++ {
			tot := 0.0
			for k := 0; k < c; k++ {
				tot += counts[j*c+k]
				score += s.lgamma(counts[j*c+k]+ajk) - s.lgamma(ajk)
			}
			score += s.lgamma(aj) - s.lgamma(aj+tot)
		}
	}
	s.cache[key] = score
	return score
}

// ScoreStructure scores a complete parent structure on the data.
func ScoreStructure(net *bn.Network, ds *parse.Dataset, parents [][]int, opt StructureOptions) (float64, error) {
	if opt.ESS == 0 {
		opt.ESS = 1
	}
	s, err := newScorer(net, ds, opt)
	if err != nil {
		return 0, err
	}
	total := 0.0
	for v := range net.Vars {
		ps := append([]int(nil), parents[v]...)
		sort.Ints(ps)
		total += s.family(v, ps)
	}
	return total, nil
}

// HillClimb learns a DAG by tabu search over single-edge additions, deletions
// and reversals, scoring with a decomposable score (so each move only re-scores
// one or two families). Plain greedy ascent stalls in local optima whose score
// is below the true graph's (colliders such as sprinkler/wet-grass are the
// classic trap), so the search keeps moving through non-improving steps under a
// tabu list and returns the best graph seen; optional random restarts perturb
// the best graph and search again.
// Variables keep the states and names of `net`; only the structure is learned.
func HillClimb(net *bn.Network, ds *parse.Dataset, opt StructureOptions) (*StructureResult, error) {
	if opt.MaxParents == 0 {
		opt.MaxParents = 3
	}
	if opt.ESS == 0 {
		opt.ESS = 1
	}
	if opt.Tabu == 0 {
		opt.Tabu = 10
	}
	if opt.MaxSteps == 0 {
		opt.MaxSteps = 10000
	}
	if opt.Patience == 0 {
		opt.Patience = 25
	}
	if opt.MaxParents < 0 || opt.ESS < 0 {
		return nil, fmt.Errorf("max parents and ESS must be non-negative")
	}
	s, err := newScorer(net, ds, opt)
	if err != nil {
		return nil, err
	}
	nv := len(net.Vars)
	parents := make([][]int, nv)
	cur := make([]float64, nv)
	for v := range cur {
		cur[v] = s.family(v, nil)
	}
	best := &StructureResult{Rows: s.n, Dropped: s.nrows - s.n}
	// climb runs tabu search from (parents, cur): each step applies the best
	// non-tabu move even when it lowers the score (so the search can leave a
	// local optimum), remembers the best graph seen, and stops after Patience
	// consecutive steps without a new best. It returns that best graph, its
	// score and the move sequence leading to it.
	climb := func(parents [][]int, cur []float64) ([][]int, float64, []Move) {
		total := 0.0
		for _, x := range cur {
			total += x
		}
		bestTotal, bestParents, bestLen := total, cloneParents(parents), 0
		var steps []Move
		var tabu [][3]int
		isTabu := func(kind, a, b int) bool {
			for _, t := range tabu {
				if t == [3]int{kind, a, b} {
					return true
				}
			}
			return false
		}
		stale := 0
		for step := 0; step < opt.MaxSteps && stale < opt.Patience; step++ {
			bestGain := math.Inf(-1)
			var bm Move
			var bp [2][]int
			found := false
			consider := func(kind string, tabuKind, from, to int, g float64, np, nf []int) {
				if isTabu(tabuKind, from, to) && !(total+g > bestTotal+1e-9) { // aspiration: allow if it beats the best
					return
				}
				if g > bestGain {
					bestGain, bm, bp, found = g, Move{kind, from, to, g}, [2][]int{np, nf}, true
				}
			}
			for to := 0; to < nv; to++ {
				for from := 0; from < nv; from++ {
					if from == to {
						continue
					}
					if !contains(parents[to], from) {
						if len(parents[to]) < opt.MaxParents && !createsCycle(parents, from, to) {
							np := insertSorted(parents[to], from)
							consider("add", 0, from, to, s.family(to, np)-cur[to], np, nil)
						}
						continue
					}
					np := remove(parents[to], from)
					consider("delete", 1, from, to, s.family(to, np)-cur[to], np, nil)
					if len(parents[from]) < opt.MaxParents && !reversalCreatesCycle(parents, from, to) {
						nf := insertSorted(parents[from], to)
						consider("reverse", 2, from, to, s.family(to, np)+s.family(from, nf)-cur[to]-cur[from], np, nf)
					}
				}
			}
			if !found {
				break
			}
			switch bm.Kind {
			case "add":
				parents[bm.To] = bp[0]
				cur[bm.To] = s.family(bm.To, bp[0])
				tabu = append(tabu, [3]int{1, bm.From, bm.To}) // do not delete it again
			case "delete":
				parents[bm.To] = bp[0]
				cur[bm.To] = s.family(bm.To, bp[0])
				tabu = append(tabu, [3]int{0, bm.From, bm.To}) // do not re-add it
			case "reverse":
				parents[bm.To], parents[bm.From] = bp[0], bp[1]
				cur[bm.To], cur[bm.From] = s.family(bm.To, bp[0]), s.family(bm.From, bp[1])
				tabu = append(tabu, [3]int{2, bm.To, bm.From}) // do not flip it back
			}
			if len(tabu) > opt.Tabu {
				tabu = tabu[1:]
			}
			total += bm.Gain
			steps = append(steps, bm)
			if total > bestTotal+1e-9 {
				bestTotal, bestParents, bestLen, stale = total, cloneParents(parents), len(steps), 0
			} else {
				stale++
			}
		}
		return bestParents, bestTotal, steps[:bestLen]
	}
	best.Parents, best.Score, best.Steps = climb(parents, cur)
	rng := rand.New(rand.NewSource(opt.Seed))
	for r := 0; r < opt.Restarts; r++ {
		p := cloneParents(best.Parents)
		// perturb: flip a handful of random edges (keeping the graph acyclic)
		for k := 0; k < 2+nv/3; k++ {
			a, b := rng.Intn(nv), rng.Intn(nv)
			if a == b {
				continue
			}
			switch {
			case contains(p[b], a):
				p[b] = remove(p[b], a)
			case len(p[b]) < opt.MaxParents && !createsCycle(p, a, b):
				p[b] = insertSorted(p[b], a)
			}
		}
		c := make([]float64, nv)
		for v := range c {
			c[v] = s.family(v, p[v])
		}
		if bp, bt, st := climb(p, c); bt > best.Score+1e-9 {
			// The score of a restart is reported without a step list: its path started from a perturbed graph.
			best.Parents, best.Score, best.Steps = bp, bt, st
			best.Restarted = true
		}
	}
	return best, nil
}

func contains(s []int, x int) bool {
	for _, y := range s {
		if y == x {
			return true
		}
	}
	return false
}

func insertSorted(s []int, x int) []int {
	out := append(append([]int(nil), s...), x)
	sort.Ints(out)
	return out
}

func remove(s []int, x int) []int {
	out := make([]int, 0, len(s))
	for _, y := range s {
		if y != x {
			out = append(out, y)
		}
	}
	return out
}

func cloneParents(p [][]int) [][]int {
	out := make([][]int, len(p))
	for i := range p {
		out[i] = append([]int(nil), p[i]...)
	}
	return out
}

// createsCycle reports whether adding the edge from→to would close a directed
// cycle, i.e. whether `to` is already an ancestor of `from` (walk parent links
// upward from `from`).
func createsCycle(parents [][]int, from, to int) bool {
	seen := map[int]bool{}
	stack := []int{from}
	for len(stack) > 0 {
		v := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if v == to {
			return true
		}
		if seen[v] {
			continue
		}
		seen[v] = true
		stack = append(stack, parents[v]...)
	}
	return false
}

// reversalCreatesCycle: would reversing from→to (adding to→from) close a cycle? That
// happens iff `to` has another directed path to `from` besides the edge itself,
// i.e. `from` has an ancestor path to `to` not via that edge.
func reversalCreatesCycle(parents [][]int, from, to int) bool {
	seen := map[int]bool{}
	var stack []int
	for _, p := range parents[to] { // walk up from `to`, skipping the direct edge from→to
		if p != from {
			stack = append(stack, p)
		}
	}
	for len(stack) > 0 {
		v := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if v == from {
			return true
		}
		if seen[v] {
			continue
		}
		seen[v] = true
		stack = append(stack, parents[v]...)
	}
	return false
}

// Apply builds a network with the learned structure and smoothed-MLE CPTs.
func (r *StructureResult) Apply(net *bn.Network, ds *parse.Dataset, alpha float64) (*bn.Network, error) {
	out := net.Clone()
	for v := range out.Vars {
		out.SetParents(v, r.Parents[v])
	}
	if errs := out.Validate(); len(errs) > 0 {
		return nil, errs[0]
	}
	return Fit(out, ds, alpha)
}
