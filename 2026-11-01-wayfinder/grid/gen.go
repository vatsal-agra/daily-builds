package grid

import (
	"fmt"
	"math/rand"
)

// Kinds of generated maps.
var Kinds = []string{"random", "maze", "rooms", "caves", "open"}

// Generate builds a seeded map of the given kind. density is the wall fraction
// for "random" (0..0.6). terrain>0 overlays weighted terrain patches (mud,
// swamp...) covering roughly that fraction of open cells. Start and Goal are
// always placed in the same connected component, far apart.
func Generate(kind string, w, h int, seed int64, density float64, terrain float64) (*Grid, error) {
	if w < 3 || h < 3 {
		return nil, fmt.Errorf("map must be at least 3x3, got %dx%d", w, h)
	}
	if w > 4096 || h > 4096 {
		return nil, fmt.Errorf("map too large (max 4096x4096)")
	}
	if density < 0 || density > 0.6 {
		return nil, fmt.Errorf("density must be within 0..0.6, got %v", density)
	}
	if terrain < 0 || terrain > 1 {
		return nil, fmt.Errorf("terrain must be within 0..1, got %v", terrain)
	}
	rng := rand.New(rand.NewSource(seed))
	g := New(w, h)
	switch kind {
	case "open":
	case "random":
		for i := range g.Cost {
			if rng.Float64() < density {
				g.Cost[i] = 0
			}
		}
	case "maze":
		genMaze(g, rng)
	case "rooms":
		genRooms(g, rng)
	case "caves":
		genCaves(g, rng)
	default:
		return nil, fmt.Errorf("unknown map kind %q (want one of %v)", kind, Kinds)
	}
	if terrain > 0 {
		overlayTerrain(g, rng, terrain)
	}
	if err := g.PlaceEndpoints(rng); err != nil {
		return nil, err
	}
	return g, nil
}

func genMaze(g *Grid, rng *rand.Rand) {
	for i := range g.Cost {
		g.Cost[i] = 0
	}
	// Recursive-backtracker on odd cells.
	type c struct{ x, y int }
	stack := []c{{1, 1}}
	g.Set(1, 1, 1)
	for len(stack) > 0 {
		cur := stack[len(stack)-1]
		var nb []c
		for _, d := range [][2]int{{2, 0}, {-2, 0}, {0, 2}, {0, -2}} {
			nx, ny := cur.x+d[0], cur.y+d[1]
			if nx > 0 && ny > 0 && nx < g.W-1 && ny < g.H-1 && g.At(nx, ny) == 0 {
				nb = append(nb, c{nx, ny})
			}
		}
		if len(nb) == 0 {
			stack = stack[:len(stack)-1]
			continue
		}
		n := nb[rng.Intn(len(nb))]
		g.Set(n.x, n.y, 1)
		g.Set((cur.x+n.x)/2, (cur.y+n.y)/2, 1)
		stack = append(stack, n)
	}
	// Knock a few extra holes so there are loops (otherwise every route is unique).
	for i := 0; i < g.W*g.H/60; i++ {
		x, y := 1+rng.Intn(g.W-2), 1+rng.Intn(g.H-2)
		g.Set(x, y, 1)
	}
}

func genRooms(g *Grid, rng *rand.Rand) {
	for i := range g.Cost {
		g.Cost[i] = 0
	}
	type room struct{ x0, y0, x1, y1 int }
	var rooms []room
	for try := 0; try < g.W*g.H/12 && try < 400; try++ {
		rw, rh := 3+rng.Intn(max(1, g.W/6)), 3+rng.Intn(max(1, g.H/6))
		if rw >= g.W-2 || rh >= g.H-2 {
			continue
		}
		x0, y0 := 1+rng.Intn(g.W-rw-1), 1+rng.Intn(g.H-rh-1)
		r := room{x0, y0, x0 + rw - 1, y0 + rh - 1}
		ok := true
		for _, o := range rooms {
			if r.x0 <= o.x1+1 && r.x1 >= o.x0-1 && r.y0 <= o.y1+1 && r.y1 >= o.y0-1 {
				ok = false
				break
			}
		}
		if !ok {
			continue
		}
		rooms = append(rooms, r)
		for y := r.y0; y <= r.y1; y++ {
			for x := r.x0; x <= r.x1; x++ {
				g.Set(x, y, 1)
			}
		}
	}
	// Connect consecutive rooms with L-shaped corridors.
	for i := 1; i < len(rooms); i++ {
		a, b := rooms[i-1], rooms[i]
		ax, ay := (a.x0+a.x1)/2, (a.y0+a.y1)/2
		bx, by := (b.x0+b.x1)/2, (b.y0+b.y1)/2
		for x := min(ax, bx); x <= max(ax, bx); x++ {
			g.Set(x, ay, 1)
		}
		for y := min(ay, by); y <= max(ay, by); y++ {
			g.Set(bx, y, 1)
		}
	}
}

