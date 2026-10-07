// Package gen builds classic optimisation models (knapsack, set cover,
// assignment, TSP, sudoku, facility location, transportation) from seeds.
package gen

import (
	"fmt"
	"math/big"
	"math/rand"
	"strings"

	"dantzig/internal/model"
)

type builder struct{ m *model.Model }

func newB(maximize bool) *builder {
	m := model.New()
	m.Maximize = maximize
	return &builder{m}
}

func (b *builder) v(name string, lo, hi *big.Rat, integer bool, obj int64) int {
	j := b.m.AddVar(name)
	b.m.Vars[j].Lo, b.m.Vars[j].Hi, b.m.Vars[j].Int = lo, hi, integer
	b.m.Vars[j].Obj = big.NewRat(obj, 1)
	return j
}

func (b *builder) bin(name string, obj int64) int {
	return b.v(name, big.NewRat(0, 1), big.NewRat(1, 1), true, obj)
}

func (b *builder) cont(name string, obj int64) int {
	return b.v(name, big.NewRat(0, 1), nil, false, obj)
}

type term struct {
	j int
	c int64
}

func (b *builder) row(name string, ts []term, lo, hi *int64) {
	r := model.Row{Name: name}
	for _, t := range ts {
		r.Entries = append(r.Entries, model.Entry{J: t.j, V: big.NewRat(t.c, 1)})
	}
	if lo != nil {
		r.Lo = big.NewRat(*lo, 1)
	}
	if hi != nil {
		r.Hi = big.NewRat(*hi, 1)
	}
	b.m.Rows = append(b.m.Rows, r)
}

func i64(v int64) *int64 { return &v }

func (b *builder) le(name string, ts []term, rhs int64) { b.row(name, ts, nil, i64(rhs)) }
func (b *builder) ge(name string, ts []term, rhs int64) { b.row(name, ts, i64(rhs), nil) }
func (b *builder) eq(name string, ts []term, rhs int64) { b.row(name, ts, i64(rhs), i64(rhs)) }

// Kinds lists the generators with their argument help.
var Kinds = []struct{ Name, Usage, Doc string }{
	{"knapsack", "knapsack N [SEED] [DIMS]", "multi-dimensional 0/1 knapsack with correlated weights"},
	{"setcover", "setcover ELEMENTS SETS [SEED]", "minimum-cost set cover"},
	{"assignment", "assignment N [SEED]", "N x N assignment problem (LP is integral)"},
	{"tsp", "tsp N [SEED]", "Euclidean travelling salesman, Miller-Tucker-Zemlin formulation"},
	{"sudoku", "sudoku [easy|hard]", "9x9 sudoku as a binary feasibility problem"},
	{"facility", "facility FACILITIES CUSTOMERS [SEED]", "uncapacitated facility location (binary open + continuous assignment)"},
	{"transport", "transport SOURCES SINKS [SEED]", "balanced transportation LP"},
	{"diet", "diet", "Stigler-style diet LP with a handful of foods"},
}

