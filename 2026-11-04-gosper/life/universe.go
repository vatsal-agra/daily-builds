// Package life implements Hashlife (Gosper, 1984) for arbitrary two-state
// outer-totalistic ("Life-like") cellular automata, plus the tooling around it.
package life

import (
	"fmt"
	"math"
	"strings"
)

// Rule is a Life-like rule in B/S notation. B0 rules are rejected because an
// empty universe would not stay empty, which Hashlife's infinite-plane model
// cannot represent.
type Rule struct {
	Born    [9]bool
	Survive [9]bool
}

// ParseRule accepts "B3/S23", "b36s23", "S23/B3" and the legacy "23/3" (S/B).
func ParseRule(s string) (Rule, error) {
	var r Rule
	s = strings.ToUpper(strings.TrimSpace(s))
	if s == "" {
		return r, fmt.Errorf("empty rule")
	}
	parts := strings.Split(s, "/")
	if len(parts) == 1 && strings.ContainsAny(s, "BS") {
		// "B36S23" without slash
		i := strings.IndexAny(s[1:], "BS")
		if i >= 0 {
			parts = []string{s[:i+1], s[i+1:]}
		}
	}
	if len(parts) != 2 {
		return r, fmt.Errorf("rule %q: expected B…/S…", s)
	}
	var bs, ss string
	legacy := !strings.ContainsAny(parts[0]+parts[1], "BS")
	if legacy {
		ss, bs = parts[0], parts[1]
	} else {
		for _, p := range parts {
			switch {
			case strings.HasPrefix(p, "B"):
				bs = p[1:]
			case strings.HasPrefix(p, "S"):
				ss = p[1:]
			default:
				return r, fmt.Errorf("rule %q: bad part %q", s, p)
			}
		}
	}
	fill := func(digits string, dst *[9]bool) error {
		for _, c := range digits {
			if c < '0' || c > '8' {
				return fmt.Errorf("rule %q: bad neighbour count %q", s, string(c))
			}
			dst[c-'0'] = true
		}
		return nil
	}
	if err := fill(bs, &r.Born); err != nil {
		return r, err
	}
	if err := fill(ss, &r.Survive); err != nil {
		return r, err
	}
	if r.Born[0] {
		return r, fmt.Errorf("rule %q: B0 rules are not supported (empty space would not stay empty)", s)
	}
	return r, nil
}

// String returns the canonical form, e.g. "B3/S23".
func (r Rule) String() string {
	var b, s strings.Builder
	for i := 0; i < 9; i++ {
		if r.Born[i] {
			b.WriteByte(byte('0' + i))
		}
		if r.Survive[i] {
			s.WriteByte(byte('0' + i))
		}
	}
	return "B" + b.String() + "/S" + s.String()
}

var Life = mustRule("B3/S23")

func mustRule(s string) Rule {
	r, err := ParseRule(s)
	if err != nil {
		panic(err)
	}
	return r
}

// Node is an immutable, hash-consed quadtree square of side 2^level.
type Node struct {
	nw, ne, sw, se *Node
	level          int
	pop            uint64
	res            *Node // centre half after 2^(level-2) generations, memoised
}

type key struct{ a, b, c, d *Node }

type slowKey struct{ n *Node }

// MaxLevel keeps coordinates inside int64 and pop counts meaningful.
const MaxLevel = 62

// MaxListCells bounds how many cells commands will enumerate.
const MaxListCells = 5_000_000

// Universe owns a node table for one rule. Nodes from different universes must
// never be mixed.
type Universe struct {
	Rule  Rule
	table map[key]*Node
	dead  *Node
	alive *Node
	empty []*Node
	slow  map[*Node]*Node // results for the current slow step exponent
	slowJ int
	// Budget is the hard cap on interned nodes during one hop; exceeding it
	// aborts the hop with ErrBudget instead of exhausting memory.
	Budget int
	// Stats
	Hits, Misses uint64
}

// ErrBudget is returned when a hop would need more nodes than Universe.Budget:
// the pattern is too irregular for Hashlife at that step size.
var ErrBudget = fmt.Errorf("node budget exceeded: the pattern is too irregular for Hashlife at this step size (try smaller steps)")

