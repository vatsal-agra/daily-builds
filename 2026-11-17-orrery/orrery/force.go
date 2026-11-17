package orrery

import "math"

// Accel computes accelerations for the given positions into out.
// With Theta == 0 it is exact pairwise summation (symmetric, so Newton's third
// law holds to rounding); otherwise a Barnes–Hut octree is used.
func (s *System) Accel(pos []Vec3, out []Vec3) {
	s.Evals++
	if s.Theta > 0 && len(pos) > 8 {
		s.accelTree(pos, out)
		return
	}
	s.accelDirect(pos, out)
}

func (s *System) accelDirect(pos []Vec3, out []Vec3) {
	n := len(pos)
	for i := range out[:n] {
		out[i] = Vec3{}
	}
	e2 := s.Eps * s.Eps
	for i := 0; i < n; i++ {
		for j := i + 1; j < n; j++ {
			dx := pos[j].X - pos[i].X
			dy := pos[j].Y - pos[i].Y
			dz := pos[j].Z - pos[i].Z
			r2 := dx*dx + dy*dy + dz*dz + e2
			inv := 1 / (r2 * math.Sqrt(r2))
			fi := s.G * s.Bodies[j].M * inv
			fj := s.G * s.Bodies[i].M * inv
			out[i].X += dx * fi
			out[i].Y += dy * fi
			out[i].Z += dz * fi
			out[j].X -= dx * fj
			out[j].Y -= dy * fj
			out[j].Z -= dz * fj
		}
	}
}

// ---------------------------------------------------------------- Barnes–Hut

// node is one octree cell. Leaves hold a singly linked list of bodies
// (first/next) so that coincident bodies beyond maxDepth need no allocation.
type node struct {
	cx, cy, cz       float64 // cell centre
	half             float64 // half-width
	size2            float64 // (2*half)², cached for the opening test
	mass             float64
	comx, comy, comz float64
	child            [8]int32 // 0 = none (index 0 is the root and never a child)
	first            int32    // first body of a leaf, -1 if none
	internal         bool
}

type tree struct {
	nodes []node
	next  []int32 // next[b] = next body in the same leaf, -1 at end
	mass  []float64
	pos   []Vec3
}

const maxDepth = 60

func buildTree(pos []Vec3, mass []float64) *tree {
	t := &tree{mass: mass, pos: pos, nodes: make([]node, 0, 2*len(pos)+1), next: make([]int32, len(pos))}
	lo, hi := pos[0], pos[0]
	for _, p := range pos {
		lo = Vec3{math.Min(lo.X, p.X), math.Min(lo.Y, p.Y), math.Min(lo.Z, p.Z)}
		hi = Vec3{math.Max(hi.X, p.X), math.Max(hi.Y, p.Y), math.Max(hi.Z, p.Z)}
	}
	half := math.Max(hi.X-lo.X, math.Max(hi.Y-lo.Y, hi.Z-lo.Z))/2*1.000001 + 1e-300
	t.nodes = append(t.nodes, node{cx: (lo.X + hi.X) / 2, cy: (lo.Y + hi.Y) / 2, cz: (lo.Z + hi.Z) / 2, half: half, size2: 4 * half * half, first: -1})
	for i := range pos {
		t.insert(0, int32(i), 0)
	}
	t.summarize(0)
	return t
}

func octant(n *node, p Vec3) int {
	o := 0
	if p.X >= n.cx {
		o |= 1
	}
	if p.Y >= n.cy {
		o |= 2
	}
	if p.Z >= n.cz {
		o |= 4
	}
	return o
}

func (t *tree) newChild(parent int32, oct int) int32 {
	p := &t.nodes[parent]
	h := p.half / 2
	c := node{cx: p.cx - h, cy: p.cy - h, cz: p.cz - h, half: h, size2: p.size2 / 4, first: -1}
	if oct&1 != 0 {
		c.cx = p.cx + h
	}
	if oct&2 != 0 {
		c.cy = p.cy + h
	}
	if oct&4 != 0 {
		c.cz = p.cz + h
	}
	t.nodes = append(t.nodes, c)
	idx := int32(len(t.nodes) - 1)
	t.nodes[parent].child[oct] = idx
	return idx
}