func genCaves(g *Grid, rng *rand.Rand) {
	for i := range g.Cost {
		if rng.Float64() < 0.45 {
			g.Cost[i] = 0
		}
	}
	for it := 0; it < 5; it++ {
		next := make([]uint8, len(g.Cost))
		for y := 0; y < g.H; y++ {
			for x := 0; x < g.W; x++ {
				walls := 0
				for dy := -1; dy <= 1; dy++ {
					for dx := -1; dx <= 1; dx++ {
						if !g.Open(x+dx, y+dy) {
							walls++
						}
					}
				}
				if walls >= 5 {
					next[y*g.W+x] = 0
				} else {
					next[y*g.W+x] = 1
				}
			}
		}
		g.Cost = next
	}
}

func overlayTerrain(g *Grid, rng *rand.Rand, frac float64) {
	levels := []uint8{2, 3, 5, 7, 9}
	target := int(frac * float64(g.W*g.H))
	painted := 0
	for guard := 0; painted < target && guard < 10000; guard++ {
		cx, cy := rng.Intn(g.W), rng.Intn(g.H)
		r := 1 + rng.Intn(max(2, min(g.W, g.H)/8))
		lv := levels[rng.Intn(len(levels))]
		for y := cy - r; y <= cy+r; y++ {
			for x := cx - r; x <= cx+r; x++ {
				if g.Open(x, y) && (x-cx)*(x-cx)+(y-cy)*(y-cy) <= r*r {
					g.Set(x, y, lv)
					painted++
				}
			}
		}
	}
}

// Component floods outward from p using legal moves and returns the reachable cells.
func (g *Grid) Component(p Point) []Point {
	if !g.Open(p.X, p.Y) {
		return nil
	}
	seen := make([]bool, len(g.Cost))
	seen[g.Idx(p.X, p.Y)] = true
	q := []Point{p}
	for h := 0; h < len(q); h++ {
		c := q[h]
		for _, d := range Dirs {
			if g.CanMove(c.X, c.Y, d[0], d[1]) {
				n := Point{c.X + d[0], c.Y + d[1]}
				if !seen[g.Idx(n.X, n.Y)] {
					seen[g.Idx(n.X, n.Y)] = true
					q = append(q, n)
				}
			}
		}
	}
	return q
}

// PlaceEndpoints picks a start in the largest component and the farthest-ish goal.
func (g *Grid) PlaceEndpoints(rng *rand.Rand) error {
	var best []Point
	seen := make([]bool, len(g.Cost))
	for i, c := range g.Cost {
		if c == 0 || seen[i] {
			continue
		}
		comp := g.Component(g.Pt(i))
		for _, p := range comp {
			seen[g.Idx(p.X, p.Y)] = true
		}
		if len(comp) > len(best) {
			best = comp
		}
	}
	if len(best) < 2 {
		return fmt.Errorf("generated map has no connected area with two cells; try a lower density")
	}
	s := best[rng.Intn(len(best))]
	// goal: best of 64 random candidates by octile distance
	gl := best[rng.Intn(len(best))]
	for i := 0; i < 64; i++ {
		c := best[rng.Intn(len(best))]
		if Octile(s, c) > Octile(s, gl) {
			gl = c
		}
	}
	if gl == s {
		return fmt.Errorf("could not place distinct start and goal")
	}
	g.Start, g.Goal = s, gl
	return nil
}
