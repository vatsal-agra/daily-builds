package layout

import (
	"fmt"
	"math"
	"sort"
)

type chain struct {
	edge     int   // index into Graph.Edges
	comp     int   // component id
	path     []int // pg node ids, top (low rank) to bottom
	reversed bool
}

type component struct {
	nodes []int // global node indices; pg id i == nodes[i] for real nodes
	p     *pg
}

type prepared struct {
	g      Graph
	o      Options
	rev    []bool
	comps  []*component
	chains []chain
	loops  []int // self-loop edge indices
}

const loopExtra = 22.0

func validate(g *Graph) error {
	for _, n := range g.Nodes {
		if n.W < 0 || n.H < 0 || math.IsNaN(n.W) || math.IsNaN(n.H) {
			return fmt.Errorf("node %q has invalid size %gx%g", n.ID, n.W, n.H)
		}
	}
	for i, e := range g.Edges {
		if e.From < 0 || e.From >= len(g.Nodes) || e.To < 0 || e.To >= len(g.Nodes) {
			return fmt.Errorf("edge %d references node out of range (%d -> %d, %d nodes)", i, e.From, e.To, len(g.Nodes))
		}
	}
	return nil
}

// prepare runs cycle removal, layering, virtual-node insertion and the initial
// ordering for every connected component (no crossing minimisation yet).
func prepare(in Graph, o Options) (*prepared, error) {
	if err := o.defaults(); err != nil {
		return nil, err
	}
	if err := validate(&in); err != nil {
		return nil, err
	}
	g := Graph{Nodes: append([]InNode(nil), in.Nodes...), Edges: append([]InEdge(nil), in.Edges...)}
	for i := range g.Edges {
		if g.Edges[i].Weight < 1 {
			g.Edges[i].Weight = 1
		}
		if g.Edges[i].MinLen < 1 {
			g.Edges[i].MinLen = 1
		}
	}
	n := len(g.Nodes)
	pr := &prepared{g: g, o: o}
	pr.rev = feedbackSet(n, g.Edges, o.Acyclic)
	// components over non-loop edges
	uf := make([]int, n)
	for i := range uf {
		uf[i] = i
	}
	var find func(int) int
	find = func(x int) int {
		for uf[x] != x {
			uf[x] = uf[uf[x]]
			x = uf[x]
		}
		return x
	}
	hasLoop := make([]bool, n)
	for i, e := range g.Edges {
		if e.From == e.To {
			pr.loops = append(pr.loops, i)
			hasLoop[e.From] = true
			continue
		}
		a, b := find(e.From), find(e.To)
		if a != b {
			uf[a] = b
		}
	}
	compOf := map[int]int{}
	local := make([]int, n)
	for v := 0; v < n; v++ {
		r := find(v)
		ci, ok := compOf[r]
		if !ok {
			ci = len(pr.comps)
			compOf[r] = ci
			pr.comps = append(pr.comps, &component{})
		}
		local[v] = len(pr.comps[ci].nodes)
		pr.comps[ci].nodes = append(pr.comps[ci].nodes, v)
	}
	compEdges := make([][]int, len(pr.comps))
	for i, e := range g.Edges {
		if e.From != e.To {
			ci := compOf[find(e.From)]
			compEdges[ci] = append(compEdges[ci], i)
		}
	}
	for ci, c := range pr.comps {
		var re []rankEdge
		for _, ei := range compEdges[ci] {
			e := g.Edges[ei]
			u, v := local[e.From], local[e.To]
			if pr.rev[ei] {
				u, v = v, u
			}
			re = append(re, rankEdge{u, v, e.Weight, e.MinLen})
		}
		var ranks []int
		var err error
		if o.Ranker == "simplex" {
			ranks, err = networkSimplexRanks(len(c.nodes), re)
		} else {
			ranks, err = longestPathRanks(len(c.nodes), re)
		}
		if err != nil {
			return nil, err
		}
		p := &pg{}
		for li, gv := range c.nodes {
			w, h := g.Nodes[gv].W, g.Nodes[gv].H
			if o.RankDir == "LR" {
				w, h = h, w
			}
			if hasLoop[gv] {
				w += 2 * loopExtra
			}
			p.addNode(ranks[li], false, w, h, gv)
		}
		for k, ei := range compEdges[ci] {
			r := re[k]
			path := []int{r.u}
			prev := r.u
			for rk := ranks[r.u] + 1; rk < ranks[r.v]; rk++ {
				d := p.addNode(rk, true, 2, 2, -1)
				p.addArc(prev, d, r.w)
				path = append(path, d)
				prev = d
			}
			p.addArc(prev, r.v, r.w)
			path = append(path, r.v)
			pr.chains = append(pr.chains, chain{edge: ei, comp: ci, path: path, reversed: pr.rev[ei]})
		}
		p.initialOrder()
		c.p = p
	}
	return pr, nil
}

