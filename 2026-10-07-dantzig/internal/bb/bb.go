package bb

import (
	"container/heap"
	"fmt"
	"io"
	"math"
	"math/big"
	"time"

	"dantzig/internal/exact"
	"dantzig/internal/lp"
	"dantzig/internal/model"
	"dantzig/internal/simplex"
)

// Status of a MIP solve.
type Status string

const (
	Optimal             Status = "optimal"
	Infeasible          Status = "infeasible"
	Unbounded           Status = "unbounded"
	UnboundedRelaxation Status = "unbounded_relaxation"
	Limit               Status = "limit"
	Unknown             Status = "unknown"
)

// Options configure a solve.
type Options struct {
	TimeLimit   time.Duration // 0 = none
	NodeLimit   int           // 0 = none
	Branch      string        // "pseudo" (default) or "mostfrac"
	NoProof     bool          // skip exact leaf certificates (faster, uncertified)
	NoDive      bool          // disable the root diving heuristic
	Log         io.Writer
	LogEvery    int
	OpenCertCap int // max open nodes to certify on a limit stop (default 2000)
}

// TracePoint is one sample of search progress.
type TracePoint struct {
	Node      int
	Seconds   float64
	Incumbent *float64 // original-sense objective
	Bound     *float64
}

// Result of a solve.
type Result struct {
	Status      Status
	X           []*big.Rat
	Obj         *big.Rat // original sense incl. constant
	Bound       *big.Rat // proven global bound, original sense (nil if unknown)
	Nodes       int
	LPIters     int
	DiveFound   int
	Uncertified int
	Certified   bool // every claim in Proof checks exactly
	Note        string
	Proof       *Proof
	Trace       []TracePoint
	Elapsed     time.Duration
	RootLP      *float64 // root relaxation objective (original sense, float)
}

type node struct {
	box   exact.Box
	basis []byte
	lb    float64
	depth int
	pn    *PNode
	bvar  int
	bup   bool
	bfrac float64 // fractional distance moved by the branch
	pobj  float64
	idx   int
	seq   int
}

type nodeHeap []*node

func (h nodeHeap) Len() int { return len(h) }
func (h nodeHeap) Less(i, j int) bool {
	if h[i].lb != h[j].lb {
		return h[i].lb < h[j].lb
	}
	return h[i].seq > h[j].seq
}
func (h nodeHeap) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *nodeHeap) Push(x any)   { *h = append(*h, x.(*node)) }
func (h *nodeHeap) Pop() any {
	old := *h
	n := old[len(old)-1]
	*h = old[:len(old)-1]
	return n
}

type solver struct {
	m            *model.Model
	opt          Options
	n            int
	cost         []*big.Rat
	intIdx       []int
	intObj       bool
	ws           *simplex.Solver
	inc          []*big.Rat
	incObj       *big.Rat // internal min sense (no constant)
	incF         float64
	incLeaf      *PNode
	open         nodeHeap
	res          *Result
	start        time.Time
	seq          int
	pcUp, pcDn   []float64
	pcUpN, pcDnN []int
	unc          int
	unbounded    bool
	rootRay      []*big.Rat
	rootX0       []*big.Rat
}

func (s *solver) sign() *big.Rat {
	if s.m.Maximize {
		return big.NewRat(-1, 1)
	}
	return big.NewRat(1, 1)
}

func (s *solver) toOrig(v *big.Rat) *big.Rat {
	o := new(big.Rat).Mul(v, s.sign())
	return o.Add(o, s.m.ObjConst)
}

func (s *solver) toOrigF(v float64) float64 {
	if s.m.Maximize {
		v = -v
	}
	return v + model.Float(s.m.ObjConst)
}

func (s *solver) setBoxFloat(box exact.Box) {
	for j := 0; j < s.n; j++ {
		lo, hi := math.Inf(-1), math.Inf(1)
		if box.Lo[j] != nil {
			lo = model.Float(box.Lo[j])
		}
		if box.Hi[j] != nil {
			hi = model.Float(box.Hi[j])
		}
		s.ws.SetBounds(j, lo, hi)
	}
}

