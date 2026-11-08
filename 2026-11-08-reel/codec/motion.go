package codec

import "math/bits"

// Search algorithms.
const (
	SearchFull    = 0
	SearchDiamond = 1
)

// mvdBits approximates the cost in bits of coding a vector difference.
func mvdBits(dx, dy int) float64 {
	c := func(v int) float64 {
		if v == 0 {
			return 1
		}
		a := iabs(v)
		return float64(2*bits.Len(uint(a)) + 1)
	}
	return c(dx) + c(dy)
}

// sad of a w*h block of src at (sx,sy) against ref at integer (rx,ry); stops
// early once the running sum exceeds limit.
func sad(src *Plane, sx, sy int, ref *Plane, rx, ry, w, h, limit int) int {
	s := 0
	for j := 0; j < h; j++ {
		a := src.Pix[src.idx(sx, sy+j) : src.idx(sx, sy+j)+w]
		b := ref.Pix[ref.idx(rx, ry+j) : ref.idx(rx, ry+j)+w]
		for i := 0; i < w; i++ {
			d := int(a[i]) - int(b[i])
			if d < 0 {
				d = -d
			}
			s += d
		}
		if s >= limit {
			return s
		}
	}
	return s
}

// sadPred is the SAD of src against an explicit prediction buffer (stride w).
func sadPred(src *Plane, sx, sy int, pred []uint8, w, h int) int {
	s := 0
	for j := 0; j < h; j++ {
		a := src.Pix[src.idx(sx, sy+j) : src.idx(sx, sy+j)+w]
		for i := 0; i < w; i++ {
			s += iabs(int(a[i]) - int(pred[j*w+i]))
		}
	}
	return s
}

// searcher performs motion estimation for one block against one reference.
type searcher struct {
	src      *Plane
	ref      *Plane
	px, py   int // block position (pixels)
	w, h     int
	pred     MV
	lam      float64 // SAD-domain lambda
	algo     int
	subpel   int
	rng      int
	evals    *int
	bestCost float64
	best     MV
	scratch  [256]uint8
}

func (s *searcher) bitsCost(mv MV) float64 {
	return s.lam * mvdBits(int(mv.X)-int(s.pred.X), int(mv.Y)-int(s.pred.Y))
}

// tryInt evaluates an integer-pel displacement; reports whether it improved.
func (s *searcher) tryInt(dx, dy int) bool {
	if iabs(dx) > s.rng || iabs(dy) > s.rng || iabs(dx*4) > maxMV || iabs(dy*4) > maxMV {
		return false
	}
	mv := MV{int16(dx * 4), int16(dy * 4)}
	extra := s.bitsCost(mv)
	if extra >= s.bestCost {
		return false
	}
	*s.evals++
	limit := int(s.bestCost - extra + 1)
	c := sad(s.src, s.px, s.py, s.ref, s.px+dx, s.py+dy, s.w, s.h, limit)
	cost := float64(c) + extra
	if cost < s.bestCost {
		s.bestCost, s.best = cost, mv
		return true
	}
	return false
}

func (s *searcher) trySub(mv MV) bool {
	if !mvOK(mv) {
		return false
	}
	extra := s.bitsCost(mv)
	if extra >= s.bestCost {
		return false
	}
	*s.evals++
	predLuma(s.ref, s.px*4+int(mv.X), s.py*4+int(mv.Y), s.w, s.h, s.scratch[:])
	c := float64(sadPred(s.src, s.px, s.py, s.scratch[:s.w*s.h], s.w, s.h)) + extra
	if c < s.bestCost {
		s.bestCost, s.best = c, mv
		return true
	}
	return false
}

var ldsp = [][2]int{{0, -2}, {0, 2}, {-2, 0}, {2, 0}, {-1, -1}, {1, -1}, {-1, 1}, {1, 1}}
var sdsp = [][2]int{{0, -1}, {0, 1}, {-1, 0}, {1, 0}}

// run searches from the candidate set and returns the best vector and its cost
// (SAD + lambda*mv bits).
func (s *searcher) run(cands []MV) (MV, float64) {
	s.bestCost = 1e18
	s.best = MV{}
	// integer candidates
	tried := map[[2]int]bool{}
	try := func(dx, dy int) {
		k := [2]int{dx, dy}
		if tried[k] {
			return
		}
		tried[k] = true
		s.tryInt(dx, dy)
	}
	// forced zero candidate so bestCost is always finite
	s.bestCost = 1e18
	s.tryInt(0, 0)
	if s.bestCost >= 1e18 { // zero rejected by range (rng==0): fall back
		s.best = MV{}
		s.bestCost = float64(sad(s.src, s.px, s.py, s.ref, s.px, s.py, s.w, s.h, 1<<30)) + s.bitsCost(MV{})
	}
	tried[[2]int{0, 0}] = true
	for _, c := range cands {
		try((int(c.X)+2)>>2, (int(c.Y)+2)>>2)
	}
	switch s.algo {
	case SearchFull:
		for dy := -s.rng; dy <= s.rng; dy++ {
			for dx := -s.rng; dx <= s.rng; dx++ {
				try(dx, dy)
			}
		}
	default:
		for iter := 0; iter < 64; iter++ {
			cx, cy := int(s.best.X)>>2, int(s.best.Y)>>2
			moved := false
			for _, d := range ldsp {
				k := [2]int{cx + d[0], cy + d[1]}
				if tried[k] {
					continue
				}
				tried[k] = true
				if s.tryInt(k[0], k[1]) {
					moved = true
				}
			}
			if !moved {
				break
			}
		}
		cx, cy := int(s.best.X)>>2, int(s.best.Y)>>2
		for _, d := range sdsp {
			try(cx+d[0], cy+d[1])
		}
	}
	// sub-pel refinement
	if s.subpel >= 1 {
		c := s.best
		for _, d := range [][2]int{{-2, -2}, {0, -2}, {2, -2}, {-2, 0}, {2, 0}, {-2, 2}, {0, 2}, {2, 2}} {
			s.trySub(MV{c.X + int16(d[0]), c.Y + int16(d[1])})
		}
		// the integer best was scored with integer SAD, which equals the
		// sub-pel scorer at fx=fy=0, so costs are comparable.
	}
	if s.subpel >= 2 {
		c := s.best
		for _, d := range [][2]int{{-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}} {
			s.trySub(MV{c.X + int16(d[0]), c.Y + int16(d[1])})
		}
	}
	return s.best, s.bestCost
}
