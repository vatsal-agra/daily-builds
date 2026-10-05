package fp

import (
	"math"
	"math/rand"
	"testing"
)

func TestMaxFilterMatchesBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(1))
	for _, n := range []int{1, 5, 40} {
		for _, r := range []int{0, 1, 3, 9} {
			src := make([]float32, n)
			for i := range src {
				src[i] = rng.Float32()
			}
			dst := make([]float32, n)
			maxFilter1D(src, dst, r)
			for i := range src {
				m := float32(-1)
				for j := i - r; j <= i+r; j++ {
					if j >= 0 && j < n && src[j] > m {
						m = src[j]
					}
				}
				if dst[i] != m {
					t.Fatalf("n=%d r=%d i=%d got %v want %v", n, r, i, dst[i], m)
				}
			}
		}
	}
}

func TestHashPacking(t *testing.T) {
	h := MakeHash(450, 300, 63)
	if h>>15 != 450 || (h>>6)&0x1FF != 300 || h&0x3F != 63 || h >= 1<<24 {
		t.Fatalf("bad packing %x", h)
	}
}

func chirpSignal(rate int, sec float64) []float64 {
	n := int(sec * float64(rate))
	x := make([]float64, n)
	for i := range x {
		t := float64(i) / float64(rate)
		// a few tone bursts at different frequencies
		f := 600 + 900*math.Sin(2*math.Pi*0.7*t) + 200*math.Floor(t*3)
		x[i] = 0.5 * math.Sin(2*math.Pi*f*t)
	}
	return x
}

func TestPeaksLandOnTone(t *testing.T) {
	p := Default()
	n := 3 * p.Rate
	x := make([]float64, n)
	for i := range x {
		x[i] = math.Sin(2 * math.Pi * 1000 * float64(i) / float64(p.Rate))
	}
	peaks, _ := Fingerprint(x, float64(p.Rate), p)
	if len(peaks) == 0 {
		t.Fatal("no peaks")
	}
	want := 1000.0 * float64(p.NFFT) / float64(p.Rate)
	for _, pk := range peaks[:5] {
		if math.Abs(float64(pk.F)-want) > 1.5 {
			t.Fatalf("peak bin %d, want ~%.0f", pk.F, want)
		}
	}
}

func TestShiftInvariance(t *testing.T) {
	// Hashes of a clip cut from the middle must be a subset of the full signal's hashes
	// (modulo the clip edges), with time offset = cut point.
	p := Default()
	x := chirpSignal(p.Rate, 12)
	_, full := Fingerprint(x, float64(p.Rate), p)
	cut := 4 * p.Rate // exactly 4 s -> frame-aligned (8000/256 = 31.25 frames/s; 4s=125 frames)
	_, part := Fingerprint(x[cut:cut+5*p.Rate], float64(p.Rate), p)
	if len(part) == 0 {
		t.Skip("synthetic signal too sparse")
	}
	set := map[Hash]bool{}
	for _, h := range full {
		set[h] = true
	}
	hit := 0
	off := int32(cut / p.Hop)
	for _, h := range part {
		if set[Hash{h.H, h.T + off}] {
			hit++
		}
	}
	if frac := float64(hit) / float64(len(part)); frac < 0.5 {
		t.Fatalf("only %.0f%% of clip hashes found at the expected offset", frac*100)
	}
}

func TestSilenceAndShortInput(t *testing.T) {
	p := Default()
	if pk, h := Fingerprint(make([]float64, 5*p.Rate), float64(p.Rate), p); len(pk) != 0 || len(h) != 0 {
		t.Fatal("inconsistent")
	}
	if pk, h := Fingerprint(make([]float64, 100), float64(p.Rate), p); len(pk) != 0 || len(h) != 0 {
		t.Fatal("short input should yield nothing")
	}
	if pk, _ := Fingerprint(nil, float64(p.Rate), p); len(pk) != 0 {
		t.Fatal("nil input should yield nothing")
	}
}