// Build constructs a model of the given kind from numeric arguments.
func Build(kind string, args []int) (*model.Model, error) {
	arg := func(i, def int) int {
		if i < len(args) {
			return args[i]
		}
		return def
	}
	need := func(k int) error {
		if len(args) < k {
			return fmt.Errorf("%s needs %d numeric argument(s)", kind, k)
		}
		return nil
	}
	for _, a := range args {
		if a < 0 {
			return nil, fmt.Errorf("arguments must be non-negative")
		}
	}
	switch kind {
	case "knapsack":
		if err := need(1); err != nil {
			return nil, err
		}
		n, dims := args[0], arg(2, 1)
		if n < 1 || n > 500 || dims < 1 || dims > 20 {
			return nil, fmt.Errorf("knapsack: need 1 <= N <= 500 and 1 <= DIMS <= 20")
		}
		return Knapsack(n, int64(arg(1, 1)), dims), nil
	case "setcover":
		if err := need(2); err != nil {
			return nil, err
		}
		if args[0] < 2 || args[1] < 2 || args[0] > 200 || args[1] > 300 {
			return nil, fmt.Errorf("setcover: need 2 <= ELEMENTS <= 200 and 2 <= SETS <= 300")
		}
		return SetCover(args[0], args[1], int64(arg(2, 1))), nil
	case "assignment":
		if err := need(1); err != nil {
			return nil, err
		}
		if args[0] < 1 || args[0] > 40 {
			return nil, fmt.Errorf("assignment: need 1 <= N <= 40")
		}
		return Assignment(args[0], int64(arg(1, 1))), nil
	case "tsp":
		if err := need(1); err != nil {
			return nil, err
		}
		if args[0] < 3 || args[0] > 14 {
			return nil, fmt.Errorf("tsp: need 3 <= N <= 14")
		}
		return TSP(args[0], int64(arg(1, 1))), nil
	case "sudoku":
		return Sudoku(arg(0, 0) == 1), nil
	case "facility":
		if err := need(2); err != nil {
			return nil, err
		}
		if args[0] < 1 || args[1] < 1 || args[0] > 30 || args[1] > 60 {
			return nil, fmt.Errorf("facility: need 1 <= FACILITIES <= 30 and 1 <= CUSTOMERS <= 60")
		}
		return Facility(args[0], args[1], int64(arg(2, 1))), nil
	case "transport":
		if err := need(2); err != nil {
			return nil, err
		}
		if args[0] < 1 || args[1] < 1 || args[0] > 40 || args[1] > 40 {
			return nil, fmt.Errorf("transport: need 1 <= SOURCES, SINKS <= 40")
		}
		return Transport(args[0], args[1], int64(arg(2, 1))), nil
	case "diet":
		return Diet(), nil
	}
	return nil, fmt.Errorf("unknown generator %q (try: dantzig gen list)", kind)
}

// Knapsack: maximise value subject to DIMS capacity rows, weights correlated with value.
func Knapsack(n int, seed int64, dims int) *model.Model {
	r := rand.New(rand.NewSource(seed))
	b := newB(true)
	vals := make([]int64, n)
	for i := range vals {
		vals[i] = int64(10 + r.Intn(90))
		b.bin(fmt.Sprintf("x%d", i+1), vals[i])
	}
	for d := 0; d < dims; d++ {
		var ts []term
		var tot int64
		for i := 0; i < n; i++ {
			w := vals[i]/2 + int64(r.Intn(30)) + 5
			tot += w
			ts = append(ts, term{i, w})
		}
		b.le(fmt.Sprintf("cap%d", d+1), ts, tot/2)
	}
	return b.m
}

// SetCover: choose sets of minimum cost so every element is covered.
func SetCover(elems, sets int, seed int64) *model.Model {
	r := rand.New(rand.NewSource(seed))
	b := newB(false)
	cover := make([][]int, elems)
	for s := 0; s < sets; s++ {
		b.bin(fmt.Sprintf("s%d", s+1), int64(3+r.Intn(18)))
		size := 2 + r.Intn(max(2, elems/4))
		for k := 0; k < size; k++ {
			e := r.Intn(elems)
			dup := false
			for _, x := range cover[e] {
				if x == s {
					dup = true
				}
			}
			if !dup {
				cover[e] = append(cover[e], s)
			}
		}
	}
	for e := 0; e < elems; e++ {
		if len(cover[e]) == 0 {
			cover[e] = append(cover[e], r.Intn(sets))
		}
		var ts []term
		for _, s := range cover[e] {
			ts = append(ts, term{s, 1})
		}
		b.ge(fmt.Sprintf("e%d", e+1), ts, 1)
	}
	return b.m
}

// Assignment: minimise total cost of a perfect matching.
func Assignment(n int, seed int64) *model.Model {
	r := rand.New(rand.NewSource(seed))
	b := newB(false)
	x := make([][]int, n)
	for i := range x {
		x[i] = make([]int, n)
		for j := range x[i] {
			x[i][j] = b.v(fmt.Sprintf("x_%d_%d", i+1, j+1), big.NewRat(0, 1), nil, true, int64(1+r.Intn(50)))
		}
	}
	for i := 0; i < n; i++ {
		var rs, cs []term
		for j := 0; j < n; j++ {
			rs = append(rs, term{x[i][j], 1})
			cs = append(cs, term{x[j][i], 1})
		}
		b.eq(fmt.Sprintf("worker%d", i+1), rs, 1)
		b.eq(fmt.Sprintf("job%d", i+1), cs, 1)
	}
	return b.m
}

// TSPPoints returns the integer city coordinates used by TSP(n, seed).
func TSPPoints(n int, seed int64) [][2]int {
	r := rand.New(rand.NewSource(seed))
	pts := make([][2]int, n)
	for i := range pts {
		pts[i] = [2]int{r.Intn(100), r.Intn(100)}
	}
	return pts
}

