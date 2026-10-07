package gen

import (
	"fmt"
	"math/big"
	"testing"

	"dantzig/internal/bb"
	"dantzig/internal/model"
)

func solve(t *testing.T, m *model.Model) *bb.Result {
	t.Helper()
	if err := m.Validate(); err != nil {
		t.Fatal(err)
	}
	r := bb.Solve(m, bb.Options{})
	if r.Status != bb.Optimal || !r.Certified {
		t.Fatalf("status %s certified=%v note=%s", r.Status, r.Certified, r.Note)
	}
	if _, err := bb.Check(m, r.Proof); err != nil {
		t.Fatalf("checker rejected: %v", err)
	}
	return r
}

func objInt(t *testing.T, r *bb.Result) int64 {
	if !r.Obj.IsInt() {
		t.Fatalf("non-integer objective %s", r.Obj.RatString())
	}
	return r.Obj.Num().Int64()
}

func coef(m *model.Model, row, v int) int64 {
	for _, e := range m.Rows[row].Entries {
		if e.J == v {
			return e.V.Num().Int64()
		}
	}
	return 0
}

func TestKnapsackAgainstBruteForce(t *testing.T) {
	for seed := int64(1); seed <= 12; seed++ {
		for _, dims := range []int{1, 2, 3} {
			n := 12 + int(seed%3)
			m := Knapsack(n, seed, dims)
			best := int64(-1)
			for mask := 0; mask < 1<<n; mask++ {
				ok := true
				for d := 0; d < dims && ok; d++ {
					var w int64
					for i := 0; i < n; i++ {
						if mask>>i&1 == 1 {
							w += coef(m, d, i)
						}
					}
					ok = w <= m.Rows[d].Hi.Num().Int64()
				}
				if !ok {
					continue
				}
				var v int64
				for i := 0; i < n; i++ {
					if mask>>i&1 == 1 {
						v += m.Vars[i].Obj.Num().Int64()
					}
				}
				if v > best {
					best = v
				}
			}
			if got := objInt(t, solve(t, m)); got != best {
				t.Fatalf("knapsack n=%d seed=%d dims=%d: got %d want %d", n, seed, dims, got, best)
			}
		}
	}
}

func permutations(n int, f func([]int)) {
	p := make([]int, n)
	for i := range p {
		p[i] = i
	}
	var rec func(k int)
	rec = func(k int) {
		if k == n {
			f(p)
			return
		}
		for i := k; i < n; i++ {
			p[k], p[i] = p[i], p[k]
			rec(k + 1)
			p[k], p[i] = p[i], p[k]
		}
	}
	rec(0)
}

func TestAssignmentAgainstBruteForce(t *testing.T) {
	for seed := int64(1); seed <= 10; seed++ {
		n := 4 + int(seed%4)
		m := Assignment(n, seed)
		best := int64(1 << 60)
		permutations(n, func(p []int) {
			var c int64
			for i, j := range p {
				c += m.Vars[i*n+j].Obj.Num().Int64()
			}
			if c < best {
				best = c
			}
		})
		if got := objInt(t, solve(t, m)); got != best {
			t.Fatalf("assignment n=%d seed=%d: %d vs %d", n, seed, got, best)
		}
	}
}

func TestTSPAgainstBruteForce(t *testing.T) {
	for seed := int64(1); seed <= 8; seed++ {
		n := 5 + int(seed%3)
		pts := TSPPoints(n, seed)
		best := int64(1 << 60)
		permutations(n-1, func(p []int) {
			prev, c := 0, int64(0)
			for _, q := range p {
				c += TSPDist(pts[prev], pts[q+1])
				prev = q + 1
			}
			c += TSPDist(pts[prev], pts[0])
			if c < best {
				best = c
			}
		})
		m := TSP(n, seed)
		r := solve(t, m)
		if got := objInt(t, r); got != best {
			t.Fatalf("tsp n=%d seed=%d: %d vs %d", n, seed, got, best)
		}
		// the returned arcs must form a single Hamiltonian cycle
		next := map[int]int{}
		for j, v := range m.Vars {
			var a, b int
			if _, err := fmt.Sscanf(v.Name, "x_%d_%d", &a, &b); err == nil && r.X[j].Sign() != 0 {
				next[a-1] = b - 1
			}
		}
		at, steps := 0, 0
		for {
			at = next[at]
			steps++
			if at == 0 || steps > n {
				break
			}
		}
		if steps != n {
			t.Fatalf("tsp tour is not Hamiltonian (%d steps for %d cities)", steps, n)
		}
	}
}

