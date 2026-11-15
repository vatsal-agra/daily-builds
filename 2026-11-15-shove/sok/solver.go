package sok

import (
	"container/heap"
	"errors"
	"time"
)

var (
	// ErrUnsolvable means the whole reachable state space was exhausted.
	ErrUnsolvable = errors.New("level is unsolvable (search space exhausted)")
	// ErrBudget means a node or time budget ran out before an answer was found.
	ErrBudget = errors.New("search budget exhausted before a solution was found")
)

// Options bounds a search. Zero values mean "unlimited".
type Options struct {
	MaxNodes     int
	MaxGenerated int // cap on stored states (memory guard); 0 = default 6,000,000
	Timeout      time.Duration
	NoFreeze     bool // disable freeze-deadlock pruning (for differential testing)
	NoMatching   bool // use the weaker sum-of-nearest-goal heuristic (for ablation)
}

// Solution is a proven push-optimal answer.
type Solution struct {
	Moves     string // LURD, uppercase = push
	Pushes    int
	WalkMoves int // total moves (pushes + walking)
	Expanded  int
	Generated int
	Elapsed   time.Duration
}

type node struct {
	boxes  []uint16
	player int32
	parent int32
	from   int32 // box cell before the push that produced this node
	dir    int8
	g      int32
	moves  int32
}

type entry struct {
	id   int32
	f, h int32
	g    int32
}
type heapT []entry

func (h heapT) Len() int { return len(h) }
func (h heapT) Less(i, j int) bool {
	if h[i].f != h[j].f {
		return h[i].f < h[j].f
	}
	if h[i].h != h[j].h {
		return h[i].h < h[j].h
	}
	return h[i].g > h[j].g
}
func (h heapT) Swap(i, j int) { h[i], h[j] = h[j], h[i] }
func (h *heapT) Push(x any)   { *h = append(*h, x.(entry)) }
func (h *heapT) Pop() any {
	o := *h
	n := len(o)
	x := o[n-1]
	*h = o[:n-1]
	return x
}

// solver holds scratch buffers so the hot loop allocates little.
type solver struct {
	lv     *Level
	an     *Analysis
	opt    Options
	boxAt  []bool
	seen   []int32 // BFS stamp
	stamp  int32
	dist   []int32
	queue  []int
	hungC  [][]int
	hungU  []int
	hungV  []int
	hungP  []int
	hungW  []int
	hungMn []int
}