type budgetPanic struct{}

func NewUniverse(r Rule) *Universe {
	u := &Universe{Rule: r, table: make(map[key]*Node, 1<<12), slow: map[*Node]*Node{}, slowJ: -1, Budget: 6_000_000}
	u.dead = &Node{level: 0}
	u.alive = &Node{level: 0, pop: 1}
	u.empty = []*Node{u.dead}
	return u
}

// Size is the number of interned nodes.
func (u *Universe) Size() int { return len(u.table) }

func satAdd(a, b uint64) uint64 {
	c := a + b
	if c < a {
		return math.MaxUint64
	}
	return c
}

func (u *Universe) join(nw, ne, sw, se *Node) *Node {
	k := key{nw, ne, sw, se}
	if n, ok := u.table[k]; ok {
		return n
	}
	if u.Budget > 0 && len(u.table) >= u.Budget {
		panic(budgetPanic{})
	}
	n := &Node{nw: nw, ne: ne, sw: sw, se: se, level: nw.level + 1}
	n.pop = satAdd(satAdd(nw.pop, ne.pop), satAdd(sw.pop, se.pop))
	u.table[k] = n
	return n
}

// Empty returns the canonical all-dead node of the given level.
func (u *Universe) Empty(level int) *Node {
	for len(u.empty) <= level {
		e := u.empty[len(u.empty)-1]
		u.empty = append(u.empty, u.join(e, e, e, e))
	}
	return u.empty[level]
}

func (u *Universe) cell(alive bool) *Node {
	if alive {
		return u.alive
	}
	return u.dead
}

// base computes the centre 2x2 of a 4x4 (level-2) node after one generation.
func (u *Universe) base(n *Node) *Node {
	var g [4][4]int
	g[0][0], g[0][1], g[0][2], g[0][3] = int(n.nw.nw.pop), int(n.nw.ne.pop), int(n.ne.nw.pop), int(n.ne.ne.pop)
	g[1][0], g[1][1], g[1][2], g[1][3] = int(n.nw.sw.pop), int(n.nw.se.pop), int(n.ne.sw.pop), int(n.ne.se.pop)
	g[2][0], g[2][1], g[2][2], g[2][3] = int(n.sw.nw.pop), int(n.sw.ne.pop), int(n.se.nw.pop), int(n.se.ne.pop)
	g[3][0], g[3][1], g[3][2], g[3][3] = int(n.sw.sw.pop), int(n.sw.se.pop), int(n.se.sw.pop), int(n.se.se.pop)
	next := func(r, c int) *Node {
		cnt := 0
		for dr := -1; dr <= 1; dr++ {
			for dc := -1; dc <= 1; dc++ {
				if dr != 0 || dc != 0 {
					cnt += g[r+dr][c+dc]
				}
			}
		}
		if g[r][c] == 1 {
			return u.cell(u.Rule.Survive[cnt])
		}
		return u.cell(u.Rule.Born[cnt])
	}
	return u.join(next(1, 1), next(1, 2), next(2, 1), next(2, 2))
}

func (u *Universe) centre(m *Node) *Node {
	return u.join(m.nw.se, m.ne.sw, m.sw.ne, m.se.nw)
}

