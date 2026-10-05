// Package timeline segments a long recording (a DJ mix, a radio hour) into the indexed songs it contains.
package timeline

import (
	"fmt"
	"math"

	"landmark/internal/engine"
	"landmark/internal/index"
)

// Config sets the sliding window.
type Config struct {
	Window float64 // seconds analysed per step
	Step   float64 // seconds between windows
	Policy index.Policy
	Speed  engine.SpeedRange
	// DriftTol is how far (seconds) song-time − mix-time may wander inside one segment.
	DriftTol float64
}

// Default is a good window for pop-length material.
func Default() Config {
	return Config{Window: 8, Step: 2, Policy: index.DefaultPolicy(), DriftTol: 1.5}
}

// Window is the verdict for one analysis window.
type Window struct {
	Start float64
	Found bool
	Song  index.Song
	Delta float64 // song time − mix time (seconds): where the song "began" relative to the mix
	Score int
}

// Segment is a run of windows agreeing on one song and a constant offset.
type Segment struct {
	Start, End float64 // seconds in the mix
	Known      bool
	Song       index.Song
	SongStart  float64 // song time corresponding to Start
	Windows    int
	BestScore  int
}

// Analyse runs the sliding-window identification.
func Analyse(ix *index.Index, x []float64, rate int, cfg Config) ([]Window, error) {
	if cfg.Window < 3 || cfg.Step <= 0 || cfg.Step > cfg.Window {
		return nil, fmt.Errorf("need window >= 3 s and 0 < step <= window")
	}
	n := float64(len(x)) / float64(rate)
	if n < cfg.Window {
		return nil, fmt.Errorf("recording (%.1fs) is shorter than the analysis window (%.1fs)", n, cfg.Window)
	}
	var ws []Window
	for t := 0.0; t+cfg.Window <= n+1e-9; t += cfg.Step {
		a := int(t * float64(rate))
		b := a + int(cfg.Window*float64(rate))
		res, err := engine.Identify(ix, x[a:b], rate, cfg.Policy, cfg.Speed)
		if err != nil {
			return nil, err
		}
		w := Window{Start: t}
		if res.Found {
			w.Found, w.Song, w.Score = true, res.Best.Song, res.Best.Score
			w.Delta = res.Best.OffsetSec - t
		}
		ws = append(ws, w)
	}
	return ws, nil
}

func same(a, b Window, tol float64) bool {
	if a.Found != b.Found {
		return false
	}
	return !a.Found || (a.Song.ID == b.Song.ID && math.Abs(a.Delta-b.Delta) <= tol)
}

// Segments smooths single-window glitches and merges runs of agreeing windows. Each window "owns" the
// time around its centre, so boundaries land mid-way between the windows that disagree.
func Segments(ws []Window, total float64, cfg Config) []Segment {
	if len(ws) == 0 {
		return nil
	}
	w := append([]Window(nil), ws...)
	// bridge a single odd window sandwiched between two agreeing neighbours
	for i := 1; i+1 < len(w); i++ {
		if same(w[i-1], w[i+1], cfg.DriftTol) && !same(w[i-1], w[i], cfg.DriftTol) {
			w[i] = w[i-1]
		}
	}
	var segs []Segment
	for i := 0; i < len(w); {
		j := i
		best := w[i].Score
		for j+1 < len(w) && same(w[i], w[j+1], cfg.DriftTol) {
			j++
			if w[j].Score > best {
				best = w[j].Score
			}
		}
		start := w[i].Start + cfg.Window/2 - cfg.Step/2
		end := w[j].Start + cfg.Window/2 + cfg.Step/2
		if i == 0 {
			start = 0
		}
		if j == len(w)-1 {
			end = total
		}
		sg := Segment{Start: start, End: end, Known: w[i].Found, Song: w[i].Song, Windows: j - i + 1, BestScore: best}
		if sg.Known {
			sg.SongStart = start + w[i].Delta
		}
		segs = append(segs, sg)
		i = j + 1
	}
	return absorbTransitions(segs, cfg.Window)
}

// Run is Analyse followed by Segments.
func Run(ix *index.Index, x []float64, rate int, cfg Config) ([]Segment, error) {
	ws, err := Analyse(ix, x, rate, cfg)
	if err != nil {
		return nil, err
	}
	return Segments(ws, float64(len(x))/float64(rate), cfg), nil
}

// absorbTransitions removes short "unidentified" gaps that sit between two identified segments: windows
// straddling a crossfade contain two songs and match neither cleanly. The boundary is placed mid-gap.
func absorbTransitions(segs []Segment, maxGap float64) []Segment {
	var out []Segment
	for i := 0; i < len(segs); i++ {
		g := segs[i]
		if !g.Known && i > 0 && i+1 < len(segs) && segs[i-1].Known && segs[i+1].Known && g.End-g.Start <= maxGap {
			mid := (g.Start + g.End) / 2
			out[len(out)-1].End = mid
			next := segs[i+1]
			next.SongStart -= next.Start - mid
			next.Start = mid
			segs[i+1] = next
			continue
		}
		out = append(out, g)
	}
	return out
}
