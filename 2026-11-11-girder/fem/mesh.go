package fem

import (
	"fmt"
	"math"
)

// Mesh is a 2-D finite-element mesh of a single element type.
type Mesh struct {
	X, Y []float64
	Type ElemType
	Conn [][]int
}

func (m *Mesh) NumNodes() int { return len(m.X) }
func (m *Mesh) NumElems() int { return len(m.Conn) }

// ElemCoords returns the nodal coordinates of element e.
func (m *Mesh) ElemCoords(e int) (xs, ys []float64) {
	c := m.Conn[e]
	xs, ys = make([]float64, len(c)), make([]float64, len(c))
	for i, n := range c {
		xs[i], ys[i] = m.X[n], m.Y[n]
	}
	return
}

// Area returns the total mesh area.
func (m *Mesh) Area() float64 {
	a := 0.0
	for e := range m.Conn {
		xs, ys := m.ElemCoords(e)
		for _, g := range m.Type.StiffRule() {
			_, _, det, err := Jacobian(m.Type, xs, ys, g.xi, g.eta)
			if err == nil {
				a += g.w * det
			}
		}
	}
	return a
}

// Validate checks connectivity and element positivity.
func (m *Mesh) Validate() error {
	if len(m.X) != len(m.Y) {
		return fmt.Errorf("coordinate arrays differ in length")
	}
	if len(m.Conn) == 0 {
		return fmt.Errorf("mesh has no elements")
	}
	used := make([]bool, len(m.X))
	for e, c := range m.Conn {
		if len(c) != m.Type.NodesPer() {
			return fmt.Errorf("element %d has %d nodes, %s needs %d", e, len(c), m.Type, m.Type.NodesPer())
		}
		for _, n := range c {
			if n < 0 || n >= len(m.X) {
				return fmt.Errorf("element %d references node %d out of range", e, n)
			}
			used[n] = true
		}
		xs, ys := m.ElemCoords(e)
		for _, g := range m.Type.StiffRule() {
			if _, _, _, err := Jacobian(m.Type, xs, ys, g.xi, g.eta); err != nil {
				return fmt.Errorf("element %d: %w", e, err)
			}
		}
	}
	for n, u := range used {
		if !u {
			return fmt.Errorf("node %d belongs to no element", n)
		}
	}
	return nil
}

// fixOrientation flips clockwise elements so that all are counter-clockwise.
func (m *Mesh) fixOrientation() {
	corners := 3
	if m.Type == Quad4 {
		corners = 4
	}
	for e, c := range m.Conn {
		xs, ys := m.ElemCoords(e)
		a := 0.0
		for i := 0; i < corners; i++ {
			j := (i + 1) % corners
			a += xs[i]*ys[j] - xs[j]*ys[i]
		}
		if a >= 0 {
			continue
		}
		switch m.Type {
		case Tri3:
			c[1], c[2] = c[2], c[1]
		case Tri6:
			c[1], c[2] = c[2], c[1]
			c[3], c[5] = c[5], c[3]
		case Quad4:
			c[1], c[3] = c[3], c[1]
		}
	}
}

// gridMesh builds a structured mesh over an (nu+1)x(nv+1) lattice of points; the lattice
// is traversed with u as the "first" direction and v the second.
func gridMesh(nu, nv int, pos func(i, j int) (float64, float64), t ElemType) *Mesh {
	m := &Mesh{Type: t}
	for j := 0; j <= nv; j++ {
		for i := 0; i <= nu; i++ {
			x, y := pos(i, j)
			m.X = append(m.X, x)
			m.Y = append(m.Y, y)
		}
	}
	id := func(i, j int) int { return j*(nu+1) + i }
	for j := 0; j < nv; j++ {
		for i := 0; i < nu; i++ {
			a, b, c, d := id(i, j), id(i+1, j), id(i+1, j+1), id(i, j+1)
			switch t {
			case Quad4:
				m.Conn = append(m.Conn, []int{a, b, c, d})
			default:
				if (i+j)%2 == 0 {
					m.Conn = append(m.Conn, []int{a, b, c}, []int{a, c, d})
				} else {
					m.Conn = append(m.Conn, []int{a, b, d}, []int{b, c, d})
				}
			}
		}
	}
	if t == Tri6 {
		m = tri3ToTri6(m)
	}
	m.fixOrientation()
	return m
}

