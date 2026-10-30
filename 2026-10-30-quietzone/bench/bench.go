// Package bench measures scanner accuracy against ground truth: it encodes
// random payloads, degrades the images with the camera simulator and counts
// how often the scanner returns exactly the original text.
package bench

import (
	"fmt"
	"image"
	"image/png"
	"math/rand"
	"os"
	"time"

	"quietzone/qr"
	"quietzone/scan"
	"quietzone/sim"
)

// Scenario is one degradation recipe.
type Scenario struct {
	Name  string
	Scale int // pixels per module of the clean render
	// Degrade receives the clean render and the symbol rectangle within it.
	Degrade func(g *image.Gray, sym image.Rectangle, rng *rand.Rand) *image.Gray
	MinVer  int
	MaxVer  int
	// Floor is the minimum acceptable success rate (0..1) asserted by tests.
	Floor float64
}

func pose(p sim.Pose, bg uint8) func(*image.Gray, image.Rectangle, *rand.Rand) *image.Gray {
	return func(g *image.Gray, _ image.Rectangle, _ *rand.Rand) *image.Gray { return sim.Warp(g, p, bg) }
}

// Scenarios returns the standard benchmark suite.
func Scenarios() []Scenario {
	randRoll := func(rng *rand.Rand) float64 { return rng.Float64()*360 - 180 }
	return []Scenario{
		{"clean", 6, func(g *image.Gray, _ image.Rectangle, _ *rand.Rand) *image.Gray { return g }, 1, 40, 1},
		{"rotation any angle", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(g, sim.Pose{Roll: randRoll(r)}, 255)
		}, 1, 20, 1},
		{"tilt up to 35°", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(g, sim.Pose{Roll: randRoll(r), TiltX: r.Float64()*70 - 35, TiltY: r.Float64()*70 - 35, Margin: 0.1}, 240)
		}, 1, 15, 0.95},
		{"strong tilt 50°", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(g, sim.Pose{Roll: randRoll(r), TiltX: r.Float64()*30 + 35, TiltY: r.Float64()*20 - 10, Margin: 0.1}, 240)
		}, 1, 10, 0.85},
		{"mirrored", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(g, sim.Pose{Roll: randRoll(r), Mirror: true}, 255)
		}, 1, 15, 1},
		{"blur σ=1.5px (module 8px)", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Blur(sim.Warp(g, sim.Pose{Roll: randRoll(r)}, 255), 1.5)
		}, 1, 15, 0.95},
		{"noise σ=25 + salt&pepper", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Noise(sim.Warp(g, sim.Pose{Roll: randRoll(r)}, 255), 25, 0.01, r)
		}, 1, 15, 0.95},
		{"uneven light + low contrast", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			w := sim.Warp(g, sim.Pose{Roll: randRoll(r), TiltX: 10}, 255)
			return sim.Lighting(sim.Contrast(w, 60, 200), 0.55, 0.3, r.Float64()*360)
		}, 1, 15, 0.9},
		{"JPEG quality 20", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			out, err := sim.JPEG(sim.Warp(g, sim.Pose{Roll: randRoll(r), TiltX: 12}, 255), 20)
			if err != nil {
				return g
			}
			return out
		}, 1, 15, 0.95},
		{"logo covers 14% of width", 8, func(g *image.Gray, sym image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(sim.Logo(g, sym, 0.14, uint8(r.Intn(2)*255)), sim.Pose{Roll: randRoll(r)}, 255)
		}, 5, 25, 0.95},
		{"tiny modules (3px)", 3, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(g, sim.Pose{Roll: randRoll(r), TiltX: 10}, 255)
		}, 1, 10, 0.9},
		{"background clutter", 8, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			w, box := sim.WarpQuad(g, sim.Pose{Roll: randRoll(r), Scale: 1, Margin: 0.6}, 255)
			return sim.Clutter(w, box, r, 60)
		}, 1, 15, 0.9},
		{"high versions (v25-40) rotated", 5, func(g *image.Gray, _ image.Rectangle, r *rand.Rand) *image.Gray {
			return sim.Warp(g, sim.Pose{Roll: randRoll(r), TiltX: r.Float64()*20 - 10}, 255)
		}, 25, 40, 0.9},
	}
}

// Row is one scenario's outcome.
type Row struct {
	Name     string
	Trials   int
	Pass     int
	MeanTime time.Duration
	Failures []string // descriptions of the first few failing trials
	Floor    float64
}

// Rate is Pass/Trials.
func (r Row) Rate() float64 { return float64(r.Pass) / float64(r.Trials) }

var payloads = []func(r *rand.Rand, n int) string{
	func(r *rand.Rand, n int) string { return rnd(r, "0123456789", n) },
	func(r *rand.Rand, n int) string { return rnd(r, "ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789$%*+-./:", n) },
	func(r *rand.Rand, n int) string {
		return rnd(r, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:/?=&_-", n)
	},
}

func rnd(r *rand.Rand, set string, n int) string {
	b := make([]byte, n)
	for i := range b {
		b[i] = set[r.Intn(len(set))]
	}
	return string(b)
}

// Run executes every scenario `trials` times with deterministic seeds.
func Run(trials int, seed int64, only string) []Row {
	var rows []Row
	for si, sc := range Scenarios() {
		if only != "" && sc.Name != only {
			continue
		}
		row := Row{Name: sc.Name, Trials: trials, Floor: sc.Floor}
		var total time.Duration
		for t := 0; t < trials; t++ {
			rng := rand.New(rand.NewSource(seed + int64(si)*100003 + int64(t)))
			ver := sc.MinVer + rng.Intn(sc.MaxVer-sc.MinVer+1)
			e := []qr.ECC{M, Q, H}[rng.Intn(3)]
			// fill the chosen version to ~60-95%
			capBytes := qr.DataCodewords(ver, e)
			n := max(1, capBytes*(60+rng.Intn(35))/100-4)
			text := payloads[rng.Intn(3)](rng, n)
			code, err := qr.EncodeText(text, qr.Options{ECC: e, MinVersion: ver, MaxVersion: ver})
			if err != nil {
				text = text[:max(1, len(text)/2)]
				code, err = qr.EncodeText(text, qr.Options{ECC: e, MinVersion: ver, MaxVersion: ver})
				if err != nil {
					continue
				}
			}
			img := code.Matrix.Image(sc.Scale, 4)
			sym := image.Rect(4*sc.Scale, 4*sc.Scale, (4+code.Matrix.N)*sc.Scale, (4+code.Matrix.N)*sc.Scale)
			deg := sc.Degrade(img, sym, rng)
			start := time.Now()
			ds, err := scan.Scan(deg, scan.Options{MaxCodes: 1})
			total += time.Since(start)
			if err == nil && len(ds) > 0 && ds[0].Result.Text == text {
				row.Pass++
			} else if len(row.Failures) < 5 {
				if dir := os.Getenv("QZ_DUMP"); dir != "" {
					if f, e := os.Create(fmt.Sprintf("%s/fail-%d-%d.png", dir, si, t)); e == nil {
						_ = png.Encode(f, deg)
						f.Close()
					}
				}
				row.Failures = append(row.Failures, fmt.Sprintf("trial %d: v%d-%v %d chars (seed %d)", t, code.Version, code.ECC, len(text), seed+int64(si)*100003+int64(t)))
			}
		}
		row.MeanTime = total / time.Duration(trials)
		rows = append(rows, row)
	}
	return rows
}

// local aliases keep the scenario table compact
const (
	M = qr.M
	Q = qr.Q
	H = qr.H
)
