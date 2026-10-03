package index

import (
	"os"
	"path/filepath"
	"testing"

	"landmark/internal/fp"
)

func hashesAt(offset int32, keys ...uint32) []fp.Hash {
	var out []fp.Hash
	for i, k := range keys {
		out = append(out, fp.Hash{H: k, T: offset + int32(i*3)})
	}
	return out
}

func build(t *testing.T) *Index {
	t.Helper()
	ix := New(fp.Default())
	keys := func(base uint32, n int) []uint32 {
		var k []uint32
		for i := 0; i < n; i++ {
			k = append(k, base+uint32(i)*7)
		}
		return k
	}
	if _, err := ix.Add("alpha", hashesAt(0, keys(100, 60)...), 500); err != nil {
		t.Fatal(err)
	}
	if _, err := ix.Add("beta", hashesAt(0, keys(5000, 60)...), 500); err != nil {
		t.Fatal(err)
	}
	return ix
}

func TestQueryFindsSongAndOffset(t *testing.T) {
	ix := build(t)
	// a clip made of alpha's landmarks 10..39, whose clip-time is (song time − 30)
	var q []fp.Hash
	for i := 10; i < 40; i++ {
		q = append(q, fp.Hash{H: 100 + uint32(i)*7, T: int32(i*3) - 30})
	}
	ms := ix.Query(q)
	if len(ms) != 1 || ms[0].Song.Name != "alpha" {
		t.Fatalf("matches %+v", ms)
	}
	if ms[0].Offset != 30 || ms[0].Score < 30 {
		t.Fatalf("offset %d score %d", ms[0].Offset, ms[0].Score)
	}
	if ms[0].Alt != 0 {
		t.Fatalf("clean match should have no rival offset, got %d", ms[0].Alt)
	}
}

func TestRivalOffsetDetectedForRepeatedMaterial(t *testing.T) {
	ix := New(fp.Default())
	var hs []fp.Hash
	for rep := 0; rep < 2; rep++ { // the same 20 landmarks occur at frame 0.. and again at 400..
		for i := 0; i < 20; i++ {
			hs = append(hs, fp.Hash{H: uint32(900 + i*11), T: int32(rep*400 + i*4)})
		}
	}
	if _, err := ix.Add("loop", hs, 800); err != nil {
		t.Fatal(err)
	}
	var q []fp.Hash
	for i := 0; i < 20; i++ {
		q = append(q, fp.Hash{H: uint32(900 + i*11), T: int32(i * 4)})
	}
	m := ix.Query(q)[0]
	if m.Alt < 18 || m.Score < 18 {
		t.Fatalf("looped song should show two equal peaks: score %d alt %d", m.Score, m.Alt)
	}
	pol := Policy{MinScore: 10, Ratio: 2, LoopFactor: 4}
	if v := pol.Decide([]Match{m}); v.Found || !v.OffsetAmbiguous {
		t.Fatalf("20 votes with an equal rival must not pass MinScore×LoopFactor=40: %+v", v)
	}
	pol.LoopFactor = 1
	if v := pol.Decide([]Match{m}); !v.Found || !v.OffsetAmbiguous {
		t.Fatalf("should accept but flag ambiguity: %+v", v)
	}
}

func TestPolicyDecisions(t *testing.T) {
	pol := Policy{MinScore: 10, Ratio: 2, LoopFactor: 4}
	mk := func(score, alt int) Match { return Match{Score: score, Alt: alt, Song: Song{Name: "s"}} }
	cases := []struct {
		name string
		ms   []Match
		want bool
	}{
		{"empty", nil, false},
		{"strong", []Match{mk(50, 2), mk(4, 1)}, true},
		{"below floor", []Match{mk(9, 0)}, false},
		{"ambiguous between songs", []Match{mk(30, 2), mk(20, 2)}, false},
		{"periodic and weak", []Match{mk(30, 25)}, false},
		{"periodic but huge", []Match{mk(90, 80)}, true},
	}
	for _, c := range cases {
		if got := pol.Decide(c.ms).Found; got != c.want {
			t.Errorf("%s: Found=%v want %v", c.name, got, c.want)
		}
	}
}

func TestSaveLoadRoundTrip(t *testing.T) {
	ix := build(t)
	path := filepath.Join(t.TempDir(), "x.lmk")
	if err := ix.Save(path); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path + ".tmp"); err == nil {
		t.Fatal("temp file left behind")
	}
	got, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Songs) != 2 || got.NumKeys() != ix.NumKeys() || got.Params != ix.Params {
		t.Fatalf("round trip mismatch: %d songs %d keys", len(got.Songs), got.NumKeys())
	}
	for k, want := range ix.table {
		have := got.table[k]
		if len(have) != len(want) || (len(want) > 0 && have[0] != want[0]) {
			t.Fatalf("postings for %d differ", k)
		}
	}
}

func TestLoadRejectsDamage(t *testing.T) {
	ix := build(t)
	dir := t.TempDir()
	path := filepath.Join(dir, "x.lmk")
	if err := ix.Save(path); err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(path)
	cases := map[string][]byte{
		"empty":     {},
		"bad magic": append([]byte("NOTANIDX"), raw[8:]...),
		"truncated": raw[:len(raw)/2],
		"bitflip":   append(append([]byte{}, raw[:50]...), append([]byte{raw[50] ^ 0xFF}, raw[51:]...)...),
	}
	for name, b := range cases {
		p := filepath.Join(dir, name)
		os.WriteFile(p, b, 0o644)
		if _, err := Load(p); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
	if _, err := Load(filepath.Join(dir, "missing")); err == nil {
		t.Error("missing file should error")
	}
}

func TestAddValidation(t *testing.T) {
	ix := New(fp.Default())
	if _, err := ix.Add("", hashesAt(0, 1), 1); err == nil {
		t.Error("empty name accepted")
	}
	if _, err := ix.Add("a", nil, 1); err == nil {
		t.Error("no landmarks accepted")
	}
	ix.Add("a", hashesAt(0, 1, 2), 1)
	if _, err := ix.Add("a", hashesAt(0, 1), 1); err == nil {
		t.Error("duplicate accepted")
	}
	if !ix.Has("a") || ix.Has("b") {
		t.Error("Has wrong")
	}
}
