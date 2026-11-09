package codec

import (
	"encoding/binary"
	"hash/crc32"
	"math"
	"math/rand"
	"strings"
	"testing"
	"time"
)

// Regression tests, one per issue found in the adversarial review (see REVIEW.md).

// R1: non-finite / absurd samples must be rejected, not turned into garbage.
func TestRejectsNonFiniteSamples(t *testing.T) {
	for _, bad := range []float64{math.NaN(), math.Inf(1), math.Inf(-1), 1e12} {
		a := mustGen(t, "mix", 1)
		a.Ch[1][200] = bad
		if _, _, err := Encode(a, Params{Kbps: 64, Transient: true}); err == nil || !strings.Contains(err.Error(), "sample") {
			t.Fatalf("sample %g accepted (err=%v)", bad, err)
		}
	}
	if _, _, err := Encode(&Audio{Rate: 44100, Ch: [][]float64{{1, 2, 3}, {1, 2}}}, DefaultParams()); err == nil {
		t.Fatal("ragged channels accepted")
	}
}

// R2: asking for more bitrate than the signal can use is reported, not silent.
func TestCappedAndOvershootReported(t *testing.T) {
	a := mustGen(t, "mix", 2)
	_, st, _ := Encode(a, Params{Kbps: 5000, Transient: true})
	if !st.Capped || st.Overshoot {
		t.Fatalf("5000 kbps: capped=%v overshoot=%v", st.Capped, st.Overshoot)
	}
	_, st, _ = Encode(a, Params{Kbps: 1, Transient: true})
	if st.Capped {
		t.Fatal("1 kbps wrongly capped")
	}
	if _, _, err := Encode(a, Params{Kbps: -3}); err == nil {
		t.Fatal("negative bitrate accepted")
	}
	if _, _, err := Encode(a, Params{Kbps: 0.5}); err == nil {
		t.Fatal("sub-1-kbps bitrate accepted")
	}
	if _, _, err := Encode(a, Params{Quality: 500}); err == nil {
		t.Fatal("absurd quality accepted")
	}
}

// R4: M/S shares the noise budget between M and S, so dual-mono costs ≈ true mono.
func TestMSNoiseBudget(t *testing.T) {
	a := mustGen(t, "voice", 3) // L == R exactly
	_, ms, _ := Encode(a, Params{Quality: 10, MS: true, Transient: true})
	_, lr, _ := Encode(a, Params{Quality: 10, MS: false, Transient: true})
	mono := &Audio{Rate: a.Rate, Ch: [][]float64{a.Ch[0]}}
	_, mo, _ := Encode(mono, Params{Quality: 10, Transient: true})
	if ms.MSFrames == 0 {
		t.Fatal("M/S never chosen for dual mono")
	}
	if float64(ms.Bytes) > 1.06*float64(mo.Bytes) {
		t.Fatalf("dual-mono via M/S %d bytes vs true mono %d", ms.Bytes, mo.Bytes)
	}
	if float64(ms.Bytes) > 0.6*float64(lr.Bytes) {
		t.Fatalf("M/S %d bytes did not beat L/R %d", ms.Bytes, lr.Bytes)
	}
	// uncorrelated stereo must not be forced into M/S
	n := mustGen(t, "noise", 2)
	_, st, _ := Encode(n, Params{Quality: 10, MS: true, Transient: true})
	if st.MSFrames > st.Frames/4 {
		t.Fatalf("uncorrelated noise used M/S in %d/%d frames", st.MSFrames, st.Frames)
	}
}

// R5: the metric must see pre-echo — block switching has to improve the 256-sample view.
func TestMetricSeesPreEcho(t *testing.T) {
	a := mustGen(t, "castanets", 4)
	on, _ := Run("on", a, Params{Kbps: 64, Transient: true, MS: true})
	off, _ := Run("off", a, Params{Kbps: 64, Transient: false, MS: true})
	if on.Stats.ShortFrames == 0 || off.Stats.ShortFrames != 0 {
		t.Fatal("block-switching flags not as requested")
	}
	if on.M.TempExcess >= off.M.TempExcess*0.7 || on.M.TempP95 >= off.M.TempP95 {
		t.Fatalf("switching on: temporal excess %.2f p95 %.2f; off: %.2f p95 %.2f",
			on.M.TempExcess, on.M.TempP95, off.M.TempExcess, off.M.TempP95)
	}
}

// R6: noise filling fills spectral holes at a bounded bit cost.
func TestNoiseFillingFillsHoles(t *testing.T) {
	a := mustGen(t, "mix", 4)
	off, _ := Run("off", a, Params{Kbps: 24, Transient: true, MS: true})
	on, _ := Run("on", a, Params{Kbps: 24, Transient: true, MS: true, NoiseFill: true})
	if on.M.HoleFrac >= off.M.HoleFrac*0.6 {
		t.Fatalf("holes %.3f → %.3f", off.M.HoleFrac, on.M.HoleFrac)
	}
	if on.Stats.NoiseBits > 0.3*float64(len(on.File)*8) {
		t.Fatalf("noise-fill side info is %.0f%% of the stream", 100*on.Stats.NoiseBits/float64(len(on.File)*8))
	}
	// determinism of the decoder's PRNG
	d1, _ := Decode(on.File)
	d2, _ := Decode(on.File)
	for i := range d1.Ch[0] {
		if d1.Ch[0][i] != d2.Ch[0][i] {
			t.Fatal("decode with noise filling is not deterministic")
		}
	}
}

