package layout

import "sort"

// feedbackSet returns, for each edge index, whether it must be reversed so
// that the graph becomes acyclic. Self-loops are never reversed (handled
// separately).
func feedbackSet(n int, edges []InEdge, strategy string) []bool {
	if strategy == "dfs" {
		return dfsFeedback(n, edges)
	}
	return greedyFeedback(n, edges)
}

// greedyFeedback is the Eades–Lin–Smyth heuristic: repeatedly peel sinks to
// the back, sources to the front, and otherwise take the node with maximal
// (out-weight − in-weight) to the front. Edges pointing backwards in the
// resulting sequence are reversed.
func greedyFeedback(n int, edges []InEdge) []bool {
	out := make([][]int, n)
	in := make([][]int, n)
	for i, e := range edges {
		if e.From == e.To {
			continue
		}
		out[e.From] = append(out[e.From], i)
		in[e.To] = append(in[e.To], i)
	}
	removed := make([]bool, n)
	outW := make([]int, n)
	inW := make([]int, n)
	for _, e := range edges {
		if e.From == e.To {
			continue
		}
		outW[e.From] += e.Weight
		inW[e.To] += e.Weight
	}
	outDeg := make([]int, n)
	inDeg := make([]int, n)
	for v := 0; v < n; v++ {
		outDeg[v], inDeg[v] = len(out[v]), len(in[v])
	}
	var front, back []int
	remove := func(v int) {
		removed[v] = true
		for _, ei := range out[v] {
			w := edges[ei].To
			if !removed[w] {
				inDeg[w]--
				inW[w] -= edges[ei].Weight
			}
		}
		for _, ei := range in[v] {
			w := edges[ei].From
			if !removed[w] {
				outDeg[w]--
				outW[w] -= edges[ei].Weight
			}
		}
	}
	left := n
	for left > 0 {
		progress := true
		for progress {
			progress = false
			for v := 0; v < n; v++ {
				if removed[v] {
					continue
				}
				if outDeg[v] == 0 {
					back = append(back, v)
					remove(v)
					left--
					progress = true
				} else if inDeg[v] == 0 {
					front = append(front, v)
					remove(v)
					left--
					progress = true
				}
			}
		}
		if left == 0 {
			break
		}
		best, bd := -1, 0
		for v := 0; v < n; v++ {
			if removed[v] {
				continue
			}
			if d := outW[v] - inW[v]; best < 0 || d > bd {
				best, bd = v, d
			}
		}
		front = append(front, best)
		remove(best)
		left--
	}
	seq := make([]int, 0, n)
	seq = append(seq, front...)
	for i := len(back) - 1; i >= 0; i-- {
		seq = append(seq, back[i])
	}
	pos := make([]int, n)
	for i, v := range seq {
		pos[v] = i
	}
	rev := make([]bool, len(edges))
	for i, e := range edges {
		if e.From != e.To && pos[e.From] > pos[e.To] {
			rev[i] = true
		}
	}
	return rev
}

// dfsFeedback reverses back edges found by a depth-first search (roots in
// index order, neighbours in edge order). Deterministic and simple baseline.
func dfsFeedback(n int, edges []InEdge) []bool {
	out := make([][]int, n)
	for i, e := range edges {
		if e.From != e.To {
			out[e.From] = append(out[e.From], i)
		}
	}
	for v := range out {
		sort.Ints(out[v])
	}
	state := make([]int8, n) // 0 new, 1 on stack, 2 done
	rev := make([]bool, len(edges))
	type frame struct{ v, i int }
	for r := 0; r < n; r++ {
		if state[r] != 0 {
			continue
		}
		st := []frame{{r, 0}}
		state[r] = 1
		for len(st) > 0 {
			f := &st[len(st)-1]
			if f.i == len(out[f.v]) {
				state[f.v] = 2
				st = st[:len(st)-1]
				continue
			}
			ei := out[f.v][f.i]
			f.i++
			w := edges[ei].To
			switch state[w] {
			case 1:
				rev[ei] = true
			case 0:
				state[w] = 1
				st = append(st, frame{w, 0})
			}
		}
	}
	return rev
}