// cutoff value passed to the dual simplex.
func (s *solver) cutoff() float64 {
	if s.inc == nil {
		return math.Inf(1)
	}
	if s.intObj {
		return s.incF - 1 + 1e-6
	}
	return s.incF
}

// prunable reports whether a float LP bound lb cannot beat the incumbent.
func (s *solver) prunable(lb float64) bool {
	if s.inc == nil {
		return false
	}
	if s.intObj {
		return lb > s.incF-1+1e-6
	}
	return lb >= s.incF-1e-9*(1+math.Abs(s.incF))
}

// exactPrunes checks the exact version of the pruning rule.
func (s *solver) exactPrunes(b *big.Rat) bool {
	if s.incObj == nil {
		return false
	}
	if s.intObj {
		b = ceilRat(b)
	}
	return b.Cmp(s.incObj) >= 0
}

func fptr(v float64) *float64 { return &v }

// Solve runs branch & bound on m.
func Solve(m *model.Model, opt Options) *Result {
	if opt.Branch == "" {
		opt.Branch = "pseudo"
	}
	if opt.OpenCertCap == 0 {
		opt.OpenCertCap = 2000
	}
	if opt.LogEvery == 0 {
		opt.LogEvery = 25
	}
	s := &solver{m: m, opt: opt, n: len(m.Vars), cost: m.MinCost(), intObj: m.ObjIsIntegral(), start: time.Now()}
	s.res = &Result{}
	for j, v := range m.Vars {
		if v.Int {
			s.intIdx = append(s.intIdx, j)
		}
	}
	s.pcUp, s.pcDn = make([]float64, s.n), make([]float64, s.n)
	s.pcUpN, s.pcDnN = make([]int, s.n), make([]int, s.n)
	s.run()
	s.res.Elapsed = time.Since(s.start)
	s.finish()
	return s.res
}

func (s *solver) logf(f string, a ...any) {
	if s.opt.Log != nil {
		fmt.Fprintf(s.opt.Log, f, a...)
	}
}

func (s *solver) globalBoundF(cur *node) float64 {
	b := math.Inf(1)
	if cur != nil {
		b = cur.lb
	}
	if len(s.open) > 0 && s.open[0].lb < b {
		b = s.open[0].lb
	}
	return b
}

func (s *solver) trace(cur *node) {
	tp := TracePoint{Node: s.res.Nodes, Seconds: time.Since(s.start).Seconds()}
	if s.inc != nil {
		tp.Incumbent = fptr(s.toOrigF(s.incF))
	}
	if gb := s.globalBoundF(cur); !math.IsInf(gb, 0) {
		tp.Bound = fptr(s.toOrigF(gb))
	}
	s.res.Trace = append(s.res.Trace, tp)
}

func (s *solver) run() {
	m := s.m
	box0 := exact.BoxOf(m)
	root := &node{box: box0, lb: math.Inf(-1), pn: &PNode{}, bvar: -1}
	s.res.Proof = &Proof{Version: 1, ModelHash: HashModel(m), Tree: root.pn}
	if box0.Empty() {
		root.pn.Leaf = "farkas"
		s.res.Note = "a variable has lower bound above upper bound"
		return
	}
	s.ws = simplex.New(lp.Build(m, box0))
	var cur *node = root
	first := true
	for cur != nil || len(s.open) > 0 {
		if s.unbounded {
			return
		}
		if s.opt.TimeLimit > 0 && time.Since(s.start) > s.opt.TimeLimit {
			s.res.Note = "time limit reached"
			s.stopWith(cur)
			return
		}
		if s.opt.NodeLimit > 0 && s.res.Nodes >= s.opt.NodeLimit {
			s.res.Note = "node limit reached"
			s.stopWith(cur)
			return
		}
		if cur == nil {
			cur = heap.Pop(&s.open).(*node)
			if s.prunable(cur.lb) {
				s.boundLeafFromBasis(cur)
				cur = nil
				continue
			}
			s.setBoxFloat(cur.box)
			if err := s.ws.LoadBasis(cur.basis); err != nil {
				s.ws.ResetSlack()
				s.setBoxFloat(cur.box)
			}
		} else if !first {
			s.setBoxFloat(cur.box)
		}
		first = false
		kids := s.process(cur)
		if s.res.Nodes%s.opt.LogEvery == 0 {
			s.trace(cur)
		}
		if kids == nil {
			cur = nil
			continue
		}
		cur = kids[0]
		heap.Push(&s.open, kids[1])
	}
}

