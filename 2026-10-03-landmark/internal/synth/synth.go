// Package synth composes and renders procedural multi-instrument songs from a seed.
package synth

import (
	"fmt"
	"math"
	"math/rand"
)

var (
	adjectives = []string{"Amber", "Velvet", "Neon", "Hollow", "Paper", "Glass", "Static", "Copper", "Lunar", "Silent", "Electric", "Faded", "Crimson", "Tidal", "Frozen", "Golden"}
	nouns      = []string{"Harbor", "Engine", "Garden", "Signal", "Orbit", "Lantern", "Circuit", "Meadow", "Skyline", "Echo", "Compass", "Ember", "Canyon", "Mirage", "Voyage", "Cascade"}
)

type scale struct {
	name  string
	steps []int
}

var scales = []scale{
	{"Major", []int{0, 2, 4, 5, 7, 9, 11}},
	{"Minor", []int{0, 2, 3, 5, 7, 8, 10}},
	{"Dorian", []int{0, 2, 3, 5, 7, 9, 10}},
	{"Mixolydian", []int{0, 2, 4, 5, 7, 9, 10}},
	{"Pentatonic", []int{0, 2, 4, 7, 9}},
}

// chord progressions as scale-degree roots (0-based, over a 7-note or 5-note scale)
var progressions = [][]int{{0, 3, 4, 0}, {0, 5, 3, 4}, {0, 4, 5, 3}, {5, 3, 0, 4}, {0, 2, 3, 4}, {0, 3, 0, 4}}

// Info describes a generated song.
type Info struct {
	Seed     int64
	Name     string
	BPM      float64
	Key      string
	Duration float64
}

type voice struct {
	harm    []float64 // harmonic amplitudes for the lead
	attack  float64
	release float64
	vibHz   float64
	vibDep  float64
}

func (s scale) note(root, degree int) int {
	n := len(s.steps)
	oct := degree / n
	d := degree % n
	if d < 0 {
		d += n
		oct--
	}
	return root + s.steps[d] + 12*oct
}

type renderer struct {
	buf  []float64
	rate float64
}

func (r *renderer) tone(start, dur, freq, gain float64, v voice) {
	s0 := int(start * r.rate)
	n := int((dur + v.release) * r.rate)
	phase := 0.0
	for i := 0; i < n; i++ {
		idx := s0 + i
		if idx < 0 || idx >= len(r.buf) {
			if idx >= len(r.buf) {
				return
			}
			continue
		}
		t := float64(i) / r.rate
		env := 1.0
		if t < v.attack {
			env = t / v.attack
		}
		if t > dur {
			env *= math.Max(0, 1-(t-dur)/v.release)
		}
		env *= 0.55 + 0.45*math.Exp(-3*t/math.Max(dur, 0.05)) // gentle decay
		f := freq * (1 + v.vibDep*math.Sin(2*math.Pi*v.vibHz*t))
		phase += 2 * math.Pi * f / r.rate
		var y float64
		for h, a := range v.harm {
			if f*float64(h+1) < r.rate/2.2 {
				y += a * math.Sin(phase*float64(h+1))
			}
		}
		r.buf[idx] += gain * env * y
	}
}

func (r *renderer) kick(start, gain, base float64) {
	s0 := int(start * r.rate)
	n := int(0.28 * r.rate)
	phase := 0.0
	for i := 0; i < n && s0+i < len(r.buf); i++ {
		t := float64(i) / r.rate
		f := base + 110*math.Exp(-t*28)
		phase += 2 * math.Pi * f / r.rate
		r.buf[s0+i] += gain * math.Sin(phase) * math.Exp(-t*9)
	}
}

func (r *renderer) noise(rng *rand.Rand, start, dur, gain, tone float64) {
	// tone in (0,1): higher = brighter (differentiated noise mix)
	s0 := int(start * r.rate)
	n := int(dur * r.rate)
	prev := 0.0
	for i := 0; i < n && s0+i < len(r.buf); i++ {
		t := float64(i) / r.rate
		w := rng.Float64()*2 - 1
		y := tone*(w-prev) + (1-tone)*w*0.3
		prev = w
		r.buf[s0+i] += gain * y * math.Exp(-t*(5/dur))
	}
}