func (t *tree) insert(ni int32, b int32, depth int) {
	n := &t.nodes[ni]
	if !n.internal {
		if n.first < 0 || depth >= maxDepth {
			t.next[b] = n.first
			n.first = b
			return
		}
		// split a leaf: push its bodies down one level
		old := n.first
		n.first = -1
		n.internal = true
		for ob := old; ob >= 0; {
			nx := t.next[ob]
			t.insertChild(ni, ob, depth)
			ob = nx
		}
	}
	t.insertChild(ni, b, depth)
}

func (t *tree) insertChild(ni int32, b int32, depth int) {
	oct := octant(&t.nodes[ni], t.pos[b])
	c := t.nodes[ni].child[oct]
	if c == 0 {
		c = t.newChild(ni, oct)
	}
	t.insert(c, b, depth+1)
}

func (t *tree) summarize(ni int32) {
	n := &t.nodes[ni]
	var mx, my, mz, m float64
	if !n.internal {
		for b := n.first; b >= 0; b = t.next[b] {
			bm := t.mass[b]
			m += bm
			mx += bm * t.pos[b].X
			my += bm * t.pos[b].Y
			mz += bm * t.pos[b].Z
		}
	} else {
		for _, c := range n.child {
			if c == 0 {
				continue
			}
			t.summarize(c)
			cn := &t.nodes[c]
			m += cn.mass
			mx += cn.mass * cn.comx
			my += cn.mass * cn.comy
			mz += cn.mass * cn.comz
		}
	}
	n.mass = m
	n.comx, n.comy, n.comz = mx/m, my/m, mz/m
}

// order lists bodies in depth-first tree order; walking targets in this order
// keeps successive traversals in cache.
func (t *tree) order(ni int32, out []int32) []int32 {
	n := &t.nodes[ni]
	if !n.internal {
		for b := n.first; b >= 0; b = t.next[b] {
			out = append(out, b)
		}
		return out
	}
	for _, c := range n.child {
		if c != 0 {
			out = t.order(c, out)
		}
	}
	return out
}

func (s *System) accelTree(pos []Vec3, out []Vec3) {
	mass := make([]float64, len(pos))
	for i, b := range s.Bodies {
		mass[i] = b.M
	}
	t := buildTree(pos, mass)
	e2 := s.Eps * s.Eps
	th2 := s.Theta * s.Theta
	G := s.G
	stack := make([]int32, 0, 256)
	for _, ti := range t.order(0, make([]int32, 0, len(pos))) {
		i := int(ti)
		px, py, pz := pos[i].X, pos[i].Y, pos[i].Z
		var ax, ay, az float64
		stack = append(stack[:0], 0)
		for len(stack) > 0 {
			ni := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			n := &t.nodes[ni]
			if !n.internal {
				for b := n.first; b >= 0; b = t.next[b] {
					if int(b) == i {
						continue
					}
					dx, dy, dz := pos[b].X-px, pos[b].Y-py, pos[b].Z-pz
					r2 := dx*dx + dy*dy + dz*dz + e2
					f := G * mass[b] / (r2 * math.Sqrt(r2))
					ax += dx * f
					ay += dy * f
					az += dz * f
				}
				continue
			}
			dx, dy, dz := n.comx-px, n.comy-py, n.comz-pz
			r2 := dx*dx + dy*dy + dz*dz
			// cheap far-field test first; a target inside the cell is never "far"
			if n.size2 < th2*r2 &&
				!(math.Abs(px-n.cx) <= n.half && math.Abs(py-n.cy) <= n.half && math.Abs(pz-n.cz) <= n.half) {
				r2 += e2
				f := G * n.mass / (r2 * math.Sqrt(r2))
				ax += dx * f
				ay += dy * f
				az += dz * f
				continue
			}
			for _, c := range n.child {
				if c != 0 {
					stack = append(stack, c)
				}
			}
		}
		out[i] = Vec3{ax, ay, az}
	}
}
