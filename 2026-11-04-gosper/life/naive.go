package life

// Naive is an independent sparse-set simulator used as the oracle for Hashlife.
// It shares no code with the quadtree engine beyond the Rule type.
type Naive struct {
	Rule  Rule
	Cells map[Point]struct{}
	Gen   uint64
}

func NewNaive(r Rule, pts []Point) *Naive {
	n := &Naive{Rule: r, Cells: make(map[Point]struct{}, len(pts))}
	for _, p := range pts {
		n.Cells[p] = struct{}{}
	}
	return n
}

func (n *Naive) Step() {
	cnt := make(map[Point]int, len(n.Cells)*8)
	for p := range n.Cells {
		for dy := int64(-1); dy <= 1; dy++ {
			for dx := int64(-1); dx <= 1; dx++ {
				if dx != 0 || dy != 0 {
					cnt[Point{p.X + dx, p.Y + dy}]++
				}
			}
		}
	}
	next := make(map[Point]struct{}, len(n.Cells))
	if n.Rule.Survive[0] {
		// live cells with no live neighbours never appear in cnt
		for p := range n.Cells {
			if _, seen := cnt[p]; !seen {
				next[p] = struct{}{}
			}
		}
	}
	for p, c := range cnt {
		if _, alive := n.Cells[p]; alive {
			if n.Rule.Survive[c] {
				next[p] = struct{}{}
			}
		} else if n.Rule.Born[c] {
			next[p] = struct{}{}
		}
	}
	n.Cells = next
	n.Gen++
}

func (n *Naive) StepN(k uint64) {
	for i := uint64(0); i < k; i++ {
		n.Step()
	}
}

// Points returns the live cells.
func (n *Naive) Points() []Point {
	out := make([]Point, 0, len(n.Cells))
	for p := range n.Cells {
		out = append(out, p)
	}
	return out
}

// Equal compares the naive state with a Sim, up to a translation of (dx,dy)
// applied to the naive coordinates.
func (n *Naive) EqualSim(s *Sim, dx, dy int64) bool {
	if uint64(len(n.Cells)) != s.Population() {
		return false
	}
	pts, _ := s.Cells(0)
	for _, p := range pts {
		if _, ok := n.Cells[Point{p.X - dx, p.Y - dy}]; !ok {
			return false
		}
	}
	return true
}