// Solve finds a push-optimal solution (ties broken toward fewer walking moves
// only incidentally; the pushes count is provably minimal).
func Solve(lv *Level, opt Options) (*Solution, error) {
	start := time.Now()
	s := &solver{lv: lv, an: Analyze(lv), opt: opt}
	n := lv.W * lv.H
	s.boxAt = make([]bool, n)
	s.seen = make([]int32, n)
	s.dist = make([]int32, n)
	nb := len(lv.Boxes)
	s.hungC = make([][]int, nb+1)
	for i := range s.hungC {
		s.hungC[i] = make([]int, nb+1)
	}
	s.hungU, s.hungV = make([]int, nb+1), make([]int, nb+1)
	s.hungP, s.hungW = make([]int, nb+1), make([]int, nb+1)
	s.hungMn = make([]int, nb+1)

	root := &node{boxes: make([]uint16, nb), player: int32(lv.Player), parent: -1}
	for i, b := range lv.Boxes {
		root.boxes[i] = uint16(b)
	}
	h0 := s.heuristic(root.boxes)
	if h0 >= inf {
		return nil, ErrUnsolvable
	}
	nodes := []*node{root}
	best := map[string]int32{}
	open := &heapT{}
	push := func(id int32, h int32) {
		heap.Push(open, entry{id: id, f: nodes[id].g + h, h: h, g: nodes[id].g})
	}
	push(0, int32(h0))
	best[s.key(root.boxes, s.canon(root.boxes, int(root.player)))] = 0
	expanded := 0
	genCap := opt.MaxGenerated
	if genCap <= 0 {
		genCap = 6_000_000
	}
	var sol []int32

	for open.Len() > 0 {
		e := heap.Pop(open).(entry)
		cur := nodes[e.id]
		k := s.key(cur.boxes, s.canon(cur.boxes, int(cur.player)))
		if g, ok := best[k]; ok && g < cur.g {
			continue // stale
		}
		if e.h == 0 {
			// h==0 <=> every box on a goal.
			for id := e.id; id >= 0; id = nodes[id].parent {
				sol = append(sol, id)
			}
			break
		}
		expanded++
		if len(nodes) > genCap {
			return nil, ErrBudget
		}
		if opt.MaxNodes > 0 && expanded > opt.MaxNodes {
			return nil, ErrBudget
		}
		if opt.Timeout > 0 && expanded&255 == 0 && time.Since(start) > opt.Timeout {
			return nil, ErrBudget
		}
		s.setBoxes(cur.boxes, true)
		s.bfs(int(cur.player))
		stamp := s.stamp
		type succ struct {
			boxes  []uint16
			from   int
			dir    int
			moves  int32
			canonK string
			h      int
		}
		var succs []succ
		for bi, b16 := range cur.boxes {
			b := int(b16)
			for d := 0; d < 4; d++ {
				dl := delta(d, lv.W)
				pl, tg := b-dl, b+dl
				if s.seen[pl] != stamp || lv.Wall[tg] || s.boxAt[tg] || s.an.Dead[tg] {
					continue
				}
				nbx := make([]uint16, nb)
				copy(nbx, cur.boxes)
				nbx[bi] = uint16(tg)
				// keep sorted
				for j := bi; j+1 < nb && nbx[j] > nbx[j+1]; j++ {
					nbx[j], nbx[j+1] = nbx[j+1], nbx[j]
				}
				for j := bi; j > 0 && nbx[j] < nbx[j-1]; j-- {
					nbx[j], nbx[j-1] = nbx[j-1], nbx[j]
				}
				succs = append(succs, succ{boxes: nbx, from: b, dir: d, moves: s.dist[pl] + 1, h: tg})
			}
		}
		walk := make([]int32, 0, len(succs))
		for _, sc := range succs {
			walk = append(walk, sc.moves)
		}
		s.setBoxes(cur.boxes, false)
		for i, sc := range succs {
			// Evaluate the successor.
			s.setBoxes(sc.boxes, true)
			dead := !opt.NoFreeze && s.an.FreezeDeadlock(s.boxAt, sc.h)
			s.setBoxes(sc.boxes, false)
			if dead {
				continue
			}
			h := s.heuristic(sc.boxes)
			if h >= inf {
				continue
			}
			pc := s.canon(sc.boxes, sc.from)
			k2 := s.key(sc.boxes, pc)
			g2 := cur.g + 1
			if g, ok := best[k2]; ok && g <= g2 {
				continue
			}
			best[k2] = g2
			nodes = append(nodes, &node{boxes: sc.boxes, player: int32(sc.from), parent: e.id,
				from: int32(sc.from), dir: int8(sc.dir), g: g2, moves: cur.moves + walk[i]})
			push(int32(len(nodes)-1), int32(h))
		}
	}
	if sol == nil {
		return nil, ErrUnsolvable
	}
	// Reconstruct move string by replaying with real BFS walking paths.
	var out []byte
	for i := len(sol) - 1; i >= 1; i-- {
		parent, child := nodes[sol[i]], nodes[sol[i-1]]
		s.setBoxes(parent.boxes, true)
		out = append(out, s.walkPath(int(parent.player), int(child.from)-delta(int(child.dir), lv.W))...)
		s.setBoxes(parent.boxes, false)
		out = append(out, dirName[child.dir]-32)
	}
	str := string(out)
	return &Solution{Moves: str, Pushes: len(sol) - 1, WalkMoves: len(str), Expanded: expanded,
		Generated: len(nodes), Elapsed: time.Since(start)}, nil
}

func (s *solver) setBoxes(bx []uint16, v bool) {
	for _, b := range bx {
		s.boxAt[b] = v
	}
}

// bfs floods from p avoiding walls and boxes (s.boxAt must be set), filling s.dist
// and stamping s.seen with a fresh stamp.
func (s *solver) bfs(p int) {
	s.stamp++
	s.queue = append(s.queue[:0], p)
	s.seen[p] = s.stamp
	s.dist[p] = 0
	for h := 0; h < len(s.queue); h++ {
		c := s.queue[h]
		for d := 0; d < 4; d++ {
			n := c + delta(d, s.lv.W)
			if s.seen[n] == s.stamp || s.lv.Wall[n] || s.boxAt[n] {
				continue
			}
			s.seen[n] = s.stamp
			s.dist[n] = s.dist[c] + 1
			s.queue = append(s.queue, n)
		}
	}
}

