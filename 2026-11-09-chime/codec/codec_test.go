package codec

import (
	"math"
	"testing"
)

func mustGen(t *testing.T, name string, sec float64) *Audio {
	t.Helper()
	a, err := Generate(name, sec, 44100, 1)
	if err != nil {
		t.Fatal(err)
	}
	return a
}

// Feature 1+3: end-to-end — high quality gives high SNR, deterministic output.
func TestEndToEndHighQuality(t *testing.T) {
	a := mustGen(t, "mix", 3)
	f1, _, err := Encode(a, Params{Quality: 45, MS: true, Transient: true})
	if err != nil {
		t.Fatal(err)
	}
	f2, _, _ := Encode(a, Params{Quality: 45, MS: true, Transient: true})
	if string(f1) != string(f2) {
		t.Fatal("encoder is not deterministic")
	}
	d, err := Decode(f1)
	if err != nil {
		t.Fatal(err)
	}
	m, _ := Compare(a, d)
	if m.SNR < 45 {
		t.Fatalf("SNR %.1f dB at q=45, want ≥ 45", m.SNR)
	}
	if d.Frames() != a.Frames() || d.Rate != a.Rate || len(d.Ch) != 2 {
		t.Fatal("shape changed")
	}
}

// Feature 3: rate control lands on target.
func TestRateControl(t *testing.T) {
	a := mustGen(t, "mix", 4)
	for _, kb := range []float64{32, 64, 128} {
		file, st, err := Encode(a, Params{Kbps: kb, MS: true, Transient: true})
		if err != nil {
			t.Fatal(err)
		}
		if st.Kbps > kb*1.001 || st.Kbps < kb*0.94 {
			t.Fatalf("target %g kbps → got %.2f (%d bytes)", kb, st.Kbps, len(file))
		}
	}
}

// Feature 1: transients trigger short blocks, steady tones do not.
func TestBlockSwitchingChosen(t *testing.T) {
	_, st, _ := Encode(mustGen(t, "castanets", 3), Params{Kbps: 96, Transient: true})
	if st.ShortFrames < 5 {
		t.Fatalf("castanets used only %d short frames", st.ShortFrames)
	}
	_, st, _ = Encode(mustGen(t, "tones", 3), Params{Kbps: 96, Transient: true})
	if st.ShortFrames != 0 {
		t.Fatalf("steady tones used %d short frames", st.ShortFrames)
	}
}

// Feature 2/4: perceptual allocation beats the flat baseline on audible noise at equal rate.
func TestPerceptualBeatsFlat(t *testing.T) {
	for _, sig := range []string{"mix", "bells", "castanets"} {
		a := mustGen(t, sig, 4)
		per, flat, err := Shootout(a, Params{Kbps: 48, MS: true, Transient: true})
		if err != nil {
			t.Fatal(err)
		}
		if per.M.MeanExcess >= flat.M.MeanExcess || per.M.P95NMR >= flat.M.P95NMR {
			t.Fatalf("%s: chime excess %.2f p95 %.2f vs flat excess %.2f p95 %.2f", sig,
				per.M.MeanExcess, per.M.P95NMR, flat.M.MeanExcess, flat.M.P95NMR)
		}
		if per.M.SNR >= flat.M.SNR {
			t.Fatalf("%s: expected perceptual coder to trade SNR for masking (%.1f vs %.1f)", sig, per.M.SNR, flat.M.SNR)
		}
	}
}

func TestMonoAndTinyInputs(t *testing.T) {
	for _, n := range []int{1, 5, 1023, 1024, 1025, 5000} {
		a := &Audio{Rate: 22050, Ch: [][]float64{make([]float64, n)}}
		for i := range a.Ch[0] {
			a.Ch[0][i] = 8000 * math.Sin(float64(i)*0.1)
		}
		file, _, err := Encode(a, Params{Quality: 30, Transient: true})
		if err != nil {
			t.Fatalf("n=%d: %v", n, err)
		}
		d, err := Decode(file)
		if err != nil {
			t.Fatalf("n=%d: %v", n, err)
		}
		if d.Frames() != n || len(d.Ch) != 1 {
			t.Fatalf("n=%d: got %d frames", n, d.Frames())
		}
	}
}

func TestCorruptionDetected(t *testing.T) {
	a := mustGen(t, "voice", 1)
	file, _, _ := Encode(a, Params{Kbps: 64, Transient: true})
	bad := append([]byte(nil), file...)
	bad[len(bad)/2] ^= 0x10
	if _, err := Decode(bad); err == nil {
		t.Fatal("flipped payload bit not detected")
	}
	if _, err := Decode(file[:len(file)-7]); err == nil {
		t.Fatal("truncation not detected")
	}
	if _, err := Decode(file[:10]); err == nil {
		t.Fatal("short header accepted")
	}
}