// result returns the centre half of n (level k) after 2^j generations, j <= k-2.
func (u *Universe) result(n *Node, j int) *Node {
	k := n.level
	if n.pop == 0 {
		return u.Empty(k - 1)
	}
	full := j == k-2
	if full {
		if n.res != nil {
			u.Hits++
			return n.res
		}
	} else if r, ok := u.slow[n]; ok {
		u.Hits++
		return r
	}
	u.Misses++
	var out *Node
	if k == 2 {
		out = u.base(n)
	} else {
		a, b, c, d := n.nw, n.ne, n.sw, n.se
		n00, n02, n20, n22 := a, b, c, d
		n01 := u.join(a.ne, b.nw, a.se, b.sw)
		n10 := u.join(a.sw, a.se, c.nw, c.ne)
		n11 := u.join(a.se, b.sw, c.ne, d.nw)
		n12 := u.join(b.sw, b.se, d.nw, d.ne)
		n21 := u.join(c.ne, d.nw, c.se, d.sw)
		var r00, r01, r02, r10, r11, r12, r20, r21, r22 *Node
		if full {
			r00, r01, r02 = u.result(n00, j-1), u.result(n01, j-1), u.result(n02, j-1)
			r10, r11, r12 = u.result(n10, j-1), u.result(n11, j-1), u.result(n12, j-1)
			r20, r21, r22 = u.result(n20, j-1), u.result(n21, j-1), u.result(n22, j-1)
		} else {
			r00, r01, r02 = u.centre(n00), u.centre(n01), u.centre(n02)
			r10, r11, r12 = u.centre(n10), u.centre(n11), u.centre(n12)
			r20, r21, r22 = u.centre(n20), u.centre(n21), u.centre(n22)
		}
		q00 := u.join(r00, r01, r10, r11)
		q01 := u.join(r01, r02, r11, r12)
		q10 := u.join(r10, r11, r20, r21)
		q11 := u.join(r11, r12, r21, r22)
		jj := j
		if full {
			jj = j - 1
		}
		out = u.join(u.result(q00, jj), u.result(q01, jj), u.result(q10, jj), u.result(q11, jj))
	}
	if full {
		n.res = out
	} else {
		u.slow[n] = out
	}
	return out
}

// expand wraps n in a ring of dead cells (level+1, same centre).
func (u *Universe) expand(n *Node) *Node {
	e := u.Empty(n.level - 1)
	return u.join(u.join(e, e, e, n.nw), u.join(e, e, n.ne, e), u.join(e, n.sw, e, e), u.join(n.se, e, e, e))
}

// fitsCentre reports whether all live cells lie in the central half.
func (u *Universe) fitsCentre(n *Node) bool {
	if n.level < 3 {
		return false
	}
	return n.nw.nw.pop+n.nw.ne.pop+n.nw.sw.pop == 0 &&
		n.ne.nw.pop+n.ne.ne.pop+n.ne.se.pop == 0 &&
		n.sw.nw.pop+n.sw.sw.pop+n.sw.se.pop == 0 &&
		n.se.ne.pop+n.se.sw.pop+n.se.se.pop == 0
}

// shrink removes empty outer rings while keeping level >= 3.
func (u *Universe) shrink(n *Node) *Node {
	for n.level > 3 && u.fitsCentre(n) {
		n = u.centre(n)
	}
	return n
}

// Advance returns root after exactly 2^j generations.
func (u *Universe) Advance(root *Node, j int) (out *Node, err error) {
	defer func() {
		if r := recover(); r != nil {
			if _, ok := r.(budgetPanic); !ok {
				panic(r)
			}
			out, err = nil, ErrBudget
		}
	}()
	if j < 0 || j > MaxLevel-5 {
		return nil, fmt.Errorf("step exponent %d out of range [0,%d]", j, MaxLevel-5)
	}
	for root.level < j+3 || !u.fitsCentre(root) {
		if root.level >= MaxLevel-1 {
			return nil, fmt.Errorf("universe too large (level %d): pattern outgrew 2^%d cells", root.level, MaxLevel)
		}
		root = u.expand(root)
	}
	root = u.expand(root)
	if j != u.slowJ {
		u.slow = map[*Node]*Node{}
		u.slowJ = j
	}
	return u.shrink(u.result(root, j)), nil
}