func (s *solver) stopWith(cur *node) {
	cap := s.opt.OpenCertCap
	emit := func(n *node) {
		n.pn.Leaf = "open"
		if !s.opt.NoProof && cap > 0 && n.basis != nil {
			cap--
			if y, _, err := lp.BoundCert(s.m, n.box, n.basis); err == nil {
				n.pn.Y = ratStrs(y)
			}
		}
	}
	if cur != nil {
		emit(cur)
	}
	for _, n := range s.open {
		emit(n)
	}
	s.open = nil
}

// boundLeafFromBasis certifies a heap node by its parent's dual vector.
func (s *solver) boundLeafFromBasis(n *node) {
	if s.opt.NoProof {
		n.pn.Leaf = "bound"
		return
	}
	y, b, err := lp.BoundCert(s.m, n.box, n.basis)
	if err != nil || !s.exactPrunes(b) {
		n.pn.Leaf = "uncertified"
		s.unc++
		return
	}
	n.pn.Leaf, n.pn.Y = "bound", ratStrs(y)
}

// leafBound certifies the current working basis as a bound leaf.
func (s *solver) leafBound(n *node) {
	if s.opt.NoProof {
		n.pn.Leaf = "bound"
		return
	}
	y, b, err := lp.BoundCert(s.m, n.box, s.ws.Statuses())
	if err != nil || !s.exactPrunes(b) {
		n.pn.Leaf = "uncertified"
		s.unc++
		return
	}
	n.pn.Leaf, n.pn.Y = "bound", ratStrs(y)
}

func (s *solver) leafFarkas(n *node) {
	if n.box.Empty() {
		n.pn.Leaf = "farkas"
		n.pn.Y = ratStrs(zeros(len(s.m.Rows)))
		return
	}
	if s.opt.NoProof {
		n.pn.Leaf = "farkas"
		return
	}
	y, err := lp.FarkasCert(s.m, n.box, s.ws)
	if err != nil {
		n.pn.Leaf = "uncertified"
		s.unc++
		return
	}
	n.pn.Leaf, n.pn.Y = "farkas", ratStrs(y)
}

func zeros(k int) []*big.Rat {
	o := make([]*big.Rat, k)
	for i := range o {
		o[i] = new(big.Rat)
	}
	return o
}

func (s *solver) uncertifiedLeaf(n *node, why string) {
	n.pn.Leaf = "uncertified"
	s.unc++
	if s.res.Note == "" {
		s.res.Note = why
	}
}

// process solves one node and returns its two children (nil for a leaf).
func (s *solver) process(nd *node) []*node {
	s.res.Nodes++
	if nd.box.Empty() {
		s.leafFarkas(nd)
		return nil
	}
	before := s.ws.Iters
	res := s.ws.Solve(s.cutoff())
	if res == simplex.IterLimit || res == simplex.NumFail {
		// one more attempt from a clean slack basis
		s.ws.ResetSlack()
		s.setBoxFloat(nd.box)
		res = s.ws.Solve(s.cutoff())
	}
	s.res.LPIters += s.ws.Iters - before
	switch res {
	case simplex.Infeasible:
		s.leafFarkas(nd)
		return nil
	case simplex.Cutoff:
		s.leafBound(nd)
		return nil
	case simplex.Unbounded:
		s.unbounded = true
		if nd.depth == 0 {
			sol := lp.Solve(s.m)
			if sol.Status == lp.Unbounded && sol.Certified {
				s.rootRay, s.rootX0 = sol.Ray, sol.X
			}
		}
		return nil
	case simplex.Optimal:
	default:
		s.uncertifiedLeaf(nd, "LP solver failed ("+res.String()+")")
		return nil
	}
	obj := s.ws.Objective()
	nd.pn.LP = fptr(s.toOrigF(obj))
	if nd.depth == 0 {
		s.res.RootLP = fptr(s.toOrigF(obj))
	}
	s.updatePseudo(nd, obj)
	if s.prunable(obj) {
		s.leafBound(nd)
		return nil
	}
	if nd.depth == 0 && !s.opt.NoDive && len(s.intIdx) > 0 {
		s.dive()
	}
	// fractional integer variables (float view)
	cand := s.fractional()
	status := s.ws.Statuses()
	if len(cand) == 0 {
		x, y, eobj, err := lp.OptimalCert(s.m, nd.box, status)
		if err != nil {
			s.uncertifiedLeaf(nd, "exact verification of an LP optimum failed: "+err.Error())
			return nil
		}
		frac := -1
		for _, j := range s.intIdx {
			if !x[j].IsInt() {
				frac = j
				break
			}
		}
		if frac < 0 {
			s.newIncumbent(x, eobj, nd.pn)
			nd.pn.Leaf, nd.pn.Y = "bound", ratStrs(y)
			if s.opt.NoProof {
				nd.pn.Y = nil
			}
			return nil
		}
		// float said integral, exact says no: branch on the exact value
		return s.branch(nd, frac, x[frac], status, obj)
	}
	j := s.pickBranch(cand)
	v := new(big.Rat).SetFloat64(s.ws.X[j])
	return s.branch(nd, j, v, status, obj)
}

