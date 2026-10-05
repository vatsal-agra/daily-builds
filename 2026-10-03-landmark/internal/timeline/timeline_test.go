package timeline

import (
	"math"
	"math/rand"
	"sync"
	"testing"

	"landmark/internal/degrade"
	"landmark/internal/engine"
	"landmark/internal/fp"
	"landmark/internal/index"
	"landmark/internal/synth"
)

const rate = 11025

func crossfade(a, b []float64, n int) []float64 {
	out := append([]float64(nil), a...)
	for i := 0; i < n; i++ {
		t := float64(i) / float64(n)
		k := len(a) - n + i
		out[k] = a[k]*math.Cos(t*math.Pi/2) + b[i]*math.Sin(t*math.Pi/2)
	}
	return append(out, b[n:]...)
}

func TestRecoversTrackListOfNoisyMix(t *testing.T) {
	ix := index.New(fp.Default())
	au := make([][]float64, 5)
	var wg sync.WaitGroup
	for i := range au {
		wg.Add(1)
		go func(i int) { defer wg.Done(); _, au[i] = synth.Generate(int64(i+1), 40, rate) }(i)
	}
	wg.Wait()
	for i, x := range au {
		if _, err := engine.Add(ix, string(rune('A'+i)), x, rate); err != nil {
			t.Fatal(err)
		}
	}
	// B[5..25] -> D[10..32] -> A[0..20] ; true joins at mix 18.5 and 38.5 (1.5 s fades)
	b := degrade.Crop(au[1], rate, 5, 20)
	d := degrade.Crop(au[3], rate, 10, 22)
	a := degrade.Crop(au[0], rate, 0, 20)
	fade := rate * 3 / 2
	mix := crossfade(crossfade(b, d, fade), a, fade)
	mix = degrade.Noise(mix, 12, false, rand.New(rand.NewSource(1)))

	segs, err := Run(ix, mix, rate, Default())
	if err != nil {
		t.Fatal(err)
	}
	if len(segs) != 3 {
		t.Fatalf("want 3 segments, got %d: %+v", len(segs), segs)
	}
	names := []string{"B", "D", "A"}
	// track D starts at mix 18.5, A starts at 18.5 + 22 - 1.5 = 39.0; the join lies mid-fade
	joins := []float64{18.5 + 0.75, 39.0 + 0.75}
	for i, s := range segs {
		if !s.Known || s.Song.Name != names[i] {
			t.Fatalf("segment %d = %+v, want %s", i, s, names[i])
		}
	}
	for i, j := range joins {
		if math.Abs(segs[i].End-j) > 2.5 || math.Abs(segs[i+1].Start-j) > 2.5 {
			t.Fatalf("boundary %d at %.1f/%.1f, want ≈%.1f", i, segs[i].End, segs[i+1].Start, j)
		}
	}
	// where in D the segment begins: song position = 10 + (segStart − 18.5)
	if got, want := segs[1].SongStart, 10+(segs[1].Start-18.5); math.Abs(got-want) > 0.5 {
		t.Fatalf("D song position %.1f, want %.1f", got, want)
	}
}

func TestConfigValidation(t *testing.T) {
	ix := index.New(fp.Default())
	x := make([]float64, 20*rate)
	for _, c := range []Config{{Window: 1, Step: 1}, {Window: 8, Step: 0}, {Window: 8, Step: 9}} {
		if _, err := Analyse(ix, x, rate, c); err == nil {
			t.Errorf("config %+v accepted", c)
		}
	}
	if _, err := Analyse(ix, x[:3*rate], rate, Default()); err == nil {
		t.Error("recording shorter than the window accepted")
	}
}

func TestSegmentSmoothingAndGaps(t *testing.T) {
	cfg := Default()
	song := func(id uint32) index.Song { return index.Song{ID: id, Name: string(rune('A' + id))} }
	f := func(start float64, id uint32, delta float64) Window {
		return Window{Start: start, Found: true, Song: song(id), Delta: delta, Score: 50}
	}
	miss := func(start float64) Window { return Window{Start: start} }
	// one dropped window inside a run is bridged
	segs := Segments([]Window{f(0, 0, 5), f(2, 0, 5), miss(4), f(6, 0, 5), f(8, 0, 5)}, 16, cfg)
	if len(segs) != 1 || segs[0].Windows != 5 {
		t.Fatalf("glitch not bridged: %+v", segs)
	}
	// the same song at a different delta is a different segment (song restarted / seeked)
	segs = Segments([]Window{f(0, 0, 5), f(2, 0, 5), f(4, 0, 30), f(6, 0, 30)}, 14, cfg)
	if len(segs) != 2 {
		t.Fatalf("seek not split: %+v", segs)
	}
	// a long unidentified stretch stays unidentified
	segs = Segments([]Window{f(0, 0, 5), f(2, 0, 5), miss(4), miss(6), miss(8), miss(10), miss(12), miss(14), f(16, 1, 0), f(18, 1, 0)}, 26, cfg)
	if len(segs) != 3 || segs[1].Known {
		t.Fatalf("expected known/unknown/known, got %+v", segs)
	}
}
