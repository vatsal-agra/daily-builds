package codec

import (
	"math"
	"math/rand"
	"testing"
)

func roundTrip(x []float64, short []bool) []float64 {
	out := make([]float64, len(x))
	for f := 0; f < len(short); f++ {
		SynthesizeFrame(AnalyzeFrame(x, f, short), f, short, out)
	}
	return out
}

func TestTDACPerfectReconstruction(t *testing.T) {
	r := rand.New(rand.NewSource(3))
	n := 20*FrameN + 357
	x := make([]float64, n)
	for i := range x {
		x[i] = r.NormFloat64() * 1000
	}
	nf := NumFrames(n)
	patterns := map[string]func(f int) bool{
		"all long":  func(f int) bool { return false },
		"all short": func(f int) bool { return true },
		"alternate": func(f int) bool { return f%2 == 1 },
		"isolated":  func(f int) bool { return f == 5 || f == 6 || f == 11 },
		"random":    func(f int) bool { return r.Intn(3) == 0 },
		"edges":     func(f int) bool { return f == 0 || f == nf-1 },
	}
	for name, p := range patterns {
		short := make([]bool, nf)
		for f := range short {
			short[f] = p(f)
		}
		y := roundTrip(x, short)
		var worst float64
		for i := range x {
			worst = math.Max(worst, math.Abs(x[i]-y[i]))
		}
		if worst > 1e-8 {
			t.Fatalf("%s: max reconstruction error %g", name, worst)
		}
	}
}

func TestMDCTEnergyCompaction(t *testing.T) {
	n := 4 * FrameN
	x := make([]float64, n)
	for i := range x {
		x[i] = 10000 * math.Sin(2*math.Pi*1000*float64(i)/44100)
	}
	short := make([]bool, NumFrames(n))
	c := AnalyzeFrame(x, 2, short)[0]
	var tot, peak float64
	for k, v := range c {
		tot += v * v
		if k > 20 && k < 30 { // 1 kHz ≈ bin 46? check the real peak below
		}
	}
	pk := 0
	for k, v := range c {
		if v*v > c[pk]*c[pk] {
			pk = k
		}
	}
	for k := pk - 3; k <= pk+3; k++ {
		peak += c[k] * c[k]
	}
	if peak/tot < 0.99 {
		t.Fatalf("tone not compacted: %.4f in ±3 bins around %d", peak/tot, pk)
	}
	if want := 1000 / (44100.0 / 2 / 1024); math.Abs(float64(pk)-want) > 1.5 {
		t.Fatalf("peak bin %d, want ≈ %.1f", pk, want)
	}
}

func TestTransientDetector(t *testing.T) {
	n := 30 * FrameN
	x := make([]float64, n)
	r := rand.New(rand.NewSource(4))
	for i := range x {
		x[i] = 200 * math.Sin(float64(i)*0.05)
	}
	at := 15*FrameN + 300
	for i := at; i < at+600; i++ {
		x[i] += r.NormFloat64() * 12000 * math.Exp(-float64(i-at)/150)
	}
	short := DetectTransients([][]float64{x})
	var any bool
	for f, s := range short {
		if s {
			any = true
			if f < 15 || f > 17 {
				t.Fatalf("spurious short frame %d", f)
			}
		}
	}
	if !any {
		t.Fatal("attack missed")
	}
	steady := DetectTransients([][]float64{x[:10*FrameN]})
	for f, s := range steady {
		if s {
			t.Fatalf("steady tone flagged at frame %d", f)
		}
	}
}