// TSPDist is the rounded Euclidean distance.
func TSPDist(a, b [2]int) int64 {
	dx, dy := float64(a[0]-b[0]), float64(a[1]-b[1])
	return int64(sqrt(dx*dx+dy*dy) + 0.5)
}

func sqrt(v float64) float64 {
	z := v
	if z == 0 {
		return 0
	}
	for i := 0; i < 60; i++ {
		z = (z + v/z) / 2
	}
	return z
}

// TSP: Miller-Tucker-Zemlin subtour elimination.
func TSP(n int, seed int64) *model.Model {
	pts := TSPPoints(n, seed)
	b := newB(false)
	x := make([][]int, n)
	for i := range x {
		x[i] = make([]int, n)
		for j := range x[i] {
			if i != j {
				x[i][j] = b.bin(fmt.Sprintf("x_%d_%d", i+1, j+1), TSPDist(pts[i], pts[j]))
			}
		}
	}
	u := make([]int, n)
	for i := 1; i < n; i++ {
		u[i] = b.v(fmt.Sprintf("u%d", i+1), big.NewRat(1, 1), big.NewRat(int64(n-1), 1), false, 0)
	}
	for i := 0; i < n; i++ {
		var out, in []term
		for j := 0; j < n; j++ {
			if i != j {
				out = append(out, term{x[i][j], 1})
				in = append(in, term{x[j][i], 1})
			}
		}
		b.eq(fmt.Sprintf("out%d", i+1), out, 1)
		b.eq(fmt.Sprintf("in%d", i+1), in, 1)
	}
	for i := 1; i < n; i++ {
		for j := 1; j < n; j++ {
			if i != j {
				b.le(fmt.Sprintf("mtz_%d_%d", i+1, j+1),
					[]term{{u[i], 1}, {u[j], -1}, {x[i][j], int64(n - 1)}}, int64(n-2))
			}
		}
	}
	return b.m
}

var sudokuEasy = []string{
	"53..7....", "6..195...", ".98....6.", "8...6...3", "4..8.3..1", "7...2...6", ".6....28.", "...419..5", "....8..79",
}

var sudokuHard = []string{
	"8........", "..36.....", ".7..9.2..", ".5...7...", "....457..", "...1...3.", "..1....68", "..85...1.", ".9....4..",
}

// Sudoku as a 0/1 exact-cover feasibility problem with a zero objective.
func Sudoku(hard bool) *model.Model {
	grid := sudokuEasy
	if hard {
		grid = sudokuHard
	}
	b := newB(false)
	var x [9][9][9]int
	for r := 0; r < 9; r++ {
		for c := 0; c < 9; c++ {
			for d := 0; d < 9; d++ {
				x[r][c][d] = b.bin(fmt.Sprintf("x_%d_%d_%d", r+1, c+1, d+1), 0)
			}
		}
	}
	for r := 0; r < 9; r++ {
		for c := 0; c < 9; c++ {
			var ts []term
			for d := 0; d < 9; d++ {
				ts = append(ts, term{x[r][c][d], 1})
			}
			b.eq(fmt.Sprintf("cell_%d_%d", r+1, c+1), ts, 1)
		}
	}
	for d := 0; d < 9; d++ {
		for r := 0; r < 9; r++ {
			var ts []term
			for c := 0; c < 9; c++ {
				ts = append(ts, term{x[r][c][d], 1})
			}
			b.eq(fmt.Sprintf("row_%d_%d", r+1, d+1), ts, 1)
		}
		for c := 0; c < 9; c++ {
			var ts []term
			for r := 0; r < 9; r++ {
				ts = append(ts, term{x[r][c][d], 1})
			}
			b.eq(fmt.Sprintf("col_%d_%d", c+1, d+1), ts, 1)
		}
		for br := 0; br < 3; br++ {
			for bc := 0; bc < 3; bc++ {
				var ts []term
				for r := 0; r < 3; r++ {
					for c := 0; c < 3; c++ {
						ts = append(ts, term{x[br*3+r][bc*3+c][d], 1})
					}
				}
				b.eq(fmt.Sprintf("box_%d_%d_%d", br+1, bc+1, d+1), ts, 1)
			}
		}
	}
	for r := 0; r < 9; r++ {
		for c := 0; c < 9; c++ {
			if ch := grid[r][c]; ch != '.' {
				d := int(ch - '1')
				b.m.Vars[x[r][c][d]].Lo = big.NewRat(1, 1)
			}
		}
	}
	return b.m
}

