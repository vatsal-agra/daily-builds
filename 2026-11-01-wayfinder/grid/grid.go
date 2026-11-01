// Package grid defines the map model shared by every planner: an 8-connected
// weighted grid with a strict no-corner-cutting movement rule.
package grid

import (
	"fmt"
	"math"
	"strings"
)

// Sqrt2 is the length of a diagonal step.
const Sqrt2 = math.Sqrt2

// Grid is a W×H map. Cost[y*W+x] == 0 means wall; 1..9 is terrain cost.
type Grid struct {
	W, H  int
	Cost  []uint8
	Start Point
	Goal  Point
}

// Point is a cell coordinate.
type Point struct{ X, Y int }

// New returns an all-open (cost 1) grid. Start/Goal default to opposite corners.
func New(w, h int) *Grid {
	g := &Grid{W: w, H: h, Cost: make([]uint8, w*h), Goal: Point{w - 1, h - 1}}
	for i := range g.Cost {
		g.Cost[i] = 1
	}
	return g
}

// Clone deep-copies the grid.
func (g *Grid) Clone() *Grid {
	c := *g
	c.Cost = append([]uint8(nil), g.Cost...)
	return &c
}

// Idx converts a point to a flat index.
func (g *Grid) Idx(x, y int) int { return y*g.W + x }

// Pt converts a flat index to a point.
func (g *Grid) Pt(i int) Point { return Point{i % g.W, i / g.W} }

// In reports whether (x,y) is inside the map.
func (g *Grid) In(x, y int) bool { return x >= 0 && y >= 0 && x < g.W && y < g.H }

// Open reports whether (x,y) is inside the map and not a wall.
func (g *Grid) Open(x, y int) bool { return g.In(x, y) && g.Cost[y*g.W+x] != 0 }

// At returns the cost of a cell (0 for wall or out of bounds).
func (g *Grid) At(x, y int) uint8 {
	if !g.In(x, y) {
		return 0
	}
	return g.Cost[y*g.W+x]
}

// Set assigns a cell cost (0 = wall).
func (g *Grid) Set(x, y int, c uint8) { g.Cost[y*g.W+x] = c }

// CanMove reports whether a single step (dx,dy ∈ {-1,0,1}) from (x,y) is legal.
// Diagonal steps require both orthogonal neighbours to be open.
func (g *Grid) CanMove(x, y, dx, dy int) bool {
	if !g.Open(x, y) || !g.Open(x+dx, y+dy) {
		return false
	}
	if dx != 0 && dy != 0 {
		return g.Open(x+dx, y) && g.Open(x, y+dy)
	}
	return true
}

// StepCost is the cost of a legal step from (x,y) by (dx,dy).
func (g *Grid) StepCost(x, y, dx, dy int) float64 {
	l := 1.0
	if dx != 0 && dy != 0 {
		l = Sqrt2
	}
	return l * (float64(g.At(x, y)) + float64(g.At(x+dx, y+dy))) / 2
}

// Dirs lists the eight move directions (orthogonals first).
var Dirs = [8][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}

// MinCost is the smallest open-cell cost (used to scale heuristics).
func (g *Grid) MinCost() float64 {
	m := uint8(255)
	for _, c := range g.Cost {
		if c != 0 && c < m {
			m = c
		}
	}
	if m == 255 {
		return 1
	}
	return float64(m)
}

// Uniform reports whether every open cell has the same cost (JPS precondition).
func (g *Grid) Uniform() bool {
	var first uint8
	for _, c := range g.Cost {
		if c == 0 {
			continue
		}
		if first == 0 {
			first = c
		} else if c != first {
			return false
		}
	}
	return true
}

// Octile is the octile distance between two points (unit costs).
func Octile(a, b Point) float64 {
	dx, dy := math.Abs(float64(a.X-b.X)), math.Abs(float64(a.Y-b.Y))
	return math.Max(dx, dy) + (Sqrt2-1)*math.Min(dx, dy)
}

// Euclid is the straight-line distance between two points.
func Euclid(a, b Point) float64 { return math.Hypot(float64(a.X-b.X), float64(a.Y-b.Y)) }

// PathCost sums step costs along a path of 8-adjacent points, validating legality.
func (g *Grid) PathCost(p []Point) (float64, error) {
	if len(p) == 0 {
		return 0, fmt.Errorf("empty path")
	}
	total := 0.0
	for i := 1; i < len(p); i++ {
		dx, dy := p[i].X-p[i-1].X, p[i].Y-p[i-1].Y
		if dx < -1 || dx > 1 || dy < -1 || dy > 1 || (dx == 0 && dy == 0) {
			return 0, fmt.Errorf("step %d: %v -> %v not adjacent", i, p[i-1], p[i])
		}
		if !g.CanMove(p[i-1].X, p[i-1].Y, dx, dy) {
			return 0, fmt.Errorf("step %d: illegal move %v -> %v", i, p[i-1], p[i])
		}
		total += g.StepCost(p[i-1].X, p[i-1].Y, dx, dy)
	}
	return total, nil
}

// Walls counts wall cells.
func (g *Grid) Walls() int {
	n := 0
	for _, c := range g.Cost {
		if c == 0 {
			n++
		}
	}
	return n
}