// canon returns the smallest cell index reachable by the player from p.
func (s *solver) canon(bx []uint16, p int) int {
	s.setBoxes(bx, true)
	s.bfs(p)
	m := p
	for _, c := range s.queue {
		if c < m {
			m = c
		}
	}
	s.setBoxes(bx, false)
	return m
}

func (s *solver) key(bx []uint16, pc int) string {
	b := make([]byte, 0, 2*len(bx)+2)
	for _, x := range bx {
		b = append(b, byte(x), byte(x>>8))
	}
	b = append(b, byte(pc), byte(pc>>8))
	return string(b)
}

// walkPath returns lowercase moves for the shortest walk from a to b with s.boxAt as obstacles.
func (s *solver) walkPath(a, b int) []byte {
	if a == b {
		return nil
	}
	s.bfs(a)
	var rev []byte
	c := b
	for c != a {
		moved := false
		for d := 0; d < 4; d++ {
			n := c - delta(d, s.lv.W) // predecessor reached by moving in direction d
			if s.seen[n] == s.stamp && s.dist[n] == s.dist[c]-1 && !s.lv.Wall[n] && !s.boxAt[n] {
				rev = append(rev, dirName[d])
				c = n
				moved = true
				break
			}
		}
		if !moved {
			panic("walkPath: unreachable cell") // cannot happen: callers pass reachable targets
		}
	}
	for i, j := 0, len(rev)-1; i < j; i, j = i+1, j-1 {
		rev[i], rev[j] = rev[j], rev[i]
	}
	return rev
}

// heuristic is an admissible lower bound on remaining pushes: the min-cost
// perfect matching between boxes and goals under single-box push distances.
func (s *solver) heuristic(bx []uint16) int {
	n := len(bx)
	if s.opt.NoMatching {
		sum := 0
		for _, b := range bx {
			m := inf
			for gi := range s.an.Goals {
				if d := int(s.an.PushDist[gi][b]); d < m {
					m = d
				}
			}
			if m >= inf {
				return inf
			}
			sum += m
		}
		return sum
	}
	const big = 1 << 20
	for i := 0; i < n; i++ {
		for j := 0; j < n; j++ {
			d := int(s.an.PushDist[j][bx[i]])
			if d >= inf {
				d = big
			}
			s.hungC[i+1][j+1] = d
		}
	}
	c := s.hungassign(n)
	if c >= big {
		return inf
	}
	return c
}

// hungassign is the O(n^3) Hungarian algorithm on s.hungC[1..n][1..n].
func (s *solver) hungassign(n int) int {
	u, v, p, way, minv := s.hungU, s.hungV, s.hungP, s.hungW, s.hungMn
	for i := 0; i <= n; i++ {
		u[i], v[i], p[i], way[i] = 0, 0, 0, 0
	}
	used := make([]bool, n+1)
	for i := 1; i <= n; i++ {
		p[0] = i
		j0 := 0
		for j := 0; j <= n; j++ {
			minv[j] = inf * 4
			used[j] = false
		}
		for {
			used[j0] = true
			i0, delta, j1 := p[j0], inf*4, 0
			for j := 1; j <= n; j++ {
				if used[j] {
					continue
				}
				cur := s.hungC[i0][j] - u[i0] - v[j]
				if cur < minv[j] {
					minv[j], way[j] = cur, j0
				}
				if minv[j] < delta {
					delta, j1 = minv[j], j
				}
			}
			for j := 0; j <= n; j++ {
				if used[j] {
					u[p[j]] += delta
					v[j] -= delta
				} else {
					minv[j] -= delta
				}
			}
			j0 = j1
			if p[j0] == 0 {
				break
			}
		}
		for {
			j1 := way[j0]
			p[j0] = p[j1]
			j0 = j1
			if j0 == 0 {
				break
			}
		}
	}
	total := 0
	for j := 1; j <= n; j++ {
		total += s.hungC[p[j]][j]
	}
	return total
}
