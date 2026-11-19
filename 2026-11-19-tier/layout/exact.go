package layout

// OptimalCrossings computes the exact minimum number of edge crossings over
// all vertex orderings of the proper layered graph (after cycle removal,
// layering and dummy insertion with the given options), summed over connected
// components. It is a dynamic program over permutations of consecutive layers,
// so it only works when layers are narrow; ok=false means "too large".
func OptimalCrossings(in Graph, o Options) (best int, ok bool, err error) {
	pr, err := prepare(in, o)
	if err != nil {
		return 0, false, err
	}
	total := 0
	for _, c := range pr.comps {
		v, fine := c.p.optimalCrossings()
		if !fine {
			return 0, false, nil
		}
		total += v
	}
	return total, true, nil
}

func permutations(a []int) [][]int {
	var out [][]int
	var rec func(k int)
	b := append([]int(nil), a...)
	rec = func(k int) {
		if k == len(b) {
			out = append(out, append([]int(nil), b...))
			return
		}
		for i := k; i < len(b); i++ {
			b[k], b[i] = b[i], b[k]
			rec(k + 1)
			b[k], b[i] = b[i], b[k]
		}
	}
	rec(0)
	return out
}

func factorial(n int) int {
	f := 1
	for i := 2; i <= n; i++ {
		f *= i
	}
	return f
}

// crossBetweenPerms counts crossings between layer i (ordering a) and i+1 (ordering b).
func (g *pg) crossBetweenPerms(a, b []int, pa, pb []int) int {
	for k, v := range a {
		pa[v] = k
	}
	for k, v := range b {
		pb[v] = k
	}
	type pr struct{ x, y int }
	var es []pr
	for _, v := range a {
		for _, e := range g.down[v] {
			es = append(es, pr{pa[v], pb[e.to]})
		}
	}
	c := 0
	for i := 0; i < len(es); i++ {
		for j := i + 1; j < len(es); j++ {
			if (es[i].x < es[j].x && es[i].y > es[j].y) || (es[i].x > es[j].x && es[i].y < es[j].y) {
				c++
			}
		}
	}
	return c
}

func (g *pg) optimalCrossings() (int, bool) {
	const budget = 4_000_000
	work := 0
	for i := 0; i+1 < len(g.layers); i++ {
		work += factorial(min(len(g.layers[i]), 9)) * factorial(min(len(g.layers[i+1]), 9))
		if len(g.layers[i]) > 8 || len(g.layers[i+1]) > 8 || work > budget {
			return 0, false
		}
	}
	if len(g.layers) < 2 {
		return 0, true
	}
	pa := make([]int, g.n)
	pb := make([]int, g.n)
	prev := permutations(g.layers[0])
	cost := make([]int, len(prev))
	for i := 0; i+1 < len(g.layers); i++ {
		next := permutations(g.layers[i+1])
		nc := make([]int, len(next))
		for j, nb := range next {
			best := -1
			for k, pa2 := range prev {
				c := cost[k] + g.crossBetweenPerms(pa2, nb, pa, pb)
				if best < 0 || c < best {
					best = c
				}
			}
			nc[j] = best
		}
		prev, cost = next, nc
	}
	m := cost[0]
	for _, c := range cost {
		if c < m {
			m = c
		}
	}
	return m, true
}