func (s *solver) fractional() []int {
	var out []int
	for _, j := range s.intIdx {
		v := s.ws.X[j]
		if math.Abs(v-math.Round(v)) > 1e-6 {
			out = append(out, j)
		}
	}
	return out
}

func (s *solver) pickBranch(cand []int) int {
	best, bestScore := cand[0], -1.0
	avgUp, avgDn := s.avgPseudo()
	for _, j := range cand {
		v := s.ws.X[j]
		f := v - math.Floor(v)
		score := math.Min(f, 1-f) // most fractional
		if s.opt.Branch == "pseudo" {
			up, dn := avgUp, avgDn
			if s.pcUpN[j] > 0 {
				up = s.pcUp[j] / float64(s.pcUpN[j])
			}
			if s.pcDnN[j] > 0 {
				dn = s.pcDn[j] / float64(s.pcDnN[j])
			}
			if avgUp > 0 || avgDn > 0 {
				score = math.Max(up*(1-f), 1e-6) * math.Max(dn*f, 1e-6)
			}
		}
		if score > bestScore {
			best, bestScore = j, score
		}
	}
	return best
}

func (s *solver) avgPseudo() (float64, float64) {
	var su, sd float64
	var nu, nd int
	for j := 0; j < s.n; j++ {
		su += s.pcUp[j]
		nu += s.pcUpN[j]
		sd += s.pcDn[j]
		nd += s.pcDnN[j]
	}
	a, b := 0.0, 0.0
	if nu > 0 {
		a = su / float64(nu)
	}
	if nd > 0 {
		b = sd / float64(nd)
	}
	return a, b
}

func (s *solver) updatePseudo(nd *node, obj float64) {
	if nd.bvar < 0 || nd.bfrac <= 1e-9 || math.IsInf(nd.pobj, 0) {
		return
	}
	gain := math.Max(obj-nd.pobj, 0) / nd.bfrac
	if nd.bup {
		s.pcUp[nd.bvar] += gain
		s.pcUpN[nd.bvar]++
	} else {
		s.pcDn[nd.bvar] += gain
		s.pcDnN[nd.bvar]++
	}
}

// branch creates the two children of nd on integer variable j at value v.
// The child nearest to v is returned first (plunged into immediately).
func (s *solver) branch(nd *node, j int, v *big.Rat, status []byte, obj float64) []*node {
	fl := floorRat(v)
	vf, _ := v.Float64()
	f := vf - math.Floor(vf)
	nd.pn.Var = new(int)
	*nd.pn.Var = j
	nd.pn.Split = fl.RatString()
	mk := func(up bool) *node {
		box := nd.box.Clone()
		c := &node{box: box, basis: status, lb: obj, depth: nd.depth + 1, bvar: j, bup: up, pobj: obj, pn: &PNode{}}
		if up {
			box.Lo[j] = new(big.Rat).Add(fl, big.NewRat(1, 1))
			c.bfrac = 1 - f
		} else {
			box.Hi[j] = new(big.Rat).Set(fl)
			c.bfrac = f
		}
		s.seq++
		c.seq = s.seq
		return c
	}
	down, up := mk(false), mk(true)
	nd.pn.Down, nd.pn.Up = down.pn, up.pn
	first, second := down, up
	if f > 0.5 {
		first, second = up, down
	}
	return []*node{first, second}
}