// Format renders the grid in the ASCII map format. S and G mark start/goal.
func (g *Grid) Format() string {
	var sb strings.Builder
	for y := 0; y < g.H; y++ {
		for x := 0; x < g.W; x++ {
			switch {
			case x == g.Start.X && y == g.Start.Y:
				sb.WriteByte('S')
			case x == g.Goal.X && y == g.Goal.Y:
				sb.WriteByte('G')
			default:
				sb.WriteByte(glyph(g.Cost[g.Idx(x, y)]))
			}
		}
		sb.WriteByte('\n')
	}
	return sb.String()
}

// Legend: '#' wall, '.' road(1), ',' grass(2), ';' brush(3), '~' mud(5), '%' swamp(7), '&' deep(9).
// Digits 1..9 are also accepted on input as explicit costs.
func glyph(c uint8) byte {
	switch c {
	case 0:
		return '#'
	case 1:
		return '.'
	case 2:
		return ','
	case 3:
		return ';'
	case 5:
		return '~'
	case 7:
		return '%'
	case 9:
		return '&'
	}
	return '0' + c
}

func costOf(b byte) (uint8, bool) {
	switch b {
	case '#', '@', 'T':
		return 0, true
	case '.', 'S', 'G':
		return 1, true
	case ',':
		return 2, true
	case ';':
		return 3, true
	case '~':
		return 5, true
	case '%':
		return 7, true
	case '&':
		return 9, true
	}
	if b >= '1' && b <= '9' {
		return b - '0', true
	}
	return 0, false
}

// Parse reads the ASCII map format. Blank lines and lines starting with '//' are
// ignored. All rows must have equal length; exactly one S and one G are required.
func Parse(s string) (*Grid, error) {
	var rows []string
	for _, ln := range strings.Split(strings.ReplaceAll(s, "\r\n", "\n"), "\n") {
		ln = strings.TrimRight(ln, " \t")
		if ln == "" || strings.HasPrefix(ln, "//") {
			continue
		}
		rows = append(rows, ln)
	}
	if len(rows) == 0 {
		return nil, fmt.Errorf("map is empty")
	}
	w := len(rows[0])
	g := &Grid{W: w, H: len(rows), Cost: make([]uint8, w*len(rows))}
	var ns, ng int
	for y, r := range rows {
		if len(r) != w {
			return nil, fmt.Errorf("row %d has length %d, expected %d", y+1, len(r), w)
		}
		for x := 0; x < w; x++ {
			c, ok := costOf(r[x])
			if !ok {
				return nil, fmt.Errorf("row %d col %d: unknown glyph %q", y+1, x+1, r[x])
			}
			g.Cost[y*w+x] = c
			switch r[x] {
			case 'S':
				g.Start = Point{x, y}
				ns++
			case 'G':
				g.Goal = Point{x, y}
				ng++
			}
		}
	}
	if ns != 1 || ng != 1 {
		return nil, fmt.Errorf("map needs exactly one S and one G (found %d S, %d G)", ns, ng)
	}
	return g, nil
}

// LineOfSight reports whether the straight segment between two cell centres
// crosses only open cells, and never passes exactly through a vertex whose two
// side cells are blocked or whose side cells are not both open (so it is
// consistent with the no-corner-cutting step rule). Exact integer arithmetic.
func (g *Grid) LineOfSight(a, b Point) bool {
	if !g.Open(a.X, a.Y) || !g.Open(b.X, b.Y) {
		return false
	}
	dx, dy := b.X-a.X, b.Y-a.Y
	sx, sy := 1, 1
	if dx < 0 {
		dx, sx = -dx, -1
	}
	if dy < 0 {
		dy, sy = -dy, -1
	}
	// Work in (major, minor) offsets with major >= minor >= 0.
	major, minor := dx, dy
	swap := false
	if dy > dx {
		major, minor, swap = dy, dx, true
	}
	open := func(i, j int) bool { // i along major axis, j along minor axis (unsigned offsets)
		if swap {
			return g.Open(a.X+sx*j, a.Y+sy*i)
		}
		return g.Open(a.X+sx*i, a.Y+sy*j)
	}
	if major == 0 {
		return true
	}
	for k := 0; k <= major; k++ {
		// Line's minor coordinate over column k spans (lo,hi)/(2*major).
		lo, hi := (2*k-1)*minor, (2*k+1)*minor
		if k == 0 {
			lo = 0
		}
		if k == major {
			hi = 2 * k * minor // the segment ends at the centre of the last cell
		}
		// rows r with (2r-1)*major < hi && (2r+1)*major > lo
		rmin := floorDiv(lo+major, 2*major)
		rmax := ceilDiv(hi-major, 2*major)
		for r := rmin; r <= rmax; r++ {
			if !open(k, r) {
				return false
			}
		}
		if k < major {
			v := (2*k + 1) * minor // line height at the column boundary
			if minor > 0 && (v-major)%(2*major) == 0 {
				r := (v - major) / (2 * major)
				if !open(k, r+1) || !open(k+1, r) {
					return false
				}
			}
		}
	}
	return true
}

func floorDiv(a, b int) int {
	q := a / b
	if a%b != 0 && (a < 0) != (b < 0) {
		q--
	}
	return q
}

func ceilDiv(a, b int) int { return -floorDiv(-a, b) }
