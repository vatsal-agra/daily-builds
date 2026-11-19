package layout

import (
	"fmt"
	"math"
	"sort"
)

type chain struct {
	edge      int   // index into Graph.Edges
	comp      int   // component id
	path      []int // pg node ids, top (low rank) to bottom
	reversed  bool
	labelNode int // pg id of the label dummy, or -1
}

type component struct {
	nodes []int // global node indices; pg id i == nodes[i] for real nodes
	p     *pg
}

type prepared struct {
	g        Graph
	o        Options
	rev      []bool
	comps    []*component
	chains   []chain
	loops    []int     // self-loop edge indices
	loopCnt  []int     // self-loops per node
	pad      []float64 // symmetric padding reserved for loops, per node
	anyLabel bool
}

const (
	loopExtra  = 22.0
	maxSize    = 4000.0
	labelCharW = 6.4
	labelH     = 16.0
)

func labelW(s string) float64 { return float64(len([]rune(s)))*labelCharW + 10 }

func validate(g *Graph) error {
	for _, n := range g.Nodes {
		if n.W < 0 || n.H < 0 || math.IsNaN(n.W) || math.IsNaN(n.H) || n.W > maxSize || n.H > maxSize {
			return fmt.Errorf("node %q has invalid size %gx%g (limit %g)", n.ID, n.W, n.H, maxSize)
		}
	}
	for i, e := range g.Edges {
		if e.From < 0 || e.From >= len(g.Nodes) || e.To < 0 || e.To >= len(g.Nodes) {
			return fmt.Errorf("edge %d references node out of range (%d -> %d, %d nodes)", i, e.From, e.To, len(g.Nodes))
		}
	}
	return nil
}

