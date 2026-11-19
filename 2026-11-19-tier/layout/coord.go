package layout

import (
	"math"
	"sort"
)

// sep returns the minimum centre-to-centre distance of two layer neighbours.
func (g *pg) sep(a, b int, nodeSep float64) float64 {
	gap := nodeSep
	if g.virtual[a] || g.virtual[b] {
		gap = nodeSep / 2
		if g.virtual[a] && g.virtual[b] {
			gap = nodeSep / 3
		}
	}
	return (g.w[a]+g.w[b])/2 + gap
}

// packedCoords is the naive baseline: every layer left-aligned and packed,
// then centred on the widest layer. Ignores edges entirely.
func (g *pg) packedCoords(nodeSep float64) []float64 {
	x := make([]float64, g.n)
	widths := make([]float64, len(g.layers))
	maxW := 0.0
	for i, l := range g.layers {
		cur := 0.0
		for k, v := range l {
			if k > 0 {
				cur += g.sep(l[k-1], v, nodeSep)
			}
			x[v] = cur
		}
		if len(l) > 0 {
			widths[i] = cur
		}
		if widths[i] > maxW {
			maxW = widths[i]
		}
	}
	for i, l := range g.layers {
		off := (maxW - widths[i]) / 2
		for _, v := range l {
			x[v] += off
		}
	}
	return x
}

// markConflicts finds type-1 conflicts: non-inner segments that cross an
// inner segment (both ends virtual). Inner segments win alignment so long
// edges stay straight. Keys are [upperNode, lowerNode].
func (g *pg) markConflicts() map[[2]int]bool {
	conf := map[[2]int]bool{}
	for i := 0; i+1 < len(g.layers); i++ {
		type seg struct{ u, v int }
		var inner, outer []seg
		for _, u := range g.layers[i] {
			for _, e := range g.down[u] {
				s := seg{u, e.to}
				if g.virtual[u] && g.virtual[e.to] {
					inner = append(inner, s)
				} else {
					outer = append(outer, s)
				}
			}
		}
		for _, a := range inner {
			for _, b := range outer {
				pa, pb := g.pos[a.u], g.pos[b.u]
				qa, qb := g.pos[a.v], g.pos[b.v]
				if (pa < pb && qa > qb) || (pa > pb && qa < qb) {
					conf[[2]int{b.u, b.v}] = true
				}
			}
		}
	}
	return conf
}