// Compact discards the whole node table and memo caches, re-interning only the
// nodes reachable from roots. This is Hashlife's garbage collector.
func (u *Universe) Compact(roots ...*Node) {
	u.table = make(map[key]*Node, 1<<12)
	u.slow = map[*Node]*Node{}
	u.slowJ = -1
	keep := u.empty
	u.empty = []*Node{u.dead}
	seen := map[*Node]bool{}
	var walk func(n *Node)
	walk = func(n *Node) {
		if n.level == 0 || seen[n] {
			return
		}
		seen[n] = true
		walk(n.nw)
		walk(n.ne)
		walk(n.sw)
		walk(n.se)
		n.res = nil
		u.table[key{n.nw, n.ne, n.sw, n.se}] = n
	}
	for _, r := range roots {
		walk(r)
	}
	// empty[k] nodes must stay canonical: re-derive them through join, which
	// reuses any already-interned identical node.
	for k := 1; k < len(keep); k++ {
		e := u.empty[k-1]
		old := keep[k]
		old.res = nil
		kk := key{e, e, e, e}
		if ex, ok := u.table[kk]; ok {
			u.empty = append(u.empty, ex)
		} else {
			u.table[kk] = old
			u.empty = append(u.empty, old)
		}
	}
}

// ---------------------------------------------------------------- Sim

// Point is a cell coordinate; y grows downwards (screen convention).
type Point struct{ X, Y int64 }

// Sim is a universe plus a current root and generation counter.
type Sim struct {
	U    *Universe
	Root *Node
	Gen  uint64
	// MaxNodes triggers compaction between sub-steps (default 3M).
	MaxNodes int
}

func NewSim(r Rule) *Sim {
	u := NewUniverse(r)
	return &Sim{U: u, Root: u.Empty(3), MaxNodes: 3_000_000}
}

func levelFor(pts []Point) int {
	k := 3
	for _, p := range pts {
		for k < MaxLevel-6 {
			h := int64(1) << uint(k-1)
			if p.X >= -h && p.X < h && p.Y >= -h && p.Y < h {
				break
			}
			k++
		}
	}
	return k
}

func (u *Universe) build(pts []Point, level int, x0, y0 int64) *Node {
	if len(pts) == 0 {
		return u.Empty(level)
	}
	if level == 0 {
		return u.alive
	}
	h := int64(1) << uint(level-1)
	var quad [4][]Point
	for _, p := range pts {
		i := 0
		if p.X >= x0+h {
			i |= 1
		}
		if p.Y >= y0+h {
			i |= 2
		}
		quad[i] = append(quad[i], p)
	}
	return u.join(u.build(quad[0], level-1, x0, y0), u.build(quad[1], level-1, x0+h, y0),
		u.build(quad[2], level-1, x0, y0+h), u.build(quad[3], level-1, x0+h, y0+h))
}

// SetCells replaces the universe contents (generation resets to 0). With
// centre the pattern's bounding box is moved to straddle the origin.
func (s *Sim) SetCells(pts []Point, centre bool) error {
	pts = dedupe(pts)
	if centre && len(pts) > 0 {
		x0, y0, x1, y1 := boundsOf(pts)
		dx, dy := (x0+x1)/2, (y0+y1)/2
		for i := range pts {
			pts[i].X -= dx
			pts[i].Y -= dy
		}
	}
	const lim = int64(1) << 50
	for _, p := range pts {
		if p.X < -lim || p.X >= lim || p.Y < -lim || p.Y >= lim {
			return fmt.Errorf("cell (%d,%d) is outside the supported range ±2^50", p.X, p.Y)
		}
	}
	k := levelFor(pts)
	s.Root = s.U.build(pts, k, -(int64(1) << uint(k-1)), -(int64(1) << uint(k-1)))
	s.Gen = 0
	return nil
}

func dedupe(pts []Point) []Point {
	seen := make(map[Point]struct{}, len(pts))
	out := make([]Point, 0, len(pts))
	for _, p := range pts {
		if _, ok := seen[p]; !ok {
			seen[p] = struct{}{}
			out = append(out, p)
		}
	}
	return out
}

func boundsOf(pts []Point) (x0, y0, x1, y1 int64) {
	x0, y0, x1, y1 = pts[0].X, pts[0].Y, pts[0].X, pts[0].Y
	for _, p := range pts {
		x0, x1 = min(x0, p.X), max(x1, p.X)
		y0, y1 = min(y0, p.Y), max(y1, p.Y)
	}
	return
}

// Population is the number of live cells (saturating at MaxUint64).
func (s *Sim) Population() uint64 { return s.Root.pop }

