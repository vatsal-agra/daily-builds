// Package sat is a compact CDCL SAT solver: two-watched-literal propagation,
// first-UIP clause learning with local minimisation, VSIDS branching with phase
// saving, Luby restarts, learnt-clause database reduction and solving under
// assumptions (which is what makes incremental SAT-sweeping practical).
package sat

import "sort"

// Lit is 2*var + sign (sign 1 = negated).
type Lit int32

const undefLit Lit = -1

// MkLit builds a literal for variable v.
func MkLit(v int, neg bool) Lit {
	if neg {
		return Lit(2*v + 1)
	}
	return Lit(2 * v)
}
func (l Lit) Var() int   { return int(l) >> 1 }
func (l Lit) Neg() bool  { return l&1 == 1 }
func (l Lit) Not() Lit   { return l ^ 1 }
func (l Lit) Sign() int8 { return int8(l & 1) }
func (l Lit) NotIf(b bool) Lit {
	if b {
		return l ^ 1
	}
	return l
}

// Result of a Solve call.
type Result int

const (
	Unknown Result = iota
	Sat
	Unsat
)

func (r Result) String() string {
	switch r {
	case Sat:
		return "SAT"
	case Unsat:
		return "UNSAT"
	}
	return "UNKNOWN"
}

const (
	lTrue  int8 = 1
	lFalse int8 = -1
	lUndef int8 = 0
)

type clause struct {
	lits    []Lit
	learnt  bool
	deleted bool
	act     float64
}

type watcher struct {
	c       *clause
	blocker Lit
}

// Solver holds one incremental SAT instance.
type Solver struct {
	ok       bool
	nvars    int
	clauses  []*clause
	learnts  []*clause
	watches  [][]watcher // indexed by literal: clauses to visit when that literal becomes true
	vals     []int8      // value per literal: 1 true, -1 false, 0 undefined
	level    []int32
	reason   []*clause
	trail    []Lit
	trailLim []int
	qhead    int

	activity []float64
	varInc   float64
	claInc   float64
	polarity []bool // saved phase: true = assign negated
	seen     []bool
	heap     []int // binary max-heap of vars by activity
	heapPos  []int // position in heap, -1 if absent

	model []bool

	// Stats
	Conflicts    int64
	Decisions    int64
	Propagations int64
	budget       int64 // conflict budget; <0 = unlimited
	maxLearnts   float64
}

// New returns an empty solver.
func New() *Solver {
	return &Solver{ok: true, varInc: 1, claInc: 1, budget: -1}
}

// NumVars returns the number of variables created so far.
func (s *Solver) NumVars() int { return s.nvars }

// NewVar creates a fresh variable and returns its index.
func (s *Solver) NewVar() int {
	v := s.nvars
	s.vals = append(s.vals, lUndef, lUndef)
	s.nvars++
	s.level = append(s.level, 0)
	s.reason = append(s.reason, nil)
	s.activity = append(s.activity, 0)
	s.polarity = append(s.polarity, true)
	s.seen = append(s.seen, false)
	s.watches = append(s.watches, nil, nil)
	s.heapPos = append(s.heapPos, -1)
	s.heapInsert(v)
	return v
}

// SetConflictBudget limits the conflicts of subsequent Solve calls (<0 = unlimited).
func (s *Solver) SetConflictBudget(n int64) { s.budget = n }

func (s *Solver) value(l Lit) int8 { return s.vals[l] }

func (s *Solver) decisionLevel() int { return len(s.trailLim) }

// AddClause adds a clause at decision level 0. It returns false once the
// formula is known to be unsatisfiable.
func (s *Solver) AddClause(lits ...Lit) bool {
	if !s.ok {
		return false
	}
	s.cancelUntil(0)
	ls := append([]Lit(nil), lits...)
	sort.Slice(ls, func(i, j int) bool { return ls[i] < ls[j] })
	out := ls[:0]
	prev := undefLit
	for _, l := range ls {
		if s.value(l) == lTrue || (prev != undefLit && l == prev.Not()) {
			return true // satisfied / tautology
		}
		if s.value(l) != lFalse && l != prev {
			out = append(out, l)
			prev = l
		}
	}
	switch len(out) {
	case 0:
		s.ok = false
		return false
	case 1:
		s.enqueue(out[0], nil)
		if s.propagate() != nil {
			s.ok = false
			return false
		}
		return true
	}
	c := &clause{lits: out}
	s.clauses = append(s.clauses, c)
	s.attach(c)
	return true
}

