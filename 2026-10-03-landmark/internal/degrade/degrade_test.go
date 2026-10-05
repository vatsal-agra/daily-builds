package degrade

import (
	"math"
	"math/rand"
	"testing"

	"landmark/internal/dsp"
)

func tone(n int, f, fs float64) []float64 {
	x := make([]float64, n)
	for i := range x {
		x[i] = 0.5 * math.Sin(2*math.Pi*f*float64(i)/fs)
	}
	return x
}

func TestNoiseHitsTargetSNR(t *testing.T) {
	x := tone(40000, 440, 8000)
	for _, snr := range []float64{20, 5, -3} {
		for _, pink := range []bool{false, true} {
			y := Noise(x, snr, pink, rand.New(rand.NewSource(1)))
			n := make([]float64, len(x))
			for i := range n {
				n[i] = y[i] - x[i]
			}
			got := 20 * math.Log10(dsp.RMS(x)/dsp.RMS(n))
			if math.Abs(got-snr) > 0.1 {
				t.Fatalf("snr %.1f pink=%v: measured %.2f", snr, pink, got)
			}
		}
	}
}

func TestCropClamps(t *testing.T) {
	x := make([]float64, 8000)
	if got := len(Crop(x, 8000, 0.5, 0.25)); got != 2000 {
		t.Fatalf("len %d", got)
	}
	if got := len(Crop(x, 8000, 0.5, 99)); got != 4000 {
		t.Fatalf("overrun len %d", got)
	}
	if Crop(x, 8000, 5, 1) != nil {
		t.Fatal("start beyond end must be nil")
	}
	if got := len(Crop(x, 8000, -0.5, 1)); got != 4000 {
		t.Fatalf("window straddling the start should keep the in-range half, got %d", got)
	}
	if Crop(x, 8000, -2, 1) != nil {
		t.Fatal("window entirely before the file must be nil")
	}
}

func TestGainAndDistortKeepLevel(t *testing.T) {
	x := tone(8000, 300, 8000)
	if r := dsp.RMS(Gain(x, -20)) / dsp.RMS(x); math.Abs(r-0.1) > 1e-6 {
		t.Fatalf("gain ratio %v", r)
	}
	d := Distort(x, 10)
	if math.Abs(dsp.RMS(d)-dsp.RMS(x)) > 1e-6 {
		t.Fatal("distortion should renormalise to input RMS")
	}
	// hard drive squares the wave: peak/rms drops
	if pk := peak(d); pk/dsp.RMS(d) > 1.2 {
		t.Fatalf("not clipped: crest %.2f", pk/dsp.RMS(d))
	}
}

func peak(x []float64) float64 {
	m := 0.0
	for _, v := range x {
		m = math.Max(m, math.Abs(v))
	}
	return m
}

func TestSpeedChangesLengthAndPitch(t *testing.T) {
	x := tone(16000, 500, 8000)
	y := Speed(x, 1.25)
	if math.Abs(float64(len(y))-12800) > 2 {
		t.Fatalf("len %d", len(y))
	}
	spec := dsp.STFT(y, 1024, 512)
	row := spec[4]
	best := 0
	for k := range row {
		if row[k] > row[best] {
			best = k
		}
	}
	if f := float64(best) * 8000 / 1024; math.Abs(f-625) > 8 {
		t.Fatalf("pitch %.1f Hz, want 625", f)
	}
}

func TestReverbAddsTailAndLowpassRemovesHighs(t *testing.T) {
	imp := make([]float64, 8000)
	imp[100] = 1
	r := Reverb(imp, 8000, 0.8, rand.New(rand.NewSource(2)))
	tail := 0.0
	for _, v := range r[400:] {
		tail += v * v
	}
	if tail == 0 || r[100] != 1 {
		t.Fatal("reverb should keep the dry impulse and add a tail")
	}
	hi := Lowpass(tone(8000, 3500, 8000), 8000, 800)
	if dsp.RMS(hi[2000:]) > 0.01 {
		t.Fatal("lowpass left too much 3.5 kHz energy")
	}
}
