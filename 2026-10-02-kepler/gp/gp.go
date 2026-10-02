// Package gp is the genetic-programming search over expression trees.
package gp

import (
	"fmt"
	"math"
	"math/rand"
	"sort"
	"sync"
	"time"

	"kepler/data"
	"kepler/expr"
)

// Config controls a search run.
type Config struct {
	Pop          int   // individuals per island
	Gens         int   // generations
	Islands      int   // parallel populations
	Seed         int64 // determinism: same seed + config => same result
	MaxSize      int   // node limit (bloat control)
	MaxDepth     int
	Unary        []string      // enabled unary ops
	Binary       []string      // enabled binary ops
	Parsimony    float64       // selection penalty per complexity unit (multiplicative)
	MigrateEvery int           // generations between ring migrations
	StopErr      float64       // stop when best NMSE <= this
	Holdout      float64       // fraction held out for model selection (0 = none)
	TimeLimit    time.Duration // wall-clock budget (0 = unlimited)
	Stop         func() bool   // polled each generation; true ends the search early
	Verbose      func(string)
}

// DefaultConfig returns sensible settings.
func DefaultConfig() Config {
	return Config{
		Pop: 300, Gens: 60, Islands: 4, Seed: 1, MaxSize: 35, MaxDepth: 9,
		Unary:     []string{"sqrt", "exp", "log", "sin", "cos"},
		Binary:    []string{"+", "-", "*", "/", "^"},
		Parsimony: 0.002, MigrateEvery: 5, StopErr: 1e-12, Holdout: 0.25,
	}
}

// Validate reports unusable configurations.
func (c *Config) Validate(nvars int) error {
	switch {
	case c.Pop < 10:
		return fmt.Errorf("population must be >= 10")
	case c.Gens < 1:
		return fmt.Errorf("generations must be >= 1")
	case c.Islands < 1:
		return fmt.Errorf("islands must be >= 1")
	case c.MaxSize < 3:
		return fmt.Errorf("max size must be >= 3")
	case len(c.Binary) == 0:
		return fmt.Errorf("at least one binary operator required")
	case nvars < 1:
		return fmt.Errorf("dataset has no input variables")
	case c.Holdout < 0 || c.Holdout >= 0.9:
		return fmt.Errorf("holdout must be in [0, 0.9)")
	}
	for _, o := range c.Unary {
		if !has(expr.UnaryOps, o) {
			return fmt.Errorf("unknown unary op %q", o)
		}
	}
	for _, o := range c.Binary {
		if !has(expr.BinaryOps, o) {
			return fmt.Errorf("unknown binary op %q", o)
		}
	}
	return nil
}

func has(s []string, x string) bool {
	for _, v := range s {
		if v == x {
			return true
		}
	}
	return false
}

// Indiv is a candidate formula with cached scores.
type Indiv struct {
	Tree  *expr.Node
	NMSE  float64 // on training data
	Comp  int
	Score float64 // selection score (lower better)
}

// Model is one entry of the final Pareto front.
type Model struct {
	Tree        *expr.Node
	Complexity  int
	TrainNMSE   float64
	HoldoutNMSE float64 // NaN when no holdout
}

// Result of a search.
type Result struct {
	Front       []Model // ascending complexity, strictly improving train NMSE
	Selected    int     // index into Front of the recommended model
	Generations int
	Evals       int64
	Names       []string
}

type island struct {
	pop   []*Indiv
	rng   *rand.Rand
	nv    int
	cfg   *Config
	pr    *Problem
	evals int64
}

// Run searches for formulas fitting d.
func Run(d *data.Dataset, cfg Config) (*Result, error) {
	if err := cfg.Validate(len(d.Names)); err != nil {
		return nil, err
	}
	if d.N() < 5 {
		return nil, fmt.Errorf("need at least 5 data rows, have %d", d.N())
	}
	train, hold := d, (*data.Dataset)(nil)
	if cfg.Holdout > 0 && d.N() >= 20 {
		train, hold = d.Split(cfg.Holdout, cfg.Seed+7919)
	}
	pr := NewProblem(train)
	var hpr *Problem
	if hold != nil {
		hpr = NewProblem(hold)
	}
	// Keep the search cheap on big data: subsample training rows for selection;
	// the final polish re-scores on the full training set.
	search := pr
	if train.N() > 400 {
		sub := &data.Dataset{Names: train.Names}
		step := float64(train.N()) / 400
		for i := 0; i < 400; i++ {
			j := int(float64(i) * step)
			sub.X = append(sub.X, train.X[j])
			sub.Y = append(sub.Y, train.Y[j])
		}
		search = NewProblem(sub)
	}

	isl := make([]*island, cfg.Islands)
	for i := range isl {
		isl[i] = &island{rng: rand.New(rand.NewSource(cfg.Seed*1000 + int64(i))), nv: len(d.Names), cfg: &cfg, pr: search}
		isl[i].init()
	}
	arch := newArchive()
	for _, is := range isl {
		for _, ind := range is.pop {
			arch.offer(ind)
		}
	}
	var gens int
	start := time.Now()
	for g := 0; g < cfg.Gens; g++ {
		gens = g + 1
		var wg sync.WaitGroup
		for _, is := range isl {
			wg.Add(1)
			go func(is *island) { defer wg.Done(); is.step() }(is)
		}
		wg.Wait()
		for _, is := range isl {
			for _, ind := range is.pop {
				arch.offer(ind)
			}
		}
		if cfg.Islands > 1 && cfg.MigrateEvery > 0 && (g+1)%cfg.MigrateEvery == 0 {
			migrate(isl)
		}
		best := arch.best()
		if cfg.Verbose != nil && best != nil && (g%5 == 0 || g == cfg.Gens-1) {
			cfg.Verbose(fmt.Sprintf("gen %3d  best nmse %.3e  %s", g+1, best.NMSE, best.Tree.Format(d.Names)))
		}
		if best != nil && best.NMSE <= cfg.StopErr {
			break
		}
		if cfg.TimeLimit > 0 && time.Since(start) >= cfg.TimeLimit {
			break
		}
		if cfg.Stop != nil && cfg.Stop() {
			break
		}
	}
	var evals int64
	for _, is := range isl {
		evals += is.evals
	}
	return finalize(arch, pr, hpr, d.Names, gens, evals), nil
}