func tri3ToTri6(m *Mesh) *Mesh {
	out := &Mesh{X: append([]float64(nil), m.X...), Y: append([]float64(nil), m.Y...), Type: Tri6}
	mid := map[[2]int]int{}
	get := func(a, b int) int {
		k := [2]int{a, b}
		if a > b {
			k = [2]int{b, a}
		}
		if n, ok := mid[k]; ok {
			return n
		}
		out.X = append(out.X, (m.X[a]+m.X[b])/2)
		out.Y = append(out.Y, (m.Y[a]+m.Y[b])/2)
		mid[k] = len(out.X) - 1
		return len(out.X) - 1
	}
	for _, c := range m.Conn {
		out.Conn = append(out.Conn, []int{c[0], c[1], c[2], get(c[0], c[1]), get(c[1], c[2]), get(c[2], c[0])})
	}
	return out
}

// Rect meshes the rectangle [x0,x0+w] x [y0,y0+h] with nx*ny cells.
func Rect(x0, y0, w, h float64, nx, ny int, t ElemType) (*Mesh, error) {
	if nx < 1 || ny < 1 || !(w > 0) || !(h > 0) {
		return nil, fmt.Errorf("Rect needs positive size and at least 1 cell per side")
	}
	return gridMesh(nx, ny, func(i, j int) (float64, float64) {
		return x0 + w*float64(i)/float64(nx), y0 + h*float64(j)/float64(ny)
	}, t), nil
}

// Annulus meshes a quarter annulus a<=r<=b, 0<=theta<=90deg. Curved edges are polygonal
// for linear elements; tri6 midside nodes are projected back onto the circle arcs for accuracy.
func Annulus(a, b float64, nr, nt int, t ElemType) (*Mesh, error) {
	if !(a > 0 && b > a) || nr < 1 || nt < 1 {
		return nil, fmt.Errorf("Annulus needs 0 < a < b and positive divisions")
	}
	m := gridMesh(nr, nt, func(i, j int) (float64, float64) {
		r := a + (b-a)*float64(i)/float64(nr)
		th := math.Pi / 2 * float64(j) / float64(nt)
		return r * math.Cos(th), r * math.Sin(th)
	}, t)
	if t == Tri6 { // re-place mid nodes on exact polar positions
		for _, c := range m.Conn {
			for k := 3; k < 6; k++ {
				p, q := c[k-3], c[(k-2)%3]
				if k == 5 {
					p, q = c[2], c[0]
				}
				r1, r2 := math.Hypot(m.X[p], m.Y[p]), math.Hypot(m.X[q], m.Y[q])
				t1, t2 := math.Atan2(m.Y[p], m.X[p]), math.Atan2(m.Y[q], m.X[q])
				if math.Abs(r1-r2) < 1e-9*b || math.Abs(t1-t2) < 1e-9 { // arc or radial edge
					r, th := (r1+r2)/2, (t1+t2)/2
					m.X[c[k]], m.Y[c[k]] = r*math.Cos(th), r*math.Sin(th)
				}
			}
		}
	}
	return m, nil
}

