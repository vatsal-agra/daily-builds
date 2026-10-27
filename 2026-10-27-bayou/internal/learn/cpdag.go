package learn

import "fmt"

// Edge states in a CPDAG matrix.
const (
	None = iota
	Fwd  // a → b (stored at [a][b])
	Bwd  // a ← b
	Und  // a — b
)

// CPDAG returns the completed partially directed acyclic graph of the
// Markov-equivalence class of the DAG given by parent lists: the skeleton, with
// exactly those edges directed that every equivalent DAG directs (v-structures
// plus Meek's rules R1–R3). m[a][b] is None, Fwd (a→b), Bwd (a←b) or Und.
func CPDAG(parents [][]int) [][]int {
	n := len(parents)
	adj := make([][]bool, n)
	dir := make([][]bool, n) // dir[a][b]: a → b is compelled
	for i := range adj {
		adj[i] = make([]bool, n)
		dir[i] = make([]bool, n)
	}
	for v, ps := range parents {
		for _, p := range ps {
			adj[p][v], adj[v][p] = true, true
		}
	}
	for v, ps := range parents {
		for i, a := range ps {
			for _, b := range ps[i+1:] {
				if !adj[a][b] {
					dir[a][v], dir[b][v] = true, true
				}
			}
		}
	}
	und := func(a, b int) bool { return adj[a][b] && !dir[a][b] && !dir[b][a] }
	for changed := true; changed; {
		changed = false
		for a := 0; a < n; a++ {
			for b := 0; b < n; b++ {
				if a == b || !und(a, b) {
					continue
				}
				// orient a → b if a rule fires
				fire := false
				for c := 0; c < n && !fire; c++ {
					// R1: c → a, c and b non-adjacent
					if dir[c][a] && !adj[c][b] && c != b {
						fire = true
					}
					// R2: a → c → b
					if dir[a][c] && dir[c][b] {
						fire = true
					}
				}
				// R3: a — c, a — d, c → b, d → b, c and d non-adjacent
				for c := 0; c < n && !fire; c++ {
					for d := c + 1; d < n && !fire; d++ {
						if und(a, c) && und(a, d) && dir[c][b] && dir[d][b] && !adj[c][d] {
							fire = true
						}
					}
				}
				if fire {
					dir[a][b] = true
					changed = true
				}
			}
		}
	}
	m := make([][]int, n)
	for a := range m {
		m[a] = make([]int, n)
		for b := range m[a] {
			switch {
			case !adj[a][b]:
				m[a][b] = None
			case dir[a][b]:
				m[a][b] = Fwd
			case dir[b][a]:
				m[a][b] = Bwd
			default:
				m[a][b] = Und
			}
		}
	}
	return m
}

// GraphDiff compares two structures through their CPDAGs, so that equivalent
// DAGs count as identical.
type GraphDiff struct {
	SHD         int // structural Hamming distance between the CPDAGs
	Missing     int // skeleton edges of the truth absent from the learned graph
	Extra       int // learned skeleton edges absent from the truth
	Misoriented int // shared edges whose direction (or undirectedness) differs
	TrueEdges   int
}

// Compare computes the diff between truth and learned parent structures.
func Compare(truth, learned [][]int) (GraphDiff, error) {
	if len(truth) != len(learned) {
		return GraphDiff{}, fmt.Errorf("structures have %d and %d variables", len(truth), len(learned))
	}
	a, b := CPDAG(truth), CPDAG(learned)
	var d GraphDiff
	for i := range a {
		for j := i + 1; j < len(a); j++ {
			x, y := a[i][j], b[i][j]
			if x != None {
				d.TrueEdges++
			}
			if x == y {
				continue
			}
			d.SHD++
			switch {
			case x != None && y == None:
				d.Missing++
			case x == None && y != None:
				d.Extra++
			default:
				d.Misoriented++
			}
		}
	}
	return d, nil
}
