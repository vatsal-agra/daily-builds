package scan

import (
	"math"
	"sort"
)

// Finder is a detected finder-pattern candidate.
type Finder struct {
	C      Pt      // centre in pixels
	Module float64 // estimated module size in pixels
	Hits   int     // number of independent scan-line confirmations
}

// FindFinders locates finder-pattern candidates by 1:1:3:1:1 run-length
// analysis along rows, cross-checked vertically and horizontally, then merged.
func FindFinders(b *Bin) []Finder {
	var cands []Finder
	runs := make([]int, 0, 64)
	for y := 0; y < b.H; y++ {
		runs = runs[:0]
		starts := []int{}
		cur, start := b.Pix[y*b.W], 0
		for x := 1; x <= b.W; x++ {
			if x == b.W || b.Pix[y*b.W+x] != cur {
				runs = append(runs, x-start)
				starts = append(starts, start)
				if x < b.W {
					cur = b.Pix[y*b.W+x]
				}
				start = x
			}
		}
		first := b.Pix[y*b.W]
		for i := 0; i+4 < len(runs); i++ {
			// runs[i] must be dark: even index if the row starts dark, else odd.
			if (i%2 == 0) != first {
				continue
			}
			if !ratioOK(runs[i : i+5]) {
				continue
			}
			total := runs[i] + runs[i+1] + runs[i+2] + runs[i+3] + runs[i+4]
			cx := float64(starts[i]) + float64(total)/2
			if f, ok := crossCheck(b, cx, float64(y), float64(total)); ok {
				cands = append(cands, f)
			}
		}
	}
	return mergeFinders(cands)
}

// ratioOK checks dark:light:dark:light:dark ~ 1:1:3:1:1 with blur-tolerant slack.
func ratioOK(r []int) bool {
	total := 0
	for _, v := range r {
		if v == 0 {
			return false
		}
		total += v
	}
	if total < 7 {
		return false
	}
	ms := float64(total) / 7
	tol := ms * 0.65
	return math.Abs(float64(r[0])-ms) < tol && math.Abs(float64(r[1])-ms) < tol &&
		math.Abs(float64(r[2])-3*ms) < 3*tol && math.Abs(float64(r[3])-ms) < tol &&
		math.Abs(float64(r[4])-ms) < tol
}

// lineRuns samples the image along the ray from (x,y) in direction (dx,dy)
// (unit vector, sampled at integer arc lengths t = 1,2,...) and returns the
// lengths of consecutive runs: first the dark run containing the start, then
// light, then dark.
func lineRuns(b *Bin, x, y, dx, dy float64, limit int) (r [3]int) {
	want := true
	k := 0
	for t := 1; t <= limit && k < 3; t++ {
		xi, yi := int(math.Round(x+dx*float64(t))), int(math.Round(y+dy*float64(t)))
		if b.At(xi, yi) == want {
			r[k]++
			continue
		}
		if k < 2 {
			want = !want
			k++
			// the pixel that ended the run starts the next one
			r[k]++
			continue
		}
		break
	}
	return
}

// crossLine reads the five runs centred on (cx,cy) along direction (dx,dy) and
// returns them, plus the offset of the true centre along the line, if the
// centre pixel is dark and the runs are 1:1:3:1:1.
func crossLine(b *Bin, cx, cy, dx, dy, approx float64) ([5]int, float64, bool) {
	var r [5]int
	if !b.At(int(math.Round(cx)), int(math.Round(cy))) {
		return r, 0, false
	}
	limit := int(approx * 2)
	f := lineRuns(b, cx, cy, dx, dy, limit)
	k := lineRuns(b, cx, cy, -dx, -dy, limit)
	r = [5]int{k[2], k[1], f[0] + k[0] + 1, f[1], f[2]}
	if !ratioOK(r[:]) {
		return r, 0, false
	}
	return r, float64(f[0]-k[0]) / 2, true
}

func crossCheck(b *Bin, cx, cy, approx float64) (Finder, bool) {
	// vertical through the row hit
	rv, offV, ok := crossLine(b, cx, cy, 0, 1, approx)
	if !ok {
		return Finder{}, false
	}
	cy += offV
	// horizontal again at the refined row
	rh, offH, ok := crossLine(b, cx, cy, 1, 0, approx)
	if !ok {
		return Finder{}, false
	}
	cx += offH
	tv, th := sum5(rv), sum5(rh)
	if math.Abs(float64(tv-th)) > 0.6*float64(max(tv, th)) {
		return Finder{}, false
	}
	// diagonal checks make the test rotation-robust against text/clutter
	for _, d := range [][2]float64{{0.7071, 0.7071}, {0.7071, -0.7071}} {
		if _, _, ok := crossLine(b, cx, cy, d[0], d[1], approx*1.5); !ok {
			return Finder{}, false
		}
	}
	return Finder{C: Pt{cx + 0.5, cy + 0.5}, Module: float64(tv+th) / 14, Hits: 1}, true
}

func sum5(r [5]int) int { return r[0] + r[1] + r[2] + r[3] + r[4] }

func mergeFinders(c []Finder) []Finder {
	var out []Finder
	for _, f := range c {
		merged := false
		for i := range out {
			o := &out[i]
			if o.C.Sub(f.C).Len() < math.Max(o.Module, f.Module)*2.5 {
				n := float64(o.Hits)
				o.C = o.C.Mul(n / (n + 1)).Add(f.C.Mul(1 / (n + 1)))
				o.Module = (o.Module*n + f.Module) / (n + 1)
				o.Hits++
				merged = true
				break
			}
		}
		if !merged {
			out = append(out, f)
		}
	}
	var keep []Finder
	for _, f := range out {
		if f.Hits >= 2 {
			keep = append(keep, f)
		}
	}
	sort.Slice(keep, func(i, j int) bool { return keep[i].Hits > keep[j].Hits })
	return keep
}

// CoreModule refines the module size using the rotation-invariant area of the
// 3x3 dark core: flood-fill from the centre; area = 9*module^2.
func CoreModule(b *Bin, c Pt, guess float64) float64 {
	sx, sy := int(c.X), int(c.Y)
	if !b.At(sx, sy) {
		return guess
	}
	limit := int(math.Pow(guess*4, 2))
	seen := map[int]bool{sy*b.W + sx: true}
	stack := [][2]int{{sx, sy}}
	area := 0
	for len(stack) > 0 {
		p := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		area++
		if area > limit {
			return guess
		}
		for _, d := range [][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}} {
			x, y := p[0]+d[0], p[1]+d[1]
			k := y*b.W + x
			if x < 0 || y < 0 || x >= b.W || y >= b.H || seen[k] || !b.Pix[k] {
				continue
			}
			seen[k] = true
			stack = append(stack, [2]int{x, y})
		}
	}
	ms := math.Sqrt(float64(area)) / 3
	if ms < guess*0.5 || ms > guess*1.6 {
		return guess
	}
	return ms
}
