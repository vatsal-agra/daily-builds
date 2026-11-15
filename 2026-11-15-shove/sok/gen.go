package sok

import (
	"errors"
	"fmt"
	"math/rand"
	"sort"
)

// GenOptions configures the reverse-play generator.
type GenOptions struct {
	W, H      int     // grid size including the wall border (min 5x5)
	Boxes     int     // number of boxes (1..12)
	Seed      int64   // RNG seed; same options + seed => identical output
	Attempts  int     // candidate layouts to rate (hardest wins)
	Pulls     int     // random pulls per candidate (default 40*Boxes)
	WallDens  float64 // fraction of interior cells turned into wall blobs
	MinPushes int     // reject candidates whose optimal solution is shorter
	MaxNodes  int     // solver node budget per candidate (deterministic; default 60000)
}

// Generated is a rated level.
type Generated struct {
	Level    *Level
	Solution *Solution
	Rating   string
	Attempt  int // which attempt produced it
	Rated    int // how many candidates were solved & rated
}

// Rate names a difficulty band from solver effort.
func Rate(sol *Solution) string {
	switch e := sol.Expanded; {
	case e < 50:
		return "trivial"
	case e < 500:
		return "easy"
	case e < 5000:
		return "medium"
	case e < 50000:
		return "hard"
	}
	return "brutal"
}

// Validate normalises options, returning an error for impossible ones.
func (o *GenOptions) Validate() error {
	if o.W < 5 || o.H < 5 || o.W > 40 || o.H > 40 {
		return fmt.Errorf("grid must be between 5x5 and 40x40, got %dx%d", o.W, o.H)
	}
	if o.Boxes < 1 || o.Boxes > 12 {
		return fmt.Errorf("boxes must be 1..12, got %d", o.Boxes)
	}
	if (o.W-2)*(o.H-2) < 2*o.Boxes+2 {
		return fmt.Errorf("a %dx%d grid is too small for %d boxes", o.W, o.H, o.Boxes)
	}
	if o.WallDens < 0 || o.WallDens > 0.5 {
		return fmt.Errorf("wall density must be in [0, 0.5], got %.2f", o.WallDens)
	}
	if o.Attempts <= 0 {
		o.Attempts = 200
	}
	if o.Pulls <= 0 {
		o.Pulls = 40 * o.Boxes
	}
	if o.MaxNodes <= 0 {
		o.MaxNodes = 60000
	}
	return nil
}

// ErrNoCandidate is returned when no candidate met the requirements.
var ErrNoCandidate = errors.New("no candidate level met the requirements; try more attempts, fewer min-pushes, or a bigger grid")

// Generate builds levels backwards from solved positions (so every candidate is
// solvable by construction), rates each with the real solver and returns the hardest.
func Generate(o GenOptions) (*Generated, error) {
	if err := o.Validate(); err != nil {
		return nil, err
	}
	rng := rand.New(rand.NewSource(o.Seed))
	var best *Generated
	rated := 0
	for a := 1; a <= o.Attempts; a++ {
		lv := candidate(rng, o)
		if lv == nil {
			continue
		}
		sol, err := Solve(lv, Options{MaxNodes: o.MaxNodes})
		if err != nil {
			continue // too hard for the budget (or the pull walk produced a pocket); skip
		}
		rated++
		if sol.Pushes < o.MinPushes {
			continue
		}
		if best == nil || better(sol, best.Solution) {
			best = &Generated{Level: lv, Solution: sol, Attempt: a}
		}
	}
	if best == nil {
		return nil, ErrNoCandidate
	}
	best.Rated = rated
	best.Rating = Rate(best.Solution)
	best.Level.Name = fmt.Sprintf("%dx%d, %d boxes, seed %d", o.W, o.H, o.Boxes, o.Seed)
	return best, nil
}

func better(a, b *Solution) bool {
	// Difficulty = how hard the optimal solver had to work, then solution length.
	if a.Expanded != b.Expanded {
		return a.Expanded > b.Expanded
	}
	return a.Pushes > b.Pushes
}

// candidate makes a random room, drops boxes on goals, then pulls them around.
func candidate(rng *rand.Rand, o GenOptions) *Level {
	w, h := o.W, o.H
	n := w * h
	lv := &Level{W: w, H: h, Wall: make([]bool, n), Goal: make([]bool, n)}
	for i := range lv.Wall {
		x, y := i%w, i/w
		lv.Wall[i] = x == 0 || y == 0 || x == w-1 || y == h-1 || rng.Float64() < o.WallDens
	}
	// Keep only the largest connected floor region.
	comp := make([]int, n)
	var bestCells []int
	for i := range lv.Wall {
		if lv.Wall[i] || comp[i] != 0 {
			continue
		}
		cells := []int{i}
		comp[i] = i + 1
		for k := 0; k < len(cells); k++ {
			for d := 0; d < 4; d++ {
				m := cells[k] + delta(d, w)
				if !lv.Wall[m] && comp[m] == 0 {
					comp[m] = i + 1
					cells = append(cells, m)
				}
			}
		}
		if len(cells) > len(bestCells) {
			bestCells = cells
		}
	}
	if len(bestCells) < 2*o.Boxes+2 {
		return nil
	}
	for i := range lv.Wall {
		lv.Wall[i] = true
	}
	for _, c := range bestCells {
		lv.Wall[c] = false
	}
	sort.Ints(bestCells)
	perm := rng.Perm(len(bestCells))
	boxes := make([]int, o.Boxes)
	for i := 0; i < o.Boxes; i++ {
		c := bestCells[perm[i]]
		boxes[i] = c
		lv.Goal[c] = true
	}
	player := bestCells[perm[o.Boxes]]

	boxAt := make([]bool, n)
	for _, b := range boxes {
		boxAt[b] = true
	}
	seen := make([]int, n)
	stamp := 0
	for p := 0; p < o.Pulls; p++ {
		// region reachable by the player
		stamp++
		region := []int{player}
		seen[player] = stamp
		for k := 0; k < len(region); k++ {
			for d := 0; d < 4; d++ {
				m := region[k] + delta(d, w)
				if seen[m] != stamp && !lv.Wall[m] && !boxAt[m] {
					seen[m] = stamp
					region = append(region, m)
				}
			}
		}
		type pull struct{ x, d int }
		var opts []pull
		for _, x := range region {
			for d := 0; d < 4; d++ {
				dl := delta(d, w)
				b, back := x+dl, x-dl
				if boxAt[b] && !lv.Wall[back] && !boxAt[back] {
					opts = append(opts, pull{x, d})
				}
			}
		}
		if len(opts) == 0 {
			break
		}
		sort.Slice(opts, func(i, j int) bool {
			if opts[i].x != opts[j].x {
				return opts[i].x < opts[j].x
			}
			return opts[i].d < opts[j].d
		})
		pl := opts[rng.Intn(len(opts))]
		dl := delta(pl.d, w)
		boxAt[pl.x+dl] = false
		boxAt[pl.x] = true
		player = pl.x - dl
	}
	for i, ok := range boxAt {
		if ok {
			lv.Boxes = append(lv.Boxes, i)
		}
	}
	if len(lv.Boxes) != o.Boxes {
		return nil
	}
	for _, b := range lv.Boxes {
		if lv.Goal[b] && o.Boxes > 1 {
			return nil // keep boxes off their goals so the puzzle isn't partly pre-solved
		}
	}
	lv.Player = player
	return lv
}
