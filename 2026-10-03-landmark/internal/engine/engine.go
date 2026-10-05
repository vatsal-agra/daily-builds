// Package engine glues fingerprinting and the index into "identify this audio" operations.
package engine

import (
	"fmt"
	"math"
	"sync"

	"landmark/internal/fp"
	"landmark/internal/index"
)

// Result is an identification outcome.
type Result struct {
	index.Verdict
	Speed     float64 // estimated playback-speed factor of the query vs. the original (1 = unchanged)
	Hashes    int     // landmarks extracted from the query
	Peaks     int
	Matches   []index.Match
	ClipFrame int // number of frames in the query
}

// SpeedRange configures the speed-tolerant search; nil/zero means exact-speed only.
type SpeedRange struct {
	Max  float64 // e.g. 0.06 searches 0.94 … 1.06
	Step float64 // e.g. 0.005
}

// Candidates lists the speed factors to try (always includes 1.0, tried first).
func (s SpeedRange) Candidates() []float64 {
	out := []float64{1}
	if s.Max <= 0 || s.Step <= 0 {
		return out
	}
	n := int(math.Round(s.Max / s.Step))
	for i := 1; i <= n; i++ {
		d := float64(i) * s.Step
		out = append(out, 1+d, 1-d)
	}
	return out
}

// Add fingerprints audio and stores it in ix.
func Add(ix *index.Index, name string, x []float64, rate int) (index.Song, error) {
	spec := fp.Spectrogram(x, float64(rate), ix.Params)
	peaks := fp.FindPeaks(spec, ix.Params)
	pairs := fp.Pairs(peaks, ix.Params)
	hs := make([]fp.Hash, len(pairs))
	for i, p := range pairs {
		hs[i] = p.Hash
	}
	id, err := ix.Add(name, hs, len(spec))
	if err != nil {
		return index.Song{}, err
	}
	return ix.Songs[id], nil
}

// Identify fingerprints a query and returns the best verdict under policy pol. With a speed range,
// the query is re-interpreted at each candidate speed factor (in parallel) and the strongest wins.
func Identify(ix *index.Index, x []float64, rate int, pol index.Policy, sr SpeedRange) (Result, error) {
	if len(x) == 0 {
		return Result{}, fmt.Errorf("empty audio")
	}
	cands := sr.Candidates()
	results := make([]Result, len(cands))
	var wg sync.WaitGroup
	sem := make(chan struct{}, 8)
	for i, c := range cands {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int, c float64) {
			defer wg.Done()
			defer func() { <-sem }()
			// Content sped up by c has every frequency multiplied by c; declaring the sample rate to be
			// rate/c makes the resampler map it back to the original pitch and tempo.
			spec := fp.Spectrogram(x, float64(rate)/c, ix.Params)
			peaks := fp.FindPeaks(spec, ix.Params)
			pairs := fp.PairsFan(peaks, ix.Params, ix.Params.QueryFan)
			hs := make([]fp.Hash, len(pairs))
			for k, p := range pairs {
				hs[k] = p.Hash
			}
			ms := ix.Query(hs)
			cp := pol
			if c != 1 {
				cp.MinScore += pol.SpeedPenalty // searching many speeds gives noise more chances to align
			}
			results[i] = Result{Verdict: cp.Decide(ms), Speed: c, Hashes: len(hs), Peaks: len(peaks), Matches: ms, ClipFrame: len(spec)}
		}(i, c)
	}
	wg.Wait()
	sharpen(results, sr.Step, pol)
	best := 0
	for i := range results {
		a, b := results[i], results[best]
		if (a.Found && !b.Found) || (a.Found == b.Found && a.Best.Score > b.Best.Score) {
			best = i
		}
	}
	return results[best], nil
}

// sharpen rejects speed-corrected matches that are not sharply tuned. A genuinely time-scaled clip lights up
// one speed factor and falls off quickly on either side; a coincidental match (a related song whose rhythm
// and scale overlap) scores about the same at every speed. Requiring the winner to beat the same song's
// score at all speeds ≥2 steps away guards against that.
func sharpen(rs []Result, step float64, pol index.Policy) {
	if step <= 0 {
		return
	}
	for i := range rs {
		r := &rs[i]
		if !r.Found || r.Speed == 1 {
			continue
		}
		other := 0
		for j := range rs {
			if math.Abs(rs[j].Speed-r.Speed) < 1.99*step {
				continue
			}
			for _, m := range rs[j].Matches {
				if m.Song.ID == r.Best.Song.ID {
					if m.Score > other {
						other = m.Score
					}
					break
				}
			}
		}
		if float64(r.Best.Score) < pol.Sharpness*float64(other) {
			r.Found = false
			r.Reason = fmt.Sprintf("speed ×%.3f is not sharply better than other speeds (%d vs %d votes) — coincidental similarity", r.Speed, r.Best.Score, other)
		}
	}
}
