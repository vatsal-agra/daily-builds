// Package eval measures identification accuracy under controlled degradations.
package eval

import (
	"fmt"
	"math"
	"math/rand"
	"runtime"
	"sort"
	"strings"
	"sync"

	"landmark/internal/degrade"
	"landmark/internal/engine"
	"landmark/internal/fp"
	"landmark/internal/index"
	"landmark/internal/synth"
)

// Condition is one named degradation applied to a clipped query.
type Condition struct {
	Name  string
	Speed float64 // >0 applies a playback-speed change and enables speed search
	Apply func(x []float64, rate int, rng *rand.Rand) []float64
}

// Conditions is the standard battery.
func Conditions() []Condition {
	id := func(x []float64, _ int, _ *rand.Rand) []float64 { return x }
	return []Condition{
		{"clean", 0, id},
		{"white noise 10 dB SNR", 0, func(x []float64, _ int, r *rand.Rand) []float64 { return degrade.Noise(x, 10, false, r) }},
		{"white noise 0 dB SNR", 0, func(x []float64, _ int, r *rand.Rand) []float64 { return degrade.Noise(x, 0, false, r) }},
		{"pink noise -3 dB SNR", 0, func(x []float64, _ int, r *rand.Rand) []float64 { return degrade.Noise(x, -3, true, r) }},
		{"low-pass 1.5 kHz", 0, func(x []float64, rt int, _ *rand.Rand) []float64 { return degrade.Lowpass(x, rt, 1500) }},
		{"heavy distortion (drive 12)", 0, func(x []float64, _ int, _ *rand.Rand) []float64 { return degrade.Distort(x, 12) }},
		{"reverb (wet 0.8)", 0, func(x []float64, rt int, r *rand.Rand) []float64 { return degrade.Reverb(x, rt, 0.8, r) }},
		{"quiet (-40 dB) + 20 dB SNR noise", 0, func(x []float64, _ int, r *rand.Rand) []float64 {
			return degrade.Gain(degrade.Noise(x, 20, false, r), -40)
		}},
		{"phone: lowpass 3 kHz + noise 5 dB + distortion", 0, func(x []float64, rt int, r *rand.Rand) []float64 {
			return degrade.Noise(degrade.Distort(degrade.Lowpass(x, rt, 3000), 4), 5, true, r)
		}},
		{"speed +3% (speed search on)", 1.03, id},
		{"speed -4% + noise 10 dB (speed search on)", 0.96, func(x []float64, _ int, r *rand.Rand) []float64 { return degrade.Noise(x, 10, false, r) }},
	}
}

// Config drives an evaluation run.
type Config struct {
	Songs, Negatives int
	SongSeconds      float64
	GenRate          int
	ClipLens         []float64
	Trials           int
	Seed             int64
	Policy           index.Policy
	Log              func(string)
}

// Cell is one (condition, clip length) measurement.
type Cell struct {
	Trials, Correct, WrongAccept, Rejected, OffsetOK int
}

// Row groups cells over clip lengths.
type Row struct {
	Cond  string
	Cells []Cell
}

// Report is the full result.
type Report struct {
	Cfg           Config
	Rows          []Row
	NegTrials     int
	NegAccepts    int
	NegScores     []int // top aligned-vote score of every negative query
	PosScores     []int // winning score of every correctly identified positive query
	IndexKeys     int
	IndexPostings int
	Markdown      string
}

