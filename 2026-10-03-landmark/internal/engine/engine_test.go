package engine

import (
	"math"
	"math/rand"
	"sync"
	"testing"

	"landmark/internal/degrade"
	"landmark/internal/fp"
	"landmark/internal/index"
	"landmark/internal/synth"
)

const genRate = 11025

var (
	once  sync.Once
	ix    *index.Index
	audio [][]float64
)

// fixture builds a 10-song, 40 s library once for the whole package.
func fixture(t *testing.T) (*index.Index, [][]float64) {
	once.Do(func() {
		ix = index.New(fp.Default())
		audio = make([][]float64, 10)
		var wg sync.WaitGroup
		for i := range audio {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				_, audio[i] = synth.Generate(int64(i+1), 40, genRate)
			}(i)
		}
		wg.Wait()
		for i, x := range audio {
			if _, err := Add(ix, string(rune('A'+i)), x, genRate); err != nil {
				panic(err)
			}
		}
	})
	return ix, audio
}

func TestIdentifiesCleanClipWithOffset(t *testing.T) {
	ix, au := fixture(t)
	for si := 0; si < 10; si += 3 {
		clip := degrade.Crop(au[si], genRate, 13.37, 6)
		r, err := Identify(ix, clip, genRate, index.DefaultPolicy(), SpeedRange{})
		if err != nil {
			t.Fatal(err)
		}
		if !r.Found || int(r.Best.Song.ID) != si {
			t.Fatalf("song %d not identified: %+v", si, r.Verdict)
		}
		if math.Abs(r.Best.OffsetSec-13.37) > 0.1 {
			t.Fatalf("offset %.2f, want 13.37", r.Best.OffsetSec)
		}
		if r.Speed != 1 {
			t.Fatalf("speed %v", r.Speed)
		}
	}
}

func TestSurvivesNoiseFilterReverb(t *testing.T) {
	ix, au := fixture(t)
	rng := rand.New(rand.NewSource(9))
	clip := degrade.Crop(au[4], genRate, 20, 10)
	clip = degrade.Reverb(degrade.Lowpass(clip, genRate, 2500), genRate, 0.6, rng)
	clip = degrade.Noise(clip, 3, true, rng)
	r, _ := Identify(ix, clip, genRate, index.DefaultPolicy(), SpeedRange{})
	if !r.Found || r.Best.Song.ID != 4 {
		t.Fatalf("not identified under combined damage: %+v", r.Verdict)
	}
}

func TestSpeedSearchRecoversFactor(t *testing.T) {
	ix, au := fixture(t)
	clip := degrade.Speed(degrade.Crop(au[7], genRate, 10, 10), 1.04)
	// without the search the clip is (correctly) not trusted…
	if r, _ := Identify(ix, clip, genRate, index.DefaultPolicy(), SpeedRange{}); r.Found && r.Best.Song.ID != 7 {
		t.Fatalf("wrong accept without speed search: %+v", r.Verdict)
	}
	r, _ := Identify(ix, clip, genRate, index.DefaultPolicy(), SpeedRange{Max: 0.06, Step: 0.005})
	if !r.Found || r.Best.Song.ID != 7 {
		t.Fatalf("speed-shifted clip not identified: %+v", r.Verdict)
	}
	if math.Abs(r.Speed-1.04) > 0.006 {
		t.Fatalf("estimated speed %.3f, want ~1.04", r.Speed)
	}
	// the offset is reported in *original* song time
	if math.Abs(r.Best.OffsetSec-10) > 0.3 {
		t.Fatalf("offset %.2f, want ~10", r.Best.OffsetSec)
	}
}

func TestRejectsUnknownMusicAndNonMusic(t *testing.T) {
	ix, _ := fixture(t)
	for seed := int64(500); seed < 506; seed++ {
		_, x := synth.Generate(seed, 30, genRate)
		clip := degrade.Crop(x, genRate, 5, 8)
		r, _ := Identify(ix, clip, genRate, index.DefaultPolicy(), SpeedRange{Max: 0.06, Step: 0.005})
		if r.Found {
			t.Fatalf("never-indexed seed %d accepted as %s: %+v", seed, r.Best.Song.Name, r.Verdict)
		}
	}
	rng := rand.New(rand.NewSource(1))
	noise := make([]float64, 8*genRate)
	for i := range noise {
		noise[i] = rng.NormFloat64() * 0.2
	}
	if r, _ := Identify(ix, noise, genRate, index.DefaultPolicy(), SpeedRange{}); r.Found {
		t.Fatalf("white noise accepted: %+v", r.Verdict)
	}
	if r, err := Identify(ix, make([]float64, 5*genRate), genRate, index.DefaultPolicy(), SpeedRange{}); err != nil || r.Found || r.Hashes != 0 {
		t.Fatalf("silence: err=%v %+v", err, r.Verdict)
	}
	if _, err := Identify(ix, nil, genRate, index.DefaultPolicy(), SpeedRange{}); err == nil {
		t.Fatal("empty input must error")
	}
}

func TestCandidatesList(t *testing.T) {
	c := SpeedRange{Max: 0.02, Step: 0.01}.Candidates()
	want := []float64{1, 1.01, 0.99, 1.02, 0.98}
	if len(c) != len(want) {
		t.Fatalf("%v", c)
	}
	for i := range c {
		if math.Abs(c[i]-want[i]) > 1e-9 {
			t.Fatalf("%v", c)
		}
	}
	if len((SpeedRange{}).Candidates()) != 1 {
		t.Fatal("zero range must be exact-only")
	}
}

func TestSharpenRejectsPlateau(t *testing.T) {
	mk := func(speed float64, score int) Result {
		m := index.Match{Song: index.Song{ID: 1}, Score: score}
		return Result{Verdict: index.Verdict{Found: true, Best: m}, Speed: speed, Matches: []index.Match{m}}
	}
	plateau := []Result{mk(1, 5), mk(1.02, 20), mk(1.03, 18), mk(1.05, 17)}
	sharpen(plateau, 0.01, index.DefaultPolicy())
	if plateau[1].Found {
		t.Fatal("a plateau of similar scores at every speed must be rejected")
	}
	spike := []Result{mk(1, 5), mk(1.02, 120), mk(1.03, 18), mk(1.05, 9)}
	sharpen(spike, 0.01, index.DefaultPolicy())
	if !spike[1].Found {
		t.Fatal("a sharp spike must survive")
	}
}