// QuarterHole meshes one quadrant of a square plate [0,L]^2 with a circular hole of radius a
// centred at the origin (symmetry boundaries lie on the x and y axes). nr radial, nt angular cells.
func QuarterHole(L, a float64, nr, nt int, t ElemType) (*Mesh, error) {
	if !(a > 0 && L > a*1.2) || nr < 1 || nt < 2 {
		return nil, fmt.Errorf("QuarterHole needs L > 1.2a > 0 and nt >= 2")
	}
	sq := func(th float64) (float64, float64) {
		c, s := math.Cos(th), math.Sin(th)
		if th <= math.Pi/4 {
			return L, L * s / c
		}
		return L * c / s, L
	}
	m := gridMesh(nr, nt, func(i, j int) (float64, float64) {
		th := math.Pi / 2 * float64(j) / float64(nt)
		s := float64(i) / float64(nr)
		s = math.Pow(s, 1.4) // cluster toward the hole
		ox, oy := sq(th)
		return (1-s)*a*math.Cos(th) + s*ox, (1-s)*a*math.Sin(th) + s*oy
	}, t)
	if t == Tri6 { // put hole-edge midside nodes on the true circle
		for _, c := range m.Conn {
			for k := 0; k < 3; k++ {
				p, q := c[k], c[(k+1)%3]
				if math.Abs(math.Hypot(m.X[p], m.Y[p])-a) < 1e-9*a && math.Abs(math.Hypot(m.X[q], m.Y[q])-a) < 1e-9*a {
					th := (math.Atan2(m.Y[p], m.X[p]) + math.Atan2(m.Y[q], m.X[q])) / 2
					m.X[c[3+k]], m.Y[c[3+k]] = a*math.Cos(th), a*math.Sin(th)
				}
			}
		}
	}
	return m, nil
}

// Edge is an ordered chain of boundary nodes (2, or 3 with the midside node last).
type Edge []int

// BoundaryEdges returns all element edges that belong to exactly one element, oriented so the
// element lies to their left (outward normal on the right).
func (m *Mesh) BoundaryEdges() []Edge {
	type rec struct {
		e     Edge
		count int
	}
	seen := map[[2]int]*rec{}
	var order [][2]int
	corners := 3
	if m.Type == Quad4 {
		corners = 4
	}
	for _, c := range m.Conn {
		for k := 0; k < corners; k++ {
			a, b := c[k], c[(k+1)%corners]
			e := Edge{a, b}
			if m.Type == Tri6 {
				e = Edge{a, b, c[3+k]}
			}
			key := [2]int{a, b}
			if a > b {
				key = [2]int{b, a}
			}
			if r, ok := seen[key]; ok {
				r.count++
			} else {
				seen[key] = &rec{e: e, count: 1}
				order = append(order, key)
			}
		}
	}
	var out []Edge
	for _, k := range order {
		if r := seen[k]; r.count == 1 {
			out = append(out, r.e)
		}
	}
	return out
}

// EdgesWhere filters boundary edges by a predicate on the endpoints.
func (m *Mesh) EdgesWhere(pred func(x1, y1, x2, y2 float64) bool) []Edge {
	var out []Edge
	for _, e := range m.BoundaryEdges() {
		if pred(m.X[e[0]], m.Y[e[0]], m.X[e[1]], m.Y[e[1]]) {
			out = append(out, e)
		}
	}
	return out
}

// NodesWhere returns nodes satisfying a predicate.
func (m *Mesh) NodesWhere(pred func(x, y float64) bool) []int {
	var out []int
	for i := range m.X {
		if pred(m.X[i], m.Y[i]) {
			out = append(out, i)
		}
	}
	return out
}

// NearestNode returns the index of the node closest to (x,y).
func (m *Mesh) NearestNode(x, y float64) int {
	best, bd := 0, math.Inf(1)
	for i := range m.X {
		if d := math.Hypot(m.X[i]-x, m.Y[i]-y); d < bd {
			best, bd = i, d
		}
	}
	return best
}

// Bounds returns the bounding box.
func (m *Mesh) Bounds() (x0, y0, x1, y1 float64) {
	x0, y0, x1, y1 = math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)
	for i := range m.X {
		x0, x1 = math.Min(x0, m.X[i]), math.Max(x1, m.X[i])
		y0, y1 = math.Min(y0, m.Y[i]), math.Max(y1, m.Y[i])
	}
	return
}