// Run builds a corpus, indexes the first Songs, and attacks it.
func Run(cfg Config) (*Report, error) {
	logf := cfg.Log
	if logf == nil {
		logf = func(string) {}
	}
	p := fp.Default()
	ix := index.New(p)
	audio := make([][]float64, cfg.Songs)
	names := make([]string, cfg.Songs)
	var wg sync.WaitGroup
	sem := make(chan struct{}, runtime.NumCPU())
	gen := func(seed int64) (string, []float64) {
		info, x := synth.Generate(seed, cfg.SongSeconds, cfg.GenRate)
		return fmt.Sprintf("%s (#%d)", info.Name, seed), x
	}
	for i := 0; i < cfg.Songs; i++ {
		wg.Add(1)
		sem <- struct{}{}
		go func(i int) {
			defer wg.Done()
			defer func() { <-sem }()
			names[i], audio[i] = gen(int64(i + 1))
		}(i)
	}
	wg.Wait()
	for i := range audio {
		if _, err := engine.Add(ix, names[i], audio[i], cfg.GenRate); err != nil {
			return nil, err
		}
	}
	negs := make([][]float64, cfg.Negatives)
	for i := range negs {
		_, negs[i] = gen(int64(10000 + i))
	}
	post := 0
	for _, s := range ix.Songs {
		post += s.Hashes
	}
	logf(fmt.Sprintf("indexed %d songs: %d keys, %d landmarks", cfg.Songs, ix.NumKeys(), post))

	rep := &Report{Cfg: cfg, IndexKeys: ix.NumKeys(), IndexPostings: post}
	conds := Conditions()
	for ci, c := range conds {
		row := Row{Cond: c.Name, Cells: make([]Cell, len(cfg.ClipLens))}
		for li, L := range cfg.ClipLens {
			cell := &row.Cells[li]
			var mu sync.Mutex
			for tr := 0; tr < cfg.Trials; tr++ {
				wg.Add(1)
				sem <- struct{}{}
				go func(tr int) {
					defer wg.Done()
					defer func() { <-sem }()
					rng := rand.New(rand.NewSource(cfg.Seed + int64(ci)*100003 + int64(li)*1009 + int64(tr)))
					si := rng.Intn(cfg.Songs)
					start := rng.Float64() * (cfg.SongSeconds - L - 0.1)
					clip := degrade.Crop(audio[si], cfg.GenRate, start, L)
					clip = c.Apply(clip, cfg.GenRate, rng)
					sr := engine.SpeedRange{}
					if c.Speed > 0 {
						clip = degrade.Speed(clip, c.Speed)
						sr = engine.SpeedRange{Max: 0.06, Step: 0.005}
					}
					res, err := engine.Identify(ix, clip, cfg.GenRate, cfg.Policy, sr)
					mu.Lock()
					defer mu.Unlock()
					cell.Trials++
					if err != nil || !res.Found {
						cell.Rejected++
						return
					}
					if int(res.Best.Song.ID) != si {
						cell.WrongAccept++
						return
					}
					cell.Correct++
					rep.PosScores = append(rep.PosScores, res.Best.Score)
					if math.Abs(res.Best.OffsetSec-start) < 0.25 {
						cell.OffsetOK++
					}
				}(tr)
			}
			wg.Wait()
		}
		rep.Rows = append(rep.Rows, row)
		logf(fmt.Sprintf("  %-50s %s", c.Name, rowSummary(row)))
	}
	// negatives: songs that were never indexed, under clean and noisy conditions
	var mu sync.Mutex
	for ni, neg := range negs {
		for _, L := range cfg.ClipLens {
			for k := 0; k < cfg.Trials/max(1, cfg.Negatives)+1; k++ {
				wg.Add(1)
				sem <- struct{}{}
				go func(ni, k int, L float64, neg []float64) {
					defer wg.Done()
					defer func() { <-sem }()
					rng := rand.New(rand.NewSource(cfg.Seed + 777 + int64(ni*131+k)))
					clip := degrade.Crop(neg, cfg.GenRate, rng.Float64()*(cfg.SongSeconds-L-0.1), L)
					if k%2 == 1 {
						clip = degrade.Noise(clip, 5, false, rng)
					}
					res, _ := engine.Identify(ix, clip, cfg.GenRate, cfg.Policy, engine.SpeedRange{Max: 0.06, Step: 0.005})
					mu.Lock()
					rep.NegTrials++
					if len(res.Matches) > 0 {
						rep.NegScores = append(rep.NegScores, res.Matches[0].Score)
					}
					if res.Found {
						rep.NegAccepts++
					}
					mu.Unlock()
				}(ni, k, L, neg)
			}
		}
	}
	wg.Wait()
	rep.Markdown = rep.render(ix)
	return rep, nil
}

func pct(a, b int) string {
	if b == 0 {
		return "—"
	}
	return fmt.Sprintf("%.0f%%", 100*float64(a)/float64(b))
}

func rowSummary(r Row) string {
	var parts []string
	for _, c := range r.Cells {
		parts = append(parts, fmt.Sprintf("%s (wrong %d)", pct(c.Correct, c.Trials), c.WrongAccept))
	}
	return strings.Join(parts, "  ")
}

func (r *Report) render(ix *index.Index) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Corpus: %d indexed songs × %.0f s, %d distinct hash keys, %d landmarks (%.1f / s of audio). Trials per cell: %d.\n\n",
		r.Cfg.Songs, r.Cfg.SongSeconds, r.IndexKeys, r.IndexPostings,
		float64(r.IndexPostings)/(float64(r.Cfg.Songs)*r.Cfg.SongSeconds), r.Cfg.Trials)
	b.WriteString("| Condition |")
	for _, L := range r.Cfg.ClipLens {
		fmt.Fprintf(&b, " %.0f s clip |", L)
	}
	b.WriteString("\n|---|")
	for range r.Cfg.ClipLens {
		b.WriteString("---|")
	}
	b.WriteString("\n")
	for _, row := range r.Rows {
		fmt.Fprintf(&b, "| %s |", row.Cond)
		for _, c := range row.Cells {
			fmt.Fprintf(&b, " %s correct · %d wrong · offset ✓ %s |", pct(c.Correct, c.Trials), c.WrongAccept, pct(c.OffsetOK, c.Correct))
		}
		b.WriteString("\n")
	}
	fmt.Fprintf(&b, "\nFalse accepts on never-indexed songs: **%d / %d** queries.\n", r.NegAccepts, r.NegTrials)
	if len(r.PosScores) > 0 && len(r.NegScores) > 0 {
		pos, neg := append([]int(nil), r.PosScores...), append([]int(nil), r.NegScores...)
		sort.Ints(pos)
		sort.Ints(neg)
		fmt.Fprintf(&b, "\nScore margin (aligned votes): correct matches p1=%d median=%d; never-indexed queries median=%d p99=%d max=%d; accept floor=%d.\n",
			pos[len(pos)/100], pos[len(pos)/2], neg[len(neg)/2], neg[len(neg)*99/100], neg[len(neg)-1], r.Cfg.Policy.MinScore)
	}
	return b.String()
}

// Worst returns the lowest accuracy among rows whose name contains substr (for tests).
func (r *Report) Accuracy(cond string, lenIdx int) float64 {
	for _, row := range r.Rows {
		if row.Cond == cond {
			c := row.Cells[lenIdx]
			return float64(c.Correct) / float64(c.Trials)
		}
	}
	return math.NaN()
}

// TotalWrong counts wrong accepts across every cell.
func (r *Report) TotalWrong() int {
	n := 0
	for _, row := range r.Rows {
		for _, c := range row.Cells {
			n += c.WrongAccept
		}
	}
	return n
}
