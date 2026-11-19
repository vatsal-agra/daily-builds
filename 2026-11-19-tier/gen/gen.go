// Package gen produces reproducible random graphs in DOT for demos and tests.
package gen

import (
	"fmt"
	"math/rand"
	"strings"
)

// DOT generates a graph. kinds: layered (random DAG with levels and some long
// edges), dag (random topological DAG), cyclic (arbitrary digraph), tree.
func DOT(kind string, n int, seed int64, density float64) (string, error) {
	if n < 1 || n > 5000 {
		return "", fmt.Errorf("n must be in 1..5000, got %d", n)
	}
	if density < 0 || density > 20 {
		return "", fmt.Errorf("density must be in 0..20, got %g", density)
	}
	r := rand.New(rand.NewSource(seed))
	type pair struct{ a, b int }
	seen := map[pair]bool{}
	var es []pair
	add := func(a, b int) {
		if a == b || seen[pair{a, b}] {
			return
		}
		seen[pair{a, b}] = true
		es = append(es, pair{a, b})
	}
	m := int(float64(n) * density)
	switch kind {
	case "tree":
		for i := 1; i < n; i++ {
			add((i-1)/2+r.Intn(1+i/8)%max(1, i), i)
		}
	case "dag":
		for i := 0; i < m; i++ {
			a, b := r.Intn(n), r.Intn(n)
			if a > b {
				a, b = b, a
			}
			add(a, b)
		}
	case "cyclic":
		for i := 0; i < m; i++ {
			add(r.Intn(n), r.Intn(n))
		}
	case "layered":
		levels := 2 + n/6
		lv := make([]int, n)
		for i := range lv {
			lv[i] = i * levels / n
		}
		for i := 1; i < n; i++ { // connect everything upward at least once
			j := r.Intn(i)
			if lv[j] == lv[i] {
				continue
			}
			add(j, i)
		}
		for i := 0; i < m; i++ {
			a, b := r.Intn(n), r.Intn(n)
			if lv[a] > lv[b] {
				a, b = b, a
			}
			if lv[a] == lv[b] {
				continue
			}
			if lv[b]-lv[a] > 3 && r.Intn(3) > 0 {
				continue
			}
			add(a, b)
		}
	default:
		return "", fmt.Errorf("unknown kind %q (layered, dag, cyclic, tree)", kind)
	}
	var sb strings.Builder
	fmt.Fprintf(&sb, "digraph %s_%d_%d {\n", kind, n, seed)
	sb.WriteString("  node [shape=box];\n")
	for i := 0; i < n; i++ {
		fmt.Fprintf(&sb, "  n%d;\n", i)
	}
	for _, e := range es {
		fmt.Fprintf(&sb, "  n%d -> n%d;\n", e.a, e.b)
	}
	sb.WriteString("}\n")
	return sb.String(), nil
}
