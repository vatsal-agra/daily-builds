package dsp

import (
	"math"
	"math/cmplx"
	"testing"
)

func TestFFTMatchesNaiveDFT(t *testing.T) {
	n := 64
	x := make([]complex128, n)
	for i := range x {
		x[i] = complex(math.Sin(float64(i)*0.7)+0.3*float64(i%5), math.Cos(float64(i)*1.3))
	}
	want := make([]complex128, n)
	for k := 0; k < n; k++ {
		for j := 0; j < n; j++ {
			want[k] += x[j] * cmplx.Exp(complex(0, -2*math.Pi*float64(k*j)/float64(n)))
		}
	}
	NewFFT(n).Transform(x)
	for k := range x {
		if cmplx.Abs(x[k]-want[k]) > 1e-9 {
			t.Fatalf("bin %d: got %v want %v", k, x[k], want[k])
		}
	}
}

func TestSTFTFindsTone(t *testing.T) {
	fs, f0 := 8000.0, 1000.0
	x := make([]float64, 8000)
	for i := range x {
		x[i] = math.Sin(2 * math.Pi * f0 * float64(i) / fs)
	}
	spec := STFT(x, 1024, 256)
	row := spec[5]
	best := 0
	for k := range row {
		if row[k] > row[best] {
			best = k
		}
	}
	if got := float64(best) * fs / 1024; math.Abs(got-f0) > 8 {
		t.Fatalf("peak at %.1f Hz, want %.1f", got, f0)
	}
}

func TestResampleKeepsToneFrequency(t *testing.T) {
	x := make([]float64, 22050)
	for i := range x {
		x[i] = math.Sin(2 * math.Pi * 440 * float64(i) / 22050)
	}
	y := Resample(x, 22050, 8000)
	if math.Abs(float64(len(y))-8000) > 2 {
		t.Fatalf("len %d", len(y))
	}
	spec := STFT(y, 1024, 512)
	row := spec[3]
	best := 0
	for k := range row {
		if row[k] > row[best] {
			best = k
		}
	}
	if got := float64(best) * 8000 / 1024; math.Abs(got-440) > 8 {
		t.Fatalf("440 Hz tone landed at %.1f", got)
	}
}

func TestResampleRemovesAliasing(t *testing.T) {
	// 6 kHz tone at fs=22050 is above the 4 kHz Nyquist of 8 kHz: must be strongly attenuated.
	x := make([]float64, 22050)
	for i := range x {
		x[i] = math.Sin(2 * math.Pi * 6000 * float64(i) / 22050)
	}
	y := Resample(x, 22050, 8000)
	if r := RMS(y[100 : len(y)-100]); r > 0.02 {
		t.Fatalf("aliased energy too high: rms %.4f", r)
	}
}

func TestLowpassAttenuates(t *testing.T) {
	fs := 8000.0
	lp := LowpassBiquad(500, fs, 0.707)
	mk := func(f float64) []float64 {
		x := make([]float64, 8000)
		for i := range x {
			x[i] = math.Sin(2 * math.Pi * f * float64(i) / fs)
		}
		return lp.Apply(x)[2000:]
	}
	if lo, hi := RMS(mk(100)), RMS(mk(3000)); hi > lo*0.05 {
		t.Fatalf("lowpass weak: pass %.3f stop %.3f", lo, hi)
	}
}