func (s *solver) newIncumbent(x []*big.Rat, obj *big.Rat, leaf *PNode) bool {
	if err := exact.CheckPoint(s.m, exact.BoxOf(s.m), x, true); err != nil {
		return false // never accept an unverified incumbent
	}
	if s.incObj != nil && obj.Cmp(s.incObj) >= 0 {
		return false
	}
	s.inc, s.incObj = x, obj
	s.incF = model.Float(obj)
	s.incLeaf = leaf
	s.trace(nil)
	s.logf("  * incumbent %s  (node %d)\n", model.DecStr(s.toOrig(obj)), s.res.Nodes)
	return true
}

// dive is a root diving heuristic: repeatedly fix the least fractional
// integer variable to its nearest integer and re-optimise with the dual simplex.
func (s *solver) dive() {
	w := s.ws.Clone()
	box := exact.BoxOf(s.m)
	save := s.ws
	s.ws = w
	defer func() { s.ws = save }()
	for step := 0; step < 4*len(s.intIdx)+10; step++ {
		cand := s.fractional()
		if len(cand) == 0 {
			x, _, eobj, err := lp.OptimalCert(s.m, box, w.Statuses())
			if err != nil {
				return
			}
			for _, j := range s.intIdx {
				if !x[j].IsInt() {
					return
				}
			}
			if s.newIncumbent(x, eobj, nil) {
				s.res.DiveFound++
			}
			return
		}
		best, bd := cand[0], 2.0
		for _, j := range cand {
			v := w.X[j]
			if d := math.Abs(v - math.Round(v)); d < bd {
				best, bd = j, d
			}
		}
		r := math.Round(w.X[best])
		w.SetBounds(best, r, r)
		if w.Solve(s.cutoff()) != simplex.Optimal {
			return
		}
		box = fixBox(box, best, r)
	}
}

func fixBox(b exact.Box, j int, v float64) exact.Box {
	nb := b.Clone()
	r := new(big.Rat).SetInt64(int64(v))
	nb.Lo[j], nb.Hi[j] = r, new(big.Rat).Set(r)
	return nb
}

func (s *solver) finish() {
	r := s.res
	r.Uncertified = s.unc
	r.Proof.Status = "unknown"
	if s.unbounded {
		r.Status = UnboundedRelaxation
		if !s.m.HasInts() {
			r.Status = Unbounded
		}
		r.Proof.Status = string(r.Status)
		r.Proof.Tree = nil
		if s.rootRay != nil {
			r.Proof.X, r.Proof.Ray = ratStrs(s.rootX0), ratStrs(s.rootRay)
			r.Certified = true
		} else {
			r.Note = "unboundedness could not be certified exactly"
		}
		return
	}
	incomplete := r.Note == "time limit reached" || r.Note == "node limit reached"
	if s.inc != nil {
		r.X = s.inc
		r.Obj = s.toOrig(s.incObj)
		r.Proof.X = ratStrs(s.inc)
		r.Proof.Objective = r.Obj.RatString()
		if s.incLeaf != nil {
			s.incLeaf.Inc = true
		}
	}
	switch {
	case incomplete:
		r.Status = Limit
	case s.unc > 0:
		r.Status = Unknown
		if s.inc != nil {
			r.Status = Limit
		}
	case s.inc != nil:
		r.Status = Optimal
	default:
		r.Status = Infeasible
	}
	r.Proof.Status = string(r.Status)
	if r.Status == Unknown {
		r.Proof.Status = "limit"
	}
	if s.opt.NoProof {
		return
	}
	rep, err := Check(s.m, r.Proof)
	if err != nil {
		r.Note = "proof self-check failed: " + err.Error()
		return
	}
	r.Bound = rep.GlobalBound
	switch r.Status {
	case Optimal, Infeasible:
		r.Certified = rep.Complete
	case Limit:
		r.Certified = true // incumbent and every bound verified; search incomplete
	}
}