// Layout runs the full pipeline.
func Layout(in Graph, o Options) (*Result, error) {
	pr, err := prepare(in, o)
	if err != nil {
		return nil, err
	}
	o = pr.o
	g := pr.g
	res := &Result{Opts: o}
	if len(g.Nodes) == 0 {
		return res, nil
	}
	m := Metrics{}
	xs := make([][]float64, len(pr.comps))
	ys := make([][]float64, len(pr.comps))
	for ci, c := range pr.comps {
		p := c.p
		if o.Order == "sweep" {
			p.minimizeCrossings(o.Sweeps)
		}
		m.Crossings += p.crossings()
		if o.Coord == "bk" {
			xs[ci] = p.bkCoords(o.NodeSep)
		} else {
			xs[ci] = p.packedCoords(o.NodeSep)
		}
		p.enforceSeparation(xs[ci], o.NodeSep)
		// y by layer
		lh := make([]float64, len(p.layers))
		for r, l := range p.layers {
			for _, v := range l {
				if p.h[v] > lh[r] {
					lh[r] = p.h[v]
				}
			}
			if len(l) > m.MaxLayer {
				m.MaxLayer = len(l)
			}
		}
		if len(p.layers) > m.Layers {
			m.Layers = len(p.layers)
		}
		ly := make([]float64, len(p.layers))
		cur := 0.0
		for r := range ly {
			ly[r] = cur + lh[r]/2
			cur += lh[r] + o.RankSep
		}
		ys[ci] = make([]float64, p.n)
		for v := 0; v < p.n; v++ {
			ys[ci][v] = ly[p.rank[v]]
		}
		for v := 0; v < p.n; v++ {
			if p.virtual[v] {
				m.Dummies++
			}
		}
	}
	// pack components side by side (TB frame)
	off := make([]float64, len(pr.comps))
	cursor := 0.0
	for ci, c := range pr.comps {
		p := c.p
		lo, hi := math.Inf(1), math.Inf(-1)
		for v := 0; v < p.n; v++ {
			lo = math.Min(lo, xs[ci][v]-p.w[v]/2)
			hi = math.Max(hi, xs[ci][v]+p.w[v]/2)
		}
		off[ci] = cursor - lo
		cursor += hi - lo + 2*o.NodeSep
	}
	// final point transform (TB frame -> output frame)
	tf := func(x, y float64) Pt {
		if o.RankDir == "LR" {
			return Pt{y, x}
		}
		return Pt{x, y}
	}
	nodePos := make([]Pt, len(g.Nodes))
	rankOf := make([]int, len(g.Nodes))
	orderOf := make([]int, len(g.Nodes))
	for ci, c := range pr.comps {
		for li, gv := range c.nodes {
			nodePos[gv] = tf(xs[ci][li]+off[ci], ys[ci][li])
			rankOf[gv] = c.p.rank[li]
			orderOf[gv] = c.p.pos[li]
		}
	}
	res.Nodes = make([]NodeBox, len(g.Nodes))
	for i, nd := range g.Nodes {
		res.Nodes[i] = NodeBox{InNode: nd, X: nodePos[i].X, Y: nodePos[i].Y, Rank: rankOf[i], Order: orderOf[i]}
	}
	res.Edges = make([]EdgeRoute, len(g.Edges))
	for i, e := range g.Edges {
		res.Edges[i] = EdgeRoute{InEdge: e, Reversed: pr.rev[i]}
	}
	pr.route(res, xs, ys, off, tf)
	for _, ei := range pr.loops {
		e := g.Edges[ei]
		nb := res.Nodes[e.From]
		w, h := nb.W, nb.H
		x, y := nb.X, nb.Y
		// loop on the right side (output frame), cubic control points
		res.Edges[ei].SelfLoop = true
		res.Edges[ei].Points = []Pt{
			{x + w/2, y - h/4}, {x + w/2 + loopExtra*1.4, y - h/2 - 4},
			{x + w/2 + loopExtra*1.4, y + h/2 + 4}, {x + w/2, y + h/4},
		}
		if pr.o.RankDir == "LR" { // loop below the node instead, keeps clear of rank axis
			res.Edges[ei].Points = []Pt{
				{x - w/4, y + h/2}, {x - w/2 - 4, y + h/2 + loopExtra*1.4},
				{x + w/2 + 4, y + h/2 + loopExtra*1.4}, {x + w/4, y + h/2},
			}
		}
	}
	// metrics
	for i, e := range g.Edges {
		if e.From == e.To {
			continue
		}
		span := res.Nodes[e.To].Rank - res.Nodes[e.From].Rank
		if span < 0 {
			span = -span
		}
		m.EdgeLength += float64(e.Weight * span)
		if pr.rev[i] {
			m.Reversed++
		}
	}
	for _, ch := range pr.chains {
		p := pr.comps[ch.comp].p
		x := xs[ch.comp]
		for k := 1; k+1 < len(ch.path); k++ {
			a, b, c := x[ch.path[k-1]], x[ch.path[k]], x[ch.path[k+1]]
			if math.Abs((b-a)-(c-b)) > 0.5 {
				m.Bends++
			}
		}
		_ = p
	}
	// extents
	minX, minY := math.Inf(1), math.Inf(1)
	maxX, maxY := math.Inf(-1), math.Inf(-1)
	grow := func(x, y float64) {
		minX, maxX = math.Min(minX, x), math.Max(maxX, x)
		minY, maxY = math.Min(minY, y), math.Max(maxY, y)
	}
	for _, nb := range res.Nodes {
		grow(nb.X-nb.W/2, nb.Y-nb.H/2)
		grow(nb.X+nb.W/2, nb.Y+nb.H/2)
	}
	for _, er := range res.Edges {
		for _, pt := range er.Points {
			grow(pt.X, pt.Y)
		}
	}
	const margin = 24.0
	dx, dy := margin-minX, margin-minY
	for i := range res.Nodes {
		res.Nodes[i].X += dx
		res.Nodes[i].Y += dy
	}
	for i := range res.Edges {
		for k := range res.Edges[i].Points {
			res.Edges[i].Points[k].X += dx
			res.Edges[i].Points[k].Y += dy
		}
	}
	res.Width, res.Height = maxX-minX+2*margin, maxY-minY+2*margin
	m.Width, m.Height = res.Width, res.Height
	res.Metrics = m
	return res, nil
}