// loopGeom returns the protrusion of the k-th (0-based) self-loop.
func loopGeom(k int) float64 { return loopExtra * 1.4 * (1 + 0.55*float64(k)) }

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
	n := len(g.Nodes)
	pr := &prepared{g: g, o: o, loopCnt: make([]int, n), pad: make([]float64, n)}
	for i := range g.Edges {
		e := &g.Edges[i]
		if e.Weight < 1 {
			e.Weight = 1
		}
		if e.MinLen < 1 {
			e.MinLen = 1
		}
		if e.Label != "" && e.From != e.To {
			pr.anyLabel = true
		}
	}
	// Labelled edges need a rank to hold their label: double every minimum
	// length so each labelled edge spans >= 2 ranks (Graphviz does the same).
	mult := 1
	if pr.anyLabel {
		mult = 2
	}
	pr.rev = feedbackSet(n, g.Edges, o.Acyclic)
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
	for i, e := range g.Edges {
		if e.From == e.To {
			pr.loops = append(pr.loops, i)
			k := pr.loopCnt[e.From]
			pr.loopCnt[e.From]++
			ext := loopGeom(k)
			if e.Label != "" {
				if o.RankDir == "LR" {
					ext += labelH + 4
				} else {
					ext += labelW(e.Label) + 4
				}
			}
			if ext > pr.pad[e.From] {
				pr.pad[e.From] = ext
			}
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
			re = append(re, rankEdge{u, v, e.Weight, e.MinLen * mult})
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
			p.addNode(ranks[li], false, w+2*pr.pad[gv], h, gv)
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
			ch := chain{edge: ei, comp: ci, path: path, reversed: pr.rev[ei], labelNode: -1}
			if lb := g.Edges[ei].Label; lb != "" && len(path) >= 3 {
				d := path[len(path)/2]
				ch.labelNode = d
				if o.RankDir == "LR" {
					p.w[d], p.h[d] = labelH, labelW(lb)
				} else {
					p.w[d], p.h[d] = labelW(lb), labelH
				}
			}
			pr.chains = append(pr.chains, ch)
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
	res := &Result{Opts: o, Rows: 1}
	if len(g.Nodes) == 0 {
		return res, nil
	}
	m := Metrics{}
	xs := make([][]float64, len(pr.comps))
	maxRank := 0
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
		for _, l := range p.layers {
			if len(l) > m.MaxLayer {
				m.MaxLayer = len(l)
			}
		}
		if len(p.layers) > maxRank {
			maxRank = len(p.layers)
		}
		for v := 0; v < p.n; v++ {
			if p.virtual[v] {
				m.Dummies++
			}
		}
	}
	m.Layers = maxRank
	// global layer geometry so equal ranks line up across components
	rankSep := o.RankSep
	if pr.anyLabel {
		rankSep /= 2
	}
	lh := make([]float64, maxRank)
	for _, c := range pr.comps {
		for v := 0; v < c.p.n; v++ {
			if c.p.h[v] > lh[c.p.rank[v]] {
				lh[c.p.rank[v]] = c.p.h[v]
			}
		}
	}
	ly := make([]float64, maxRank)
	cur := 0.0
	for r := range ly {
		ly[r] = cur + lh[r]/2
		cur += lh[r] + rankSep
	}
	// shelf-pack components into rows aiming at a ~3:2 canvas
	type ext struct{ lo, hi, top, bot float64 }
	exts := make([]ext, len(pr.comps))
	area, widest := 0.0, 0.0
	for ci, c := range pr.comps {
		p := c.p
		e := ext{math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)}
		for v := 0; v < p.n; v++ {
			e.lo = math.Min(e.lo, xs[ci][v]-p.w[v]/2)
			e.hi = math.Max(e.hi, xs[ci][v]+p.w[v]/2)
			e.top = math.Min(e.top, ly[p.rank[v]]-p.h[v]/2)
			e.bot = math.Max(e.bot, ly[p.rank[v]]+p.h[v]/2)
		}
		exts[ci] = e
		w, h := e.hi-e.lo+2*o.NodeSep, e.bot-e.top+rankSep
		area += w * h
		widest = math.Max(widest, w)
	}
	target := math.Max(widest, math.Sqrt(area)*1.5)
	offX := make([]float64, len(pr.comps))
	offY := make([]float64, len(pr.comps))
	cx, rowY, rowH := 0.0, 0.0, 0.0
	rows, inRow := 1, 0
	for ci := range pr.comps {
		e := exts[ci]
		w, h := e.hi-e.lo+2*o.NodeSep, e.bot-e.top+rankSep
		if inRow > 0 && cx+w > target {
			rows++
			rowY += rowH
			cx, rowH, inRow = 0, 0, 0
		}
		offX[ci] = cx - e.lo
		offY[ci] = rowY
		cx += w
		rowH = math.Max(rowH, h)
		inRow++
	}
	res.Rows = rows
	tf := func(x, y float64) Pt {
		if o.RankDir == "LR" {
			return Pt{y, x}
		}
		return Pt{x, y}
	}
	nodePos := make([]Pt, len(g.Nodes))
	rankOf := make([]int, len(g.Nodes))
	orderOf := make([]int, len(g.Nodes))
	ys := make([][]float64, len(pr.comps))
	for ci, c := range pr.comps {
		ys[ci] = make([]float64, c.p.n)
		for v := 0; v < c.p.n; v++ {
			ys[ci][v] = ly[c.p.rank[v]] + offY[ci]
			xs[ci][v] += offX[ci]
		}
		for li, gv := range c.nodes {
			nodePos[gv] = tf(xs[ci][li], ys[ci][li])
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
	pr.route(res, xs, ys, tf)
	pr.routeLoops(res)
	// metrics
	div := float64(1)
	if pr.anyLabel {
		div = 2
	}
	for i, e := range g.Edges {
		if e.From == e.To {
			continue
		}
		span := res.Nodes[e.To].Rank - res.Nodes[e.From].Rank
		if span < 0 {
			span = -span
		}
		m.EdgeLength += float64(e.Weight*span) / div
		if pr.rev[i] {
			m.Reversed++
		}
	}
	for _, ch := range pr.chains {
		x := xs[ch.comp]
		for k := 1; k+1 < len(ch.path); k++ {
			a, b, c := x[ch.path[k-1]], x[ch.path[k]], x[ch.path[k+1]]
			if math.Abs((b-a)-(c-b)) > 0.5 {
				m.Bends++
			}
		}
	}
	// canvas
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
		if er.HasLabel {
			lw := labelW(er.Label)
			grow(er.LabelPos.X-lw/2, er.LabelPos.Y-labelH/2)
			grow(er.LabelPos.X+lw/2, er.LabelPos.Y+labelH/2)
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
		res.Edges[i].LabelPos.X += dx
		res.Edges[i].LabelPos.Y += dy
	}
	res.Width, res.Height = maxX-minX+2*margin, maxY-minY+2*margin
	m.Width, m.Height = res.Width, res.Height
	res.Metrics = m
	return res, nil
}

func (pr *prepared) routeLoops(res *Result) {
	seen := make([]int, len(pr.g.Nodes))
	for _, ei := range pr.loops {
		e := pr.g.Edges[ei]
		nb := res.Nodes[e.From]
		k := seen[e.From]
		seen[e.From]++
		ext := loopGeom(k)
		w, h, x, y := nb.W, nb.H, nb.X, nb.Y
		er := &res.Edges[ei]
		er.SelfLoop = true
		if pr.o.RankDir == "LR" { // loop below the node, clear of the rank axis
			er.Points = []Pt{{x - w/4, y + h/2}, {x - w/2 - 4, y + h/2 + ext}, {x + w/2 + 4, y + h/2 + ext}, {x + w/4, y + h/2}}
			if e.Label != "" {
				er.HasLabel, er.LabelPos = true, Pt{x, y + h/2 + ext*0.75 + labelH/2 + 2}
			}
		} else {
			er.Points = []Pt{{x + w/2, y - h/4}, {x + w/2 + ext, y - h/2 - 4}, {x + w/2 + ext, y + h/2 + 4}, {x + w/2, y + h/4}}
			if e.Label != "" {
				er.HasLabel, er.LabelPos = true, Pt{x + w/2 + ext*0.75 + labelW(e.Label)/2 + 2, y}
			}
		}
	}
}

// route builds polyline points for every non-loop edge. Attachment points are
// spread along the node border ordered by where the edge heads next.
func (pr *prepared) route(res *Result, xs, ys [][]float64, tf func(x, y float64) Pt) {
	type end struct {
		ch   int
		out  bool // leaves its node (bottom side) vs arrives (top side)
		peer float64
	}
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
		inner := p.w[key[1]] - 2*pr.pad[p.real[key[1]]] // visible box width
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
		var pts []Pt
		for i, v := range ch.path {
			px, py := x[v], y[v]
			if i == 0 {
				px += portX[k][0]
				py += pr.borderDY(p, v, portX[k][0])
			}
			if i == len(ch.path)-1 {
				px += portX[k][1]
				py -= pr.borderDY(p, v, portX[k][1])
			}
			pts = append(pts, tf(px, py))
		}
		if ch.reversed {
			for a, b := 0, len(pts)-1; a < b; a, b = a+1, b-1 {
				pts[a], pts[b] = pts[b], pts[a]
			}
		}
		er := &res.Edges[ch.edge]
		er.Points = pts
		if ch.labelNode >= 0 {
			er.HasLabel = true
			er.LabelPos = tf(x[ch.labelNode], y[ch.labelNode])
		}
	}
}

// borderDY is the vertical distance from node centre to its border at a given
// horizontal offset (half the height for boxes; elliptical for ellipses).
func (pr *prepared) borderDY(p *pg, v int, dx float64) float64 {
	gv := p.real[v]
	if gv < 0 {
		return 0
	}
	h := p.h[v] / 2
	if pr.g.Nodes[gv].Shape == "ellipse" {
		w := p.w[v]/2 - pr.pad[gv]
		if w > 0 {
			if r := dx / w; r > -1 && r < 1 {
				return h * math.Sqrt(1-r*r)
			}
			return 0
		}
	}
	return h
}