// R7: a header whose layout fingerprint disagrees must be refused, not mis-decoded.
func TestLayoutFingerprint(t *testing.T) {
	a := mustGen(t, "tones", 1)
	f, _, _ := Encode(a, Params{Kbps: 64, Transient: true})
	bad := append([]byte(nil), f...)
	bad[22] ^= 1
	if _, err := Decode(bad); err == nil || !strings.Contains(err.Error(), "layout") {
		t.Fatalf("fingerprint mismatch not caught: %v", err)
	}
}

func rehash(b []byte) {
	binary.LittleEndian.PutUint32(b[14:], uint32(len(b)-headerSize))
	binary.LittleEndian.PutUint32(b[18:], crc32.ChecksumIEEE(b[headerSize:]))
}

// Hostile input: CRC-valid garbage and bit-flipped streams must never panic or hang.
func TestHostileDecode(t *testing.T) {
	r := rand.New(rand.NewSource(9))
	start := time.Now()
	good, _, _ := Encode(mustGen(t, "mix", 1), Params{Kbps: 64, Transient: true, NoiseFill: true, MS: true})
	for i := 0; i < 300; i++ {
		p := append([]byte(nil), good...)
		for k := 0; k < 1+r.Intn(4); k++ {
			p[headerSize+r.Intn(len(p)-headerSize)] ^= byte(1 << uint(r.Intn(8)))
		}
		if r.Intn(4) == 0 {
			p = p[:headerSize+r.Intn(len(p)-headerSize)]
		}
		rehash(p)
		_, _ = Decode(p) // any error is fine; a panic or hang is not
	}
	for i := 0; i < 300; i++ {
		h := append([]byte(nil), good[:headerSize]...)
		binary.LittleEndian.PutUint32(h[10:], uint32(r.Intn(1<<30)+1))
		h[5] = byte(1 + r.Intn(2))
		pl := make([]byte, r.Intn(300)+1)
		r.Read(pl)
		_, _ = Decode(rehashed(h, pl))
	}
	// huge claimed length with a tiny payload must fail fast
	h := append([]byte(nil), good[:headerSize]...)
	binary.LittleEndian.PutUint32(h[10:], 1<<30)
	h[5] = 2
	if _, err := Decode(rehashed(h, make([]byte, 12))); err == nil {
		t.Fatal("giant header with tiny payload decoded")
	}
	if time.Since(start) > 20*time.Second {
		t.Fatalf("hostile decode took %v", time.Since(start))
	}
}

func rehashed(h, payload []byte) []byte {
	b := append(append([]byte(nil), h...), payload...)
	rehash(b)
	return b
}

// Every supported sample rate round-trips with valid layouts.
func TestSampleRates(t *testing.T) {
	for _, r := range []int{8000, 11025, 22050, 32000, 44100, 48000, 96000, 192000} {
		for _, m := range []int{LongM, ShortM} {
			l := LayoutFor(m, r)
			for i := 1; i < len(l.Edges); i++ {
				if l.Edges[i]-l.Edges[i-1] < 4 {
					t.Fatalf("rate %d M=%d: band %d narrower than 4 bins", r, m, i-1)
				}
			}
			if l.Edges[0] != 0 || l.Edges[len(l.Edges)-1] != m {
				t.Fatalf("rate %d M=%d: edges do not tile the spectrum", r, m)
			}
		}
		a, _ := Generate("mix", 1, r, 1)
		f, _, err := Encode(a, Params{Kbps: 64, Transient: true, MS: true})
		if err != nil {
			t.Fatalf("%d: %v", r, err)
		}
		d, err := Decode(f)
		if err != nil || d.Rate != r || d.Frames() != a.Frames() {
			t.Fatalf("%d: decode err=%v", r, err)
		}
	}
}

// Silence is (nearly) free and decodes to exact zeros.
func TestSilence(t *testing.T) {
	a := mustGen(t, "silence", 2)
	f, _, err := Encode(a, Params{Kbps: 64, MS: true, Transient: true})
	if err != nil {
		t.Fatal(err)
	}
	if len(f) > 120 {
		t.Fatalf("2 s of silence took %d bytes", len(f))
	}
	d, _ := Decode(f)
	for _, v := range d.Ch[0] {
		if v != 0 {
			t.Fatal("silence decoded to non-zero")
		}
	}
}

// Full-scale square waves must survive (huge quantised values, escape codes).
func TestFullScaleSquare(t *testing.T) {
	n := 44100
	a := &Audio{Rate: 44100, Ch: [][]float64{make([]float64, n), make([]float64, n)}}
	for i := 0; i < n; i++ {
		v := 32767.0
		if (i/50)%2 == 0 {
			v = -32768
		}
		a.Ch[0][i], a.Ch[1][i] = v, -v
	}
	f, _, err := Encode(a, Params{Quality: 25, MS: true, Transient: true})
	if err != nil {
		t.Fatal(err)
	}
	d, err := Decode(f)
	if err != nil {
		t.Fatal(err)
	}
	if m, _ := Compare(a, d); m.SNR < 25 {
		t.Fatalf("square SNR %.1f", m.SNR)
	}
}

// Steady signals must not trigger block switching (false positives cost bits).
func TestNoFalseTransients(t *testing.T) {
	for _, sig := range []string{"tones", "noise", "sweep", "voice"} {
		_, st, _ := Encode(mustGen(t, sig, 3), Params{Kbps: 64, Transient: true})
		if st.ShortFrames != 0 {
			t.Fatalf("%s: %d short frames", sig, st.ShortFrames)
		}
	}
}