// finalize polishes archive members on the full training set, simplifies,
// snaps constants, rebuilds the Pareto front and picks a recommended model.
func finalize(arch *archive, pr, hpr *Problem, names []string, gens int, evals int64) *Result {
	var cand []Model
	add := func(t *expr.Node) {
		m := Model{Tree: t, Complexity: t.Complexity(), TrainNMSE: pr.NMSE(t), HoldoutNMSE: math.NaN()}
		if math.IsInf(m.TrainNMSE, 0) || math.IsNaN(m.TrainNMSE) {
			return
		}
		if hpr != nil {
			m.HoldoutNMSE = hpr.NMSE(t)
		}
		cand = append(cand, m)
	}
	for _, ind := range arch.members() {
		raw := expr.Simplify(ind.Tree)
		pr.FitConstants(raw, 400, 2)
		// cleaned: numerically-equivalent pruning + nice-number snapping
		clean := pr.Prune(raw.Clone(), 0.02)
		pr.Snap(clean, 0.02)
		clean = expr.Simplify(clean)
		pr.FitConstants(clean, 200, 1) // re-tune what snapping left free
		pr.Snap(clean, 0.02)
		clean = expr.Simplify(clean)
		pr.Snap(clean, 0.02)
		add(expr.Simplify(clean)) // cleaned first: wins exact ties
		add(raw)
	}
	sort.SliceStable(cand, func(i, j int) bool {
		if cand[i].Complexity != cand[j].Complexity {
			return cand[i].Complexity < cand[j].Complexity
		}
		return floor(cand[i].TrainNMSE) < floor(cand[j].TrainNMSE)
	})
	var front []Model
	for _, m := range cand {
		// a higher-complexity model must be strictly better to stay on the front;
		// errors below the numeric floor count as equal
		if len(front) == 0 || floor(m.TrainNMSE) < floor(front[len(front)-1].TrainNMSE)*0.99 {
			front = append(front, m)
		}
	}
	return &Result{Front: front, Selected: SelectModel(front), Generations: gens, Evals: evals, Names: names}
}

// SelectModel picks the front member minimising a complexity-adjusted error:
// err * exp(0.06*complexity), with err = holdout NMSE when available (else
// training NMSE) floored at 1e-12. Near-equal errors therefore resolve to the
// simpler formula, while a model must cut error by a real margin to justify
// extra terms — the usual knee of the Pareto curve.
func SelectModel(front []Model) int {
	best, bi := math.Inf(1), -1
	for i, m := range front {
		e := m.TrainNMSE
		if !math.IsNaN(m.HoldoutNMSE) {
			e = m.HoldoutNMSE
		}
		if v := floor(e) * math.Exp(0.06*float64(m.Complexity)); v < best {
			best, bi = v, i
		}
	}
	return bi
}

func migrate(isl []*island) {
	// ring: each island sends its best 3 to the next, replacing that island's worst 3
	n := len(isl)
	out := make([][]*Indiv, n)
	for i, is := range isl {
		sort.SliceStable(is.pop, func(a, b int) bool { return is.pop[a].Score < is.pop[b].Score })
		for k := 0; k < 3 && k < len(is.pop); k++ {
			p := is.pop[k]
			out[i] = append(out[i], &Indiv{Tree: p.Tree.Clone(), NMSE: p.NMSE, Comp: p.Comp, Score: p.Score})
		}
	}
	for i, is := range isl {
		for k, m := range out[(i+n-1)%n] {
			is.pop[len(is.pop)-1-k] = m
		}
	}
}

// ---- archive (Pareto hall of fame) ----

type archive struct {
	byComp map[int]*Indiv
}

func newArchive() *archive { return &archive{byComp: map[int]*Indiv{}} }

func (a *archive) offer(ind *Indiv) {
	if math.IsInf(ind.NMSE, 0) || math.IsNaN(ind.NMSE) {
		return
	}
	cur := a.byComp[ind.Comp]
	if cur == nil || ind.NMSE < cur.NMSE {
		a.byComp[ind.Comp] = &Indiv{Tree: ind.Tree.Clone(), NMSE: ind.NMSE, Comp: ind.Comp, Score: ind.Score}
	}
}

// members returns the non-dominated entries by complexity ascending.
func (a *archive) members() []*Indiv {
	var keys []int
	for k := range a.byComp {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	var out []*Indiv
	best := math.Inf(1)
	for _, k := range keys {
		if e := a.byComp[k].NMSE; e < best {
			best = e
			out = append(out, a.byComp[k])
		}
	}
	return out
}

func (a *archive) best() *Indiv {
	m := a.members()
	if len(m) == 0 {
		return nil
	}
	return m[len(m)-1]
}

// floor treats errors under 1e-12 as numerically zero (float noise).
func floor(e float64) float64 { return math.Max(e, 1e-12) }
