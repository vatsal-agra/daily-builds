package viz

import (
	"encoding/json"
	"strings"
	"testing"

	"landmark/internal/degrade"
	"landmark/internal/engine"
	"landmark/internal/fp"
	"landmark/internal/index"
	"landmark/internal/synth"
)

const rate = 11025

func setup(t *testing.T) (*index.Index, []float64) {
	t.Helper()
	ix := index.New(fp.Default())
	var first []float64
	for s := int64(1); s <= 3; s++ {
		_, x := synth.Generate(s, 25, rate)
		if s == 2 {
			first = x
		}
		if _, err := engine.Add(ix, "Song <"+string(rune('A'+s))+">", x, rate); err != nil {
			t.Fatal(err)
		}
	}
	return ix, first
}

func payloadOf(t *testing.T, page string) payload {
	t.Helper()
	i := strings.Index(page, "const D=")
	j := strings.Index(page[i:], ";\nconst $=")
	if i < 0 || j < 0 {
		t.Fatal("data block not found")
	}
	var p payload
	if err := json.Unmarshal([]byte(page[i+len("const D="):i+j]), &p); err != nil {
		t.Fatalf("embedded JSON invalid: %v", err)
	}
	return p
}

func TestReportForMatch(t *testing.T) {
	ix, x := setup(t)
	clip := degrade.Crop(x, rate, 6, 8)
	res, _ := engine.Identify(ix, clip, rate, index.DefaultPolicy(), engine.SpeedRange{})
	page, err := Render(ix, clip, rate, res, "evil</title><script>alert(1)</script>.wav")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(page, "__DATA__") || strings.Contains(page, "__TITLE__") {
		t.Fatal("template placeholder left in output")
	}
	if strings.Contains(page, "<script>alert(1)") {
		t.Fatal("title is not escaped")
	}
	p := payloadOf(t, page)
	if !p.Found || p.Song != "Song <C>" || p.NMatched == 0 || p.NMatched > p.NHashes {
		t.Fatalf("payload: found=%v song=%q matched=%d/%d", p.Found, p.Song, p.NMatched, p.NHashes)
	}
	if p.OffsetSec < 5.8 || p.OffsetSec > 6.2 {
		t.Fatalf("offset %.2f", p.OffsetSec)
	}
	if len(p.Hist) == 0 || len(p.Peaks) != p.NPeaks || len(p.Pairs) != p.NHashes {
		t.Fatal("inconsistent payload arrays")
	}
	// the histogram's tallest bar sits at the winning offset
	top := p.Hist[0]
	for _, h := range p.Hist {
		if h[1] > top[1] {
			top = h
		}
	}
	if d := top[0] - p.BestDelta; d < -1 || d > 1 {
		t.Fatalf("histogram peak %d vs best delta %d", top[0], p.BestDelta)
	}
}

func TestReportForNoMatchHasNoNulls(t *testing.T) {
	ix, _ := setup(t)
	clip := make([]float64, 4*rate)
	res, _ := engine.Identify(ix, clip, rate, index.DefaultPolicy(), engine.SpeedRange{})
	page, err := Render(ix, clip, rate, res, "silence.wav")
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{`"Peaks":null`, `"Pairs":null`, `"Hist":null`, `"Scores":null`} {
		if strings.Contains(page, f) {
			t.Fatalf("JSON contains %s — the page script would crash", f)
		}
	}
	if payloadOf(t, page).Found {
		t.Fatal("silence reported as found")
	}
	if _, err := Render(ix, []float64{0.1, 0.2}, rate, engine.Result{Speed: 1}, "tiny"); err == nil {
		t.Fatal("too-short clip should error")
	}
}