func (s *Solver) attach(c *clause) {
	s.watches[c.lits[0].Not()] = append(s.watches[c.lits[0].Not()], watcher{c, c.lits[1]})
	s.watches[c.lits[1].Not()] = append(s.watches[c.lits[1].Not()], watcher{c, c.lits[0]})
}

func (s *Solver) enqueue(l Lit, from *clause) {
	v := l.Var()
	s.vals[l] = lTrue
	s.vals[l^1] = lFalse
	s.level[v] = int32(s.decisionLevel())
	s.reason[v] = from
	s.trail = append(s.trail, l)
}

func (s *Solver) propagate() *clause {
	var confl *clause
	for s.qhead < len(s.trail) {
		p := s.trail[s.qhead]
		s.qhead++
		s.Propagations++
		ws := s.watches[p]
		falseLit := p.Not()
		i, j := 0, 0
		for i < len(ws) {
			w := ws[i]
			i++
			if w.c.deleted {
				continue
			}
			if s.value(w.blocker) == lTrue {
				ws[j] = w
				j++
				continue
			}
			c := w.c
			if c.lits[0] == falseLit {
				c.lits[0], c.lits[1] = c.lits[1], falseLit
			}
			first := c.lits[0]
			nw := watcher{c, first}
			if first != w.blocker && s.value(first) == lTrue {
				ws[j] = nw
				j++
				continue
			}
			found := false
			for k := 2; k < len(c.lits); k++ {
				if s.value(c.lits[k]) != lFalse {
					c.lits[1], c.lits[k] = c.lits[k], falseLit
					nl := c.lits[1].Not()
					s.watches[nl] = append(s.watches[nl], nw)
					found = true
					break
				}
			}
			if found {
				continue
			}
			ws[j] = nw
			j++
			if s.value(first) == lFalse {
				confl = c
				s.qhead = len(s.trail)
				for i < len(ws) {
					ws[j] = ws[i]
					i++
					j++
				}
			} else {
				s.enqueue(first, c)
			}
		}
		s.watches[p] = ws[:j]
		if confl != nil {
			return confl
		}
	}
	return nil
}

func (s *Solver) cancelUntil(lvl int) {
	if s.decisionLevel() <= lvl {
		return
	}
	for i := len(s.trail) - 1; i >= s.trailLim[lvl]; i-- {
		v := s.trail[i].Var()
		s.polarity[v] = s.trail[i].Neg()
		s.vals[2*v], s.vals[2*v+1] = lUndef, lUndef
		s.reason[v] = nil
		if s.heapPos[v] < 0 {
			s.heapInsert(v)
		}
	}
	s.trail = s.trail[:s.trailLim[lvl]]
	s.trailLim = s.trailLim[:lvl]
	s.qhead = len(s.trail)
}

