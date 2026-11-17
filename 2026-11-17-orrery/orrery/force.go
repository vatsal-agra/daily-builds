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

type node struct {
	cx, cy, cz float64 // cell centre
	half       float64 // half-width
	mass       float64
	com        Vec3
	child      [8]int32 // 0 = none (index 0 is the root and never a child)
	bodies     []int32  // leaf contents (nil for internal nodes)
	internal   bool
}

type tree struct {
	nodes []node
	mass  []float64
	pos   []Vec3
}

const maxDepth = 60

func buildTree(pos []Vec3, mass []float64) *tree {
	t := &tree{mass: mass, pos: pos, nodes: make([]node, 0, 2*len(pos)+1)}
	lo, hi := pos[0], pos[0]
	for _, p := range pos {
		lo = Vec3{math.Min(lo.X, p.X), math.Min(lo.Y, p.Y), math.Min(lo.Z, p.Z)}
		hi = Vec3{math.Max(hi.X, p.X), math.Max(hi.Y, p.Y), math.Max(hi.Z, p.Z)}
	}
	half := math.Max(hi.X-lo.X, math.Max(hi.Y-lo.Y, hi.Z-lo.Z))/2*1.000001 + 1e-300
	t.nodes = append(t.nodes, node{cx: (lo.X + hi.X) / 2, cy: (lo.Y + hi.Y) / 2, cz: (lo.Z + hi.Z) / 2, half: half})
	for i := range pos {
		t.insert(0, int32(i), 0)
	}
	t.summarize(0)
	return t
}

func (t *tree) octant(n *node, p Vec3) int {
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
	c := node{cx: p.cx - h, cy: p.cy - h, cz: p.cz - h, half: h}
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
		if len(n.bodies) == 0 || depth >= maxDepth {
			n.bodies = append(n.bodies, b)
			return
		}
		// split leaf
		old := n.bodies
		n.bodies = nil
		n.internal = true
		for _, ob := range old {
			t.insertChild(ni, ob, depth)
		}
	}
	t.insertChild(ni, b, depth)
}

func (t *tree) insertChild(ni int32, b int32, depth int) {
	oct := t.octant(&t.nodes[ni], t.pos[b])
	c := t.nodes[ni].child[oct]
	if c == 0 {
		c = t.newChild(ni, oct)
	}
	t.insert(c, b, depth+1)
}

func (t *tree) summarize(ni int32) {
	n := &t.nodes[ni]
	if !n.internal {
		for _, b := range n.bodies {
			n.mass += t.mass[b]
			n.com = n.com.AddScaled(t.pos[b], t.mass[b])
		}
	} else {
		for _, c := range n.child {
			if c == 0 {
				continue
			}
			t.summarize(c)
			cn := &t.nodes[c]
			n.mass += cn.mass
			n.com = n.com.AddScaled(cn.com, cn.mass)
		}
	}
	n.com = n.com.Scale(1 / n.mass)
}

func (s *System) accelTree(pos []Vec3, out []Vec3) {
	mass := make([]float64, len(pos))
	for i, b := range s.Bodies {
		mass[i] = b.M
	}
	t := buildTree(pos, mass)
	e2 := s.Eps * s.Eps
	th2 := s.Theta * s.Theta
	stack := make([]int32, 0, 128)
	for i := range pos {
		p := pos[i]
		var a Vec3
		stack = append(stack[:0], 0)
		for len(stack) > 0 {
			ni := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			n := &t.nodes[ni]
			if !n.internal {
				for _, b := range n.bodies {
					if int(b) == i {
						continue
					}
					d := pos[b].Sub(p)
					r2 := d.Norm2() + e2
					a = a.AddScaled(d, s.G*mass[b]/(r2*math.Sqrt(r2)))
				}
				continue
			}
			d := n.com.Sub(p)
			r2 := d.Norm2()
			size := 2 * n.half
			inside := math.Abs(p.X-n.cx) <= n.half && math.Abs(p.Y-n.cy) <= n.half && math.Abs(p.Z-n.cz) <= n.half
			if !inside && size*size < th2*r2 {
				r2 += e2
				a = a.AddScaled(d, s.G*n.mass/(r2*math.Sqrt(r2)))
				continue
			}
			for _, c := range n.child {
				if c != 0 {
					stack = append(stack, c)
				}
			}
		}
		out[i] = a
	}
}