// Generate renders a song of `dur` seconds at sample rate `rate`. The result depends only on seed.
func Generate(seed int64, dur float64, rate int) (Info, []float64) {
	rng := rand.New(rand.NewSource(seed*7919 + 17))
	sc := scales[rng.Intn(len(scales))]
	root := 45 + rng.Intn(12)
	bpm := math.Round((78+70*rng.Float64())*10) / 10
	detune := (rng.Float64() - 0.5) * 0.8 // ±40 cents of per-song tuning drift
	kickHz := 40 + 20*rng.Float64()
	prog := progressions[rng.Intn(len(progressions))]
	beat := 60 / bpm
	bar := 4 * beat

	// per-song timbre
	nh := 3 + rng.Intn(5)
	lead := voice{attack: 0.01 + 0.03*rng.Float64(), release: 0.08 + 0.15*rng.Float64(),
		vibHz: 4 + 3*rng.Float64(), vibDep: 0.002 + 0.004*rng.Float64()}
	for h := 0; h < nh; h++ {
		lead.harm = append(lead.harm, math.Pow(0.3+0.5*rng.Float64(), float64(h)))
	}
	pad := voice{harm: []float64{1, 0.3, 0.12}, attack: 0.08, release: 0.3}
	bass := voice{harm: []float64{1, 0.35}, attack: 0.01, release: 0.08}

	name := fmt.Sprintf("%s %s", adjectives[rng.Intn(len(adjectives))], nouns[rng.Intn(len(nouns))])
	keyNames := []string{"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"}
	info := Info{Seed: seed, Name: name, BPM: bpm, Key: keyNames[root%12] + " " + sc.name, Duration: dur}

	midiHz := func(m float64) float64 { return 440 * math.Pow(2, (m+detune-69)/12) }
	r := &renderer{buf: make([]float64, int(dur*float64(rate))), rate: float64(rate)}
	nb := int(dur/bar) + 1
	nsc := len(sc.steps)

	// melody phrases: A, A', B, A  (each 4 bars of 8 eighth-note slots per bar)
	mkPhrase := func() [][]int { // per bar, per slot: degree or -99 for rest
		ph := make([][]int, 4)
		deg := nsc + rng.Intn(nsc)
		for b := range ph {
			ph[b] = make([]int, 8)
			for s := range ph[b] {
				if rng.Float64() < 0.28 {
					ph[b][s] = -99
					continue
				}
				deg += rng.Intn(5) - 2
				if deg < nsc-2 {
					deg = nsc - 2
				}
				if deg > 2*nsc+3 {
					deg = 2*nsc + 3
				}
				ph[b][s] = deg
			}
		}
		return ph
	}
	// A pool of phrases; every 4-bar section picks one at random and mutates a few notes, so the
	// song has recurring motifs (like real music) but never repeats itself exactly.
	pool := [][][]int{mkPhrase(), mkPhrase(), mkPhrase(), mkPhrase()}
	mutate := func(src [][]int) [][]int {
		out := make([][]int, len(src))
		for b := range src {
			out[b] = append([]int(nil), src[b]...)
		}
		for k := 0; k < 4; k++ {
			b, sl := rng.Intn(4), rng.Intn(8)
			switch rng.Intn(3) {
			case 0:
				out[b][sl] = -99
			default:
				out[b][sl] = nsc + rng.Intn(nsc+3)
			}
		}
		return out
	}
	var phrases [][][]int
	var progs [][]int // progression used in each 4-bar section
	cur := prog
	for sec := 0; sec <= nb/4; sec++ {
		phrases = append(phrases, mutate(pool[rng.Intn(len(pool))]))
		if sec%2 == 0 && sec > 0 {
			cur = progressions[rng.Intn(len(progressions))]
		}
		progs = append(progs, cur)
	}
	hat := rng.Float64() < 0.8
	drums := rng.Float64() < 0.85

	for b := 0; b < nb; b++ {
		t0 := float64(b) * bar
		chordRoot := progs[b/4][b%4]
		rootMidi := sc.note(root, chordRoot)
		// pad triad
		for _, off := range []int{0, 2, 4} {
			m := sc.note(root, chordRoot+off) + 12
			r.tone(t0, bar*0.98, midiHz(float64(m)), 0.07, pad)
		}
		// bass: root on beats 1 and 3, fifth on the and of 3
		r.tone(t0, beat*1.5, midiHz(float64(rootMidi-12)), 0.22, bass)
		r.tone(t0+2*beat, beat*0.9, midiHz(float64(rootMidi-12)), 0.2, bass)
		r.tone(t0+3*beat, beat*0.9, midiHz(float64(sc.note(root, chordRoot+4)-12)), 0.17, bass)
		// melody
		phrase := phrases[b/4]
		for s := 0; s < 8; s++ {
			d := phrase[b%4][s]
			if d == -99 {
				continue
			}
			r.tone(t0+float64(s)*beat/2, beat/2*0.92, midiHz(float64(sc.note(root+12, d))), 0.16, lead)
		}
		if drums {
			for q := 0; q < 4; q++ {
				if q%2 == 0 || (b%4 == 3 && q == 3) {
					r.kick(t0+float64(q)*beat, 0.45, kickHz)
				}
				if q%2 == 1 {
					r.noise(rng, t0+float64(q)*beat, 0.16, 0.22, 0.5)
				}
			}
		}
		if hat {
			for s := 0; s < 8; s++ {
				r.noise(rng, t0+float64(s)*beat/2, 0.05, 0.07, 0.95)
			}
		}
	}
	peak := 0.0
	for _, v := range r.buf {
		peak = math.Max(peak, math.Abs(v))
	}
	if peak > 0 {
		for i := range r.buf {
			r.buf[i] *= 0.9 / peak
		}
	}
	return info, r.buf
}