// analyze derives a first-UIP learnt clause (asserting literal first) and the backtrack level.
func (s *Solver) analyze(confl *clause) ([]Lit, int) {
	learnt := []Lit{undefLit}
	pathC := 0
	p := undefLit
	idx := len(s.trail) - 1
	for {
		if confl.learnt {
			s.bumpClause(confl)
		}
		start := 0
		if p != undefLit {
			start = 1
		}
		for _, q := range confl.lits[start:] {
			v := q.Var()
			if !s.seen[v] && s.level[v] > 0 {
				s.bumpVar(v)
				s.seen[v] = true
				if int(s.level[v]) >= s.decisionLevel() {
					pathC++
				} else {
					learnt = append(learnt, q)
				}
			}
		}
		for !s.seen[s.trail[idx].Var()] {
			idx--
		}
		p = s.trail[idx]
		idx--
		confl = s.reason[p.Var()]
		s.seen[p.Var()] = false
		pathC--
		if pathC <= 0 {
			break
		}
	}
	learnt[0] = p.Not()

	// local minimisation: drop literals implied by the rest of the clause
	toClear := append([]Lit(nil), learnt...)
	j := 1
	for i := 1; i < len(learnt); i++ {
		r := s.reason[learnt[i].Var()]
		keep := true
		if r != nil {
			keep = false
			for _, q := range r.lits[1:] {
				if !s.seen[q.Var()] && s.level[q.Var()] > 0 {
					keep = true
					break
				}
			}
		}
		if keep {
			learnt[j] = learnt[i]
			j++
		}
	}
	learnt = learnt[:j]
	for _, l := range toClear {
		s.seen[l.Var()] = false
	}

	bt := 0
	if len(learnt) > 1 {
		mi := 1
		for i := 2; i < len(learnt); i++ {
			if s.level[learnt[i].Var()] > s.level[learnt[mi].Var()] {
				mi = i
			}
		}
		learnt[1], learnt[mi] = learnt[mi], learnt[1]
		bt = int(s.level[learnt[1].Var()])
	}
	return learnt, bt
}

func (s *Solver) bumpVar(v int) {
	s.activity[v] += s.varInc
	if s.activity[v] > 1e100 {
		for i := range s.activity {
			s.activity[i] *= 1e-100
		}
		s.varInc *= 1e-100
	}
	if s.heapPos[v] >= 0 {
		s.heapUp(s.heapPos[v])
	}
}

func (s *Solver) bumpClause(c *clause) {
	c.act += s.claInc
	if c.act > 1e20 {
		for _, l := range s.learnts {
			l.act *= 1e-20
		}
		s.claInc *= 1e-20
	}
}

// --- order heap -----------------------------------------------------------

func (s *Solver) heapLess(a, b int) bool { return s.activity[a] > s.activity[b] }

func (s *Solver) heapInsert(v int) {
	s.heapPos[v] = len(s.heap)
	s.heap = append(s.heap, v)
	s.heapUp(s.heapPos[v])
}

func (s *Solver) heapUp(i int) {
	x := s.heap[i]
	for i > 0 {
		p := (i - 1) / 2
		if !s.heapLess(x, s.heap[p]) {
			break
		}
		s.heap[i] = s.heap[p]
		s.heapPos[s.heap[i]] = i
		i = p
	}
	s.heap[i] = x
	s.heapPos[x] = i
}

func (s *Solver) heapDown(i int) {
	x := s.heap[i]
	n := len(s.heap)
	for {
		l := 2*i + 1
		if l >= n {
			break
		}
		c := l
		if r := l + 1; r < n && s.heapLess(s.heap[r], s.heap[l]) {
			c = r
		}
		if !s.heapLess(s.heap[c], x) {
			break
		}
		s.heap[i] = s.heap[c]
		s.heapPos[s.heap[i]] = i
		i = c
	}
	s.heap[i] = x
	s.heapPos[x] = i
}

func (s *Solver) heapPop() int {
	x := s.heap[0]
	last := s.heap[len(s.heap)-1]
	s.heap = s.heap[:len(s.heap)-1]
	s.heapPos[x] = -1
	if len(s.heap) > 0 {
		s.heap[0] = last
		s.heapPos[last] = 0
		s.heapDown(0)
	}
	return x
}

func (s *Solver) pickBranch() Lit {
	for len(s.heap) > 0 {
		v := s.heapPop()
		if s.vals[2*v] == lUndef {
			return MkLit(v, s.polarity[v])
		}
	}
	return undefLit
}

// --- database reduction --------------------------------------------------

func (s *Solver) locked(c *clause) bool {
	return s.value(c.lits[0]) == lTrue && s.reason[c.lits[0].Var()] == c
}