// route builds polyline points for every non-loop edge. Attachment points are
// spread along the node border ordered by where the edge heads next.
func (pr *prepared) route(res *Result, xs, ys [][]float64, off []float64, tf func(x, y float64) Pt) {
	type end struct {
		ch   int
		out  bool // leaves its node (bottom side) vs arrives (top side)
		peer float64
	}
	// per (comp, pg node) lists of ends
	ends := map[[2]int][]end{}
	for k, ch := range pr.chains {
		x := xs[ch.comp]
		first, last := ch.path[0], ch.path[len(ch.path)-1]
		ends[[2]int{ch.comp, first}] = append(ends[[2]int{ch.comp, first}], end{k, true, x[ch.path[1]]})
		ends[[2]int{ch.comp, last}] = append(ends[[2]int{ch.comp, last}], end{k, false, x[ch.path[len(ch.path)-2]]})
	}
	portX := make([][2]float64, len(pr.chains)) // [start dx, end dx]
	for key, list := range ends {
		p := pr.comps[key[0]].p
		for _, side := range []bool{true, false} {
			var sel []end
			for _, e := range list {
				if e.out == side {
					sel = append(sel, e)
				}
			}
			sort.Slice(sel, func(a, b int) bool {
				if sel[a].peer != sel[b].peer {
					return sel[a].peer < sel[b].peer
				}
				return sel[a].ch < sel[b].ch
			})
			inner := p.w[key[1]]
			if pr.g.Nodes[p.real[key[1]]].ID != "" && inner > 0 {
				// remove loop padding so ports stay on the visible box
				if hasLoopNode(pr, p.real[key[1]]) {
					inner -= 2 * loopExtra
				}
			}
			usable := inner * 0.7
			for i, e := range sel {
				d := 0.0
				if len(sel) > 1 {
					d = (float64(i)+0.5)/float64(len(sel))*usable - usable/2
				}
				if e.out {
					portX[e.ch][0] = d
				} else {
					portX[e.ch][1] = d
				}
			}
		}
	}
	for k, ch := range pr.chains {
		p := pr.comps[ch.comp].p
		x, y := xs[ch.comp], ys[ch.comp]
		o := off[ch.comp]
		var pts []Pt
		for i, v := range ch.path {
			px, py := x[v]+o, y[v]
			if i == 0 {
				px += portX[k][0]
				py += borderDY(pr, p, v, portX[k][0]) // bottom side
			}
			if i == len(ch.path)-1 {
				px += portX[k][1]
				py -= borderDY(pr, p, v, portX[k][1]) // top side
			}
			pts = append(pts, tf(px, py))
		}
		if ch.reversed {
			for a, b := 0, len(pts)-1; a < b; a, b = a+1, b-1 {
				pts[a], pts[b] = pts[b], pts[a]
			}
		}
		res.Edges[ch.edge].Points = pts
		_ = k
	}
}

func hasLoopNode(pr *prepared, gv int) bool {
	for _, ei := range pr.loops {
		if pr.g.Edges[ei].From == gv {
			return true
		}
	}
	return false
}

// borderDY is the vertical distance from node centre to its border at a given
// horizontal offset (half the height for boxes; elliptical for ellipses).
func borderDY(pr *prepared, p *pg, v int, dx float64) float64 {
	h := p.h[v] / 2
	gv := p.real[v]
	if gv >= 0 && pr.g.Nodes[gv].Shape == "ellipse" {
		w := p.w[v] / 2
		if hasLoopNode(pr, gv) {
			w -= loopExtra
		}
		if w > 0 {
			r := dx / w
			if r < 1 && r > -1 {
				return h * math.Sqrt(1-r*r)
			}
			return 0
		}
	}
	if gv < 0 {
		return 0
	}
	return h
}