func TestSetCoverAgainstBruteForce(t *testing.T) {
	for seed := int64(1); seed <= 10; seed++ {
		m := SetCover(10, 12, seed)
		ns := len(m.Vars)
		best := int64(1 << 60)
		for mask := 0; mask < 1<<ns; mask++ {
			ok := true
			for e := range m.Rows {
				cov := false
				for _, en := range m.Rows[e].Entries {
					if mask>>en.J&1 == 1 {
						cov = true
					}
				}
				if !cov {
					ok = false
					break
				}
			}
			if !ok {
				continue
			}
			var c int64
			for s := 0; s < ns; s++ {
				if mask>>s&1 == 1 {
					c += m.Vars[s].Obj.Num().Int64()
				}
			}
			if c < best {
				best = c
			}
		}
		if got := objInt(t, solve(t, m)); got != best {
			t.Fatalf("setcover seed=%d: %d vs %d", seed, got, best)
		}
	}
}

func TestFacilityAgainstBruteForce(t *testing.T) {
	for seed := int64(1); seed <= 8; seed++ {
		f, c := 4, 7
		m := Facility(f, c, seed)
		best := int64(1 << 60)
		for mask := 1; mask < 1<<f; mask++ {
			var cost int64
			for i := 0; i < f; i++ {
				if mask>>i&1 == 1 {
					cost += m.Vars[i].Obj.Num().Int64()
				}
			}
			for j := 0; j < c; j++ {
				cheap := int64(1 << 60)
				for i := 0; i < f; i++ {
					if mask>>i&1 == 1 {
						if v := m.Vars[f+i*c+j].Obj.Num().Int64(); v < cheap {
							cheap = v
						}
					}
				}
				cost += cheap
			}
			if cost < best {
				best = cost
			}
		}
		if got := objInt(t, solve(t, m)); got != best {
			t.Fatalf("facility seed=%d: %d vs %d", seed, got, best)
		}
	}
}

func TestSudokuSolutionsAreValid(t *testing.T) {
	for _, hard := range []bool{false, true} {
		m := Sudoku(hard)
		r := solve(t, m)
		var g [9][9]int
		for j, v := range m.Vars {
			var a, b, d int
			fmt.Sscanf(v.Name, "x_%d_%d_%d", &a, &b, &d)
			if r.X[j].Cmp(big.NewRat(1, 1)) == 0 {
				if g[a-1][b-1] != 0 {
					t.Fatal("cell filled twice")
				}
				g[a-1][b-1] = d
			}
		}
		for i := 0; i < 9; i++ {
			var row, col, box [10]bool
			for j := 0; j < 9; j++ {
				for _, p := range []struct {
					seen *[10]bool
					v    int
				}{{&row, g[i][j]}, {&col, g[j][i]}, {&box, g[i/3*3+j/3][i%3*3+j%3]}} {
					if p.v < 1 || p.seen[p.v] {
						t.Fatalf("hard=%v: invalid sudoku grid %v", hard, g)
					}
					p.seen[p.v] = true
				}
			}
		}
		for i, line := range SudokuGivens(hard) {
			for j, ch := range line {
				if ch != '.' && g[i][j] != int(ch-'0') {
					t.Fatalf("given at (%d,%d) overwritten", i+1, j+1)
				}
			}
		}
	}
}

func TestTransportAndDiet(t *testing.T) {
	for seed := int64(1); seed <= 5; seed++ {
		m := Transport(4, 6, seed)
		solve(t, m)
	}
	solve(t, Diet())
}

func TestBuildValidation(t *testing.T) {
	bad := []struct {
		kind string
		args []int
	}{{"tsp", []int{2}}, {"tsp", nil}, {"knapsack", []int{0}}, {"assignment", []int{99}}, {"nope", nil}, {"setcover", []int{5}}, {"facility", []int{0, 3}}}
	for _, b := range bad {
		if _, err := Build(b.kind, b.args); err == nil {
			t.Errorf("Build(%s,%v) accepted bad input", b.kind, b.args)
		}
	}
	for _, k := range Kinds {
		args := []int{6, 8, 1}
		if k.Name == "tsp" {
			args = []int{5, 1}
		}
		if _, err := Build(k.Name, args); err != nil {
			t.Errorf("Build(%s): %v", k.Name, err)
		}
	}
}