// bkOnce computes one of the four Brandes–Köpf layouts. vertUp processes
// layers bottom-up, rightToLeft mirrors the in-layer direction.
func (g *pg) bkOnce(conf map[[2]int]bool, nodeSep float64, vertUp, rightToLeft bool) []float64 {
	layers := make([][]int, len(g.layers))
	for i, l := range g.layers {
		c := append([]int(nil), l...)
		if rightToLeft {
			for a, b := 0, len(c)-1; a < b; a, b = a+1, b-1 {
				c[a], c[b] = c[b], c[a]
			}
		}
		layers[i] = c
	}
	if vertUp {
		for a, b := 0, len(layers)-1; a < b; a, b = a+1, b-1 {
			layers[a], layers[b] = layers[b], layers[a]
		}
	}
	pos := make([]int, g.n)
	for _, l := range layers {
		for k, v := range l {
			pos[v] = k
		}
	}
	nb := func(v int) []int {
		src := g.up[v]
		if vertUp {
			src = g.down[v]
		}
		r := make([]int, len(src))
		for i, e := range src {
			r[i] = e.to
		}
		sort.Slice(r, func(a, b int) bool { return pos[r[a]] < pos[r[b]] })
		return r
	}
	isConf := func(u, v int) bool {
		if vertUp {
			return conf[[2]int{v, u}]
		}
		return conf[[2]int{u, v}]
	}
	root := make([]int, g.n)
	align := make([]int, g.n)
	for v := range root {
		root[v], align[v] = v, v
	}
	for _, l := range layers {
		r := -1
		for _, v := range l {
			ns := nb(v)
			if len(ns) == 0 {
				continue
			}
			lo, hi := (len(ns)-1)/2, len(ns)/2
			for m := lo; m <= hi; m++ {
				u := ns[m]
				if align[v] == v && !isConf(u, v) && r < pos[u] {
					align[u] = v
					root[v] = root[u]
					align[v] = root[v]
					r = pos[u]
				}
			}
		}
	}
	// horizontal compaction
	x := make([]float64, g.n)
	placed := make([]bool, g.n)
	sink := make([]int, g.n)
	shift := make([]float64, g.n)
	for v := range sink {
		sink[v] = v
		shift[v] = math.Inf(1)
	}
	layerOf := make([]int, g.n)
	for i, l := range layers {
		for _, v := range l {
			layerOf[v] = i
		}
	}
	var place func(v int)
	place = func(v int) {
		if placed[v] {
			return
		}
		placed[v] = true
		x[v] = 0
		w := v
		for {
			if pos[w] > 0 {
				pw := layers[layerOf[w]][pos[w]-1]
				u := root[pw]
				place(u)
				if sink[v] == v {
					sink[v] = sink[u]
				}
				d := g.sep(w, pw, nodeSep)
				if sink[v] != sink[u] {
					if s := x[v] - x[u] - d; s < shift[sink[u]] {
						shift[sink[u]] = s
					}
				} else if c := x[u] + d; c > x[v] {
					x[v] = c
				}
			}
			w = align[w]
			if w == v {
				break
			}
		}
	}
	for v := 0; v < g.n; v++ {
		if root[v] == v {
			place(v)
		}
	}
	out := make([]float64, g.n)
	for v := 0; v < g.n; v++ {
		r := root[v]
		out[v] = x[r]
		if s := shift[sink[r]]; !math.IsInf(s, 1) {
			out[v] += s
		}
	}
	if rightToLeft {
		for v := range out {
			out[v] = -out[v]
		}
	}
	return out
}

// bkCoords runs the four alignments, aligns them to the narrowest and takes
// the average of the two median candidates per node.
func (g *pg) bkCoords(nodeSep float64) []float64 {
	conf := g.markConflicts()
	var res [4][]float64
	i := 0
	for _, up := range []bool{false, true} {
		for _, rl := range []bool{false, true} {
			res[i] = g.bkOnce(conf, nodeSep, up, rl)
			i++
		}
	}
	extent := func(x []float64) (lo, hi float64) {
		lo, hi = math.Inf(1), math.Inf(-1)
		for v := 0; v < g.n; v++ {
			if a := x[v] - g.w[v]/2; a < lo {
				lo = a
			}
			if b := x[v] + g.w[v]/2; b > hi {
				hi = b
			}
		}
		return
	}
	narrow, nw := 0, math.Inf(1)
	for k := range res {
		lo, hi := extent(res[k])
		if hi-lo < nw {
			nw, narrow = hi-lo, k
		}
	}
	nlo, nhi := extent(res[narrow])
	for k := range res {
		lo, hi := extent(res[k])
		var d float64
		if k%2 == 0 { // left-aligned layouts
			d = nlo - lo
		} else {
			d = nhi - hi
		}
		for v := range res[k] {
			res[k][v] += d
		}
	}
	out := make([]float64, g.n)
	for v := 0; v < g.n; v++ {
		c := []float64{res[0][v], res[1][v], res[2][v], res[3][v]}
		sort.Float64s(c)
		out[v] = (c[1] + c[2]) / 2
	}
	return out
}

// enforceSeparation is a safety net: sweeping each layer left→right makes
// sure the averaged coordinates never overlap.
func (g *pg) enforceSeparation(x []float64, nodeSep float64) {
	for _, l := range g.layers {
		for k := 1; k < len(l); k++ {
			if min := x[l[k-1]] + g.sep(l[k-1], l[k], nodeSep); x[l[k]] < min {
				x[l[k]] = min
			}
		}
	}
}