func (s *Solver) reduceDB() {
	sort.Slice(s.learnts, func(i, j int) bool {
		a, b := s.learnts[i], s.learnts[j]
		if (len(a.lits) <= 2) != (len(b.lits) <= 2) {
			return len(b.lits) <= 2
		}
		return a.act < b.act
	})
	half := len(s.learnts) / 2
	keep := s.learnts[:0]
	for i, c := range s.learnts {
		if i < half && len(c.lits) > 2 && !s.locked(c) {
			c.deleted = true
		} else {
			keep = append(keep, c)
		}
	}
	s.learnts = keep
	for i := range s.watches {
		ws := s.watches[i]
		k := 0
		for _, w := range ws {
			if !w.c.deleted {
				ws[k] = w
				k++
			}
		}
		s.watches[i] = ws[:k]
	}
}

func luby(y float64, x int) float64 {
	size, seq := 1, 0
	for size < x+1 {
		seq++
		size = 2*size + 1
	}
	for size-1 != x {
		size = (size - 1) >> 1
		seq--
		x = x % size
	}
	r := 1.0
	for i := 0; i < seq; i++ {
		r *= y
	}
	return r
}

func (s *Solver) search(nofConflicts int, assumps []Lit) Result {
	conflictC := 0
	for {
		confl := s.propagate()
		if confl != nil {
			s.Conflicts++
			conflictC++
			if s.decisionLevel() == 0 {
				s.ok = false
				return Unsat
			}
			learnt, bt := s.analyze(confl)
			s.cancelUntil(bt)
			if len(learnt) == 1 {
				s.enqueue(learnt[0], nil)
			} else {
				c := &clause{lits: learnt, learnt: true}
				s.learnts = append(s.learnts, c)
				s.attach(c)
				s.bumpClause(c)
				s.enqueue(learnt[0], c)
			}
			s.varInc /= 0.95
			s.claInc /= 0.999
			continue
		}
		if conflictC >= nofConflicts {
			s.cancelUntil(0)
			return Unknown
		}
		if s.budget >= 0 && s.Conflicts >= s.budget {
			s.cancelUntil(0)
			return Unknown
		}
		if float64(len(s.learnts)-len(s.trail)) >= s.maxLearnts {
			s.reduceDB()
		}
		next := undefLit
		for s.decisionLevel() < len(assumps) {
			p := assumps[s.decisionLevel()]
			switch s.value(p) {
			case lTrue:
				s.trailLim = append(s.trailLim, len(s.trail))
			case lFalse:
				s.cancelUntil(0)
				return Unsat // unsatisfiable under these assumptions
			default:
				next = p
			}
			if next != undefLit {
				break
			}
		}
		if next == undefLit {
			s.Decisions++
			next = s.pickBranch()
			if next == undefLit {
				s.model = make([]bool, s.nvars)
				for v := range s.model {
					s.model[v] = s.vals[2*v] == lTrue
				}
				s.cancelUntil(0)
				return Sat
			}
		}
		s.trailLim = append(s.trailLim, len(s.trail))
		s.enqueue(next, nil)
	}
}

// Solve decides satisfiability under the given assumptions. After Sat, Value
// reports the model. After Unsat the formula may still be satisfiable without
// the assumptions (see Okay).
func (s *Solver) Solve(assumps ...Lit) Result {
	if !s.ok {
		return Unsat
	}
	s.cancelUntil(0)
	if s.propagate() != nil {
		s.ok = false
		return Unsat
	}
	s.maxLearnts = float64(len(s.clauses))/3 + 1000
	startConf := s.Conflicts
	for i := 0; ; i++ {
		nof := int(luby(2, i) * 100)
		r := s.search(nof, assumps)
		if r != Unknown {
			return r
		}
		if s.budget >= 0 && s.Conflicts >= s.budget {
			return Unknown
		}
		s.maxLearnts *= 1.05
		_ = startConf
	}
}

// Okay is false once the clause set is unsatisfiable regardless of assumptions.
func (s *Solver) Okay() bool { return s.ok }

// Value returns the model value of variable v after a Sat result.
func (s *Solver) Value(v int) bool {
	if v < len(s.model) {
		return s.model[v]
	}
	return false
}

// LitValue returns the model value of a literal.
func (s *Solver) LitValue(l Lit) bool { return s.Value(l.Var()) != l.Neg() }
