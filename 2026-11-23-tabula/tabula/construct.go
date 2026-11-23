package tabula

import (
	"fmt"
	"math/rand"
	"sort"
	"time"
)

// ConstructResult is the outcome of the feasibility search.
type ConstructResult struct {
	A        *Assignment
	Nodes    int
	Restarts int
	// Hardest lists events that most often hit a dead end (empty domain), for diagnostics.
	Hardest []string
	Reason  string
}

type construct struct {
	in    *Instance
	st    *State
	rng   *rand.Rand
	dom   [][]int // dom[e][d] = number of feasible (period,room) pairs on day d
	total []int
	fails []int
	nodes int
	limit int
	dl    time.Time
}

func (c *construct) recomputeDay(e, d int) {
	in := c.in
	ev := &in.Events[e]
	n := 0
	for _, s := range ev.Starts {
		if s/in.N != d {
			continue
		}
		for _, r := range ev.Rooms {
			if c.st.CanPlace(e, s, r) {
				n++
			}
		}
	}
	c.total[e] += n - c.dom[e][d]
	c.dom[e][d] = n
}

// Construct finds any hard-feasible timetable (all events placed) using
// MRV backtracking with forward checking, restarting with growing node limits.
// If prev is non-nil, its placements are tried first (used for re-solving).
func (in *Instance) Construct(seed int64, budget time.Duration, prev *Assignment) *ConstructResult {
	rng := rand.New(rand.NewSource(seed))
	deadline := time.Now().Add(budget)
	res := &ConstructResult{}
	fails := make([]int, len(in.Events))
	limit := 400
	for restart := 0; ; restart++ {
		c := &construct{in: in, st: NewState(in), rng: rng, limit: limit, dl: deadline, fails: fails}
		c.dom = make([][]int, len(in.Events))
		c.total = make([]int, len(in.Events))
		for e := range c.dom {
			c.dom[e] = make([]int, in.D)
			for d := 0; d < in.D; d++ {
				c.recomputeDay(e, d)
			}
		}
		var usePrev *Assignment
		if restart%2 == 0 {
			usePrev = prev
		}
		ok := c.search(usePrev)
		res.Nodes += c.nodes
		res.Restarts = restart
		if ok {
			res.A = c.st.A.Clone()
			return res
		}
		if time.Now().After(deadline) {
			break
		}
		limit = limit * 3 / 2
	}
	type kv struct {
		n int
		s string
	}
	var kvs []kv
	for e, n := range fails {
		if n > 0 {
			kvs = append(kvs, kv{n, in.Events[e].Name})
		}
	}
	sort.Slice(kvs, func(i, j int) bool { return kvs[i].n > kvs[j].n })
	for i := 0; i < len(kvs) && i < 5; i++ {
		res.Hardest = append(res.Hardest, fmt.Sprintf("%s (%d dead ends)", kvs[i].s, kvs[i].n))
	}
	res.Reason = "no feasible timetable found within the time budget"
	return res
}

func (c *construct) search(prev *Assignment) bool {
	in, st := c.in, c.st
	if st.placed == len(in.Events) {
		return true
	}
	if c.nodes >= c.limit || (c.nodes&63 == 0 && time.Now().After(c.dl)) {
		return false
	}
	c.nodes++
	// MRV: smallest total domain; ties broken randomly, then by longer/more constrained events.
	best, bestN, ties := -1, 1<<30, 0
	for e := range in.Events {
		if st.A.Slot[e] >= 0 {
			continue
		}
		n := c.total[e]
		if n == 0 {
			c.fails[e]++
			return false
		}
		if n < bestN {
			best, bestN, ties = e, n, 1
		} else if n == bestN {
			ties++
			if c.rng.Intn(ties) == 0 {
				best = e
			}
		}
	}
	ev := &in.Events[best]
	type cand struct{ s, r int }
	var cands []cand
	for _, s := range ev.Starts {
		for _, r := range ev.Rooms {
			if st.CanPlace(best, s, r) {
				cands = append(cands, cand{s, r})
			}
		}
	}
	c.rng.Shuffle(len(cands), func(i, j int) { cands[i], cands[j] = cands[j], cands[i] })
	if prev != nil && prev.Slot[best] >= 0 { // try the previous placement first
		for i, cd := range cands {
			if cd.s == prev.Slot[best] && cd.r == prev.Room[best] {
				cands[0], cands[i] = cands[i], cands[0]
				break
			}
		}
	}
	for _, cd := range cands {
		d := cd.s / in.N
		// snapshot day-d domains of all unplaced events (cheap undo)
		saved := make([]int, len(in.Events))
		for e := range in.Events {
			saved[e] = c.dom[e][d]
		}
		st.Place(best, cd.s, cd.r)
		dead := false
		for e := range in.Events {
			if st.A.Slot[e] >= 0 {
				continue
			}
			c.recomputeDay(e, d)
			if c.total[e] == 0 {
				c.fails[e]++
				dead = true
				break
			}
		}
		if !dead && c.search(prev) {
			return true
		}
		st.Unplace(best)
		for e := range in.Events {
			if st.A.Slot[e] >= 0 && e != best {
				continue
			}
			c.total[e] += saved[e] - c.dom[e][d]
			c.dom[e][d] = saved[e]
		}
		if c.nodes >= c.limit || time.Now().After(c.dl) {
			return false
		}
	}
	return false
}