func (s *Sim) origin() int64 { return -(int64(1) << uint(s.Root.level-1)) }

// Cells lists live cells; ok is false if more than limit cells exist (limit<=0: no limit).
func (s *Sim) Cells(limit int) (pts []Point, ok bool) {
	if limit > 0 && s.Root.pop > uint64(limit) {
		return nil, false
	}
	var walk func(n *Node, x, y int64)
	walk = func(n *Node, x, y int64) {
		if n.pop == 0 {
			return
		}
		if n.level == 0 {
			pts = append(pts, Point{x, y})
			return
		}
		h := int64(1) << uint(n.level-1)
		walk(n.nw, x, y)
		walk(n.ne, x+h, y)
		walk(n.sw, x, y+h)
		walk(n.se, x+h, y+h)
	}
	o := s.origin()
	walk(s.Root, o, o)
	return pts, true
}

type box struct{ x0, y0, x1, y1 int64 } // relative to the node's top-left; valid if pop>0

// BBox returns the exact bounding box of live cells. It is memoised per node,
// so it is linear in the number of distinct nodes, not in the pattern area.
func (s *Sim) BBox() (x0, y0, x1, y1 int64, ok bool) {
	if s.Root.pop == 0 {
		return 0, 0, 0, 0, false
	}
	memo := map[*Node]box{}
	var rec func(n *Node) box
	rec = func(n *Node) box {
		if n.level == 0 {
			return box{0, 0, 0, 0}
		}
		if b, ok := memo[n]; ok {
			return b
		}
		h := int64(1) << uint(n.level-1)
		b := box{math.MaxInt64, math.MaxInt64, math.MinInt64, math.MinInt64}
		for i, c := range [4]*Node{n.nw, n.ne, n.sw, n.se} {
			if c.pop == 0 {
				continue
			}
			cb := rec(c)
			ox, oy := int64(i&1)*h, int64(i>>1)*h
			b.x0, b.y0 = min(b.x0, cb.x0+ox), min(b.y0, cb.y0+oy)
			b.x1, b.y1 = max(b.x1, cb.x1+ox), max(b.y1, cb.y1+oy)
		}
		memo[n] = b
		return b
	}
	b := rec(s.Root)
	o := s.origin()
	return b.x0 + o, b.y0 + o, b.x1 + o, b.y1 + o, true
}

// Get reports whether the cell at (x,y) is alive.
func (s *Sim) Get(x, y int64) bool {
	o := s.origin()
	if x < o || y < o || x >= -o || y >= -o {
		return false
	}
	x -= o
	y -= o // now relative to the root's top-left corner
	n := s.Root
	for n.level > 0 {
		if n.pop == 0 {
			return false
		}
		h := int64(1) << uint(n.level-1)
		right, down := x >= h, y >= h
		if right {
			x -= h
		}
		if down {
			y -= h
		}
		switch {
		case !right && !down:
			n = n.nw
		case right && !down:
			n = n.ne
		case !right && down:
			n = n.sw
		default:
			n = n.se
		}
	}
	return n.pop == 1
}

// Step advances exactly n generations (any n, via binary decomposition into
// power-of-two hops), compacting the node table when it grows past MaxNodes.
func (s *Sim) Step(n uint64) error {
	for j := 0; n != 0; j, n = j+1, n>>1 {
		if n&1 == 0 {
			continue
		}
		if err := s.StepPow(j); err != nil {
			return err
		}
	}
	return nil
}

// StepPow advances exactly 2^j generations in a single Hashlife hop.
func (s *Sim) StepPow(j int) error {
	r, err := s.U.Advance(s.Root, j)
	if err != nil {
		if err == ErrBudget {
			s.U.Compact(s.Root) // drop the half-built garbage; Root is untouched
		}
		return err
	}
	s.Root = r
	s.Gen += 1 << uint(j)
	if s.MaxNodes > 0 && s.U.Size() > s.MaxNodes {
		s.U.Compact(s.Root)
	}
	return nil
}

// Level is the quadtree level (side 2^Level) of the node.
func (n *Node) Level() int { return n.level }