// SudokuGivens returns the puzzle rows used by Sudoku.
func SudokuGivens(hard bool) []string {
	if hard {
		return sudokuHard
	}
	return sudokuEasy
}

// Facility: open facilities (binary) and serve customers fractionally.
func Facility(f, c int, seed int64) *model.Model {
	r := rand.New(rand.NewSource(seed))
	b := newB(false)
	y := make([]int, f)
	for i := range y {
		y[i] = b.bin(fmt.Sprintf("open%d", i+1), int64(40+r.Intn(60)))
	}
	x := make([][]int, f)
	for i := range x {
		x[i] = make([]int, c)
		for j := range x[i] {
			x[i][j] = b.cont(fmt.Sprintf("serve_%d_%d", i+1, j+1), int64(2+r.Intn(30)))
		}
	}
	for j := 0; j < c; j++ {
		var ts []term
		for i := 0; i < f; i++ {
			ts = append(ts, term{x[i][j], 1})
		}
		b.eq(fmt.Sprintf("demand%d", j+1), ts, 1)
	}
	for i := 0; i < f; i++ {
		for j := 0; j < c; j++ {
			b.le(fmt.Sprintf("link_%d_%d", i+1, j+1), []term{{x[i][j], 1}, {y[i], -1}}, 0)
		}
	}
	return b.m
}

// Transport: ship goods from sources to sinks at minimum cost.
func Transport(s, t int, seed int64) *model.Model {
	r := rand.New(rand.NewSource(seed))
	b := newB(false)
	supply := make([]int64, s)
	demand := make([]int64, t)
	var tot int64
	for j := range demand {
		demand[j] = int64(5 + r.Intn(20))
		tot += demand[j]
	}
	rem := tot
	for i := range supply {
		if i == s-1 {
			supply[i] = rem
		} else {
			supply[i] = rem / int64(s-i)
			if supply[i] > 1 {
				supply[i] += int64(r.Intn(3)) - 1
			}
			rem -= supply[i]
		}
	}
	x := make([][]int, s)
	for i := range x {
		x[i] = make([]int, t)
		for j := range x[i] {
			x[i][j] = b.cont(fmt.Sprintf("ship_%d_%d", i+1, j+1), int64(1+r.Intn(20)))
		}
	}
	for i := 0; i < s; i++ {
		var ts []term
		for j := 0; j < t; j++ {
			ts = append(ts, term{x[i][j], 1})
		}
		b.eq(fmt.Sprintf("supply%d", i+1), ts, supply[i])
	}
	for j := 0; j < t; j++ {
		var ts []term
		for i := 0; i < s; i++ {
			ts = append(ts, term{x[i][j], 1})
		}
		b.eq(fmt.Sprintf("demand%d", j+1), ts, demand[j])
	}
	return b.m
}

// Diet: minimise cost of foods meeting nutrient minima / maxima.
func Diet() *model.Model {
	src := `Minimize
 cost: 18 oats + 24 milk + 12 bread + 47 chicken + 8 beans + 35 cheese + 9 rice + 15 apple
Subject To
 calories: 110 oats + 120 milk + 90 bread + 180 chicken + 130 beans + 110 cheese + 205 rice + 80 apple >= 2000
 calories_max: 110 oats + 120 milk + 90 bread + 180 chicken + 130 beans + 110 cheese + 205 rice + 80 apple <= 2600
 protein: 4 oats + 8 milk + 3 bread + 30 chicken + 9 beans + 7 cheese + 4 rice + apple >= 55
 calcium: 20 oats + 290 milk + 60 bread + 15 chicken + 60 beans + 200 cheese + 20 rice + 10 apple >= 800
 fat: 3 oats + 5 milk + 1 bread + 7 chicken + 1 beans + 9 cheese + rice <= 70
 fiber: 4 oats + 3 bread + 8 beans + 1 rice + 4 apple >= 25
Bounds
 oats <= 4
 milk <= 4
 bread <= 8
 chicken <= 3
 beans <= 6
 cheese <= 3
 rice <= 4
 apple <= 5
End`
	m, err := model.Parse(strings.TrimSpace(src))
	if err != nil {
		panic(err)
	}
	return m
}
