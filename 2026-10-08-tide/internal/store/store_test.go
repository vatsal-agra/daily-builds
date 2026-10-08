package store

import (
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func lbl(name string, kv ...string) Labels {
	m := map[string]string{NameLabel: name}
	for i := 0; i < len(kv); i += 2 {
		m[kv[i]] = kv[i+1]
	}
	return NewLabels(m)
}

func mustOpen(t *testing.T, dir string) *Store {
	t.Helper()
	s, err := Open(Options{Dir: dir, ChunkSize: 10})
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func eq(t *testing.T, name, val string) *Matcher {
	m, err := NewMatcher(MatchEq, name, val)
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func sel(t *testing.T, s *Store, name string) []Sample {
	t.Helper()
	out, err := s.Select([]*Matcher{eq(t, NameLabel, name)}, 0, 1<<60)
	if err != nil {
		t.Fatal(err)
	}
	if len(out) == 0 {
		return nil
	}
	return out[0].Samples
}

func fill(t *testing.T, s *Store, name string, from, n int) {
	t.Helper()
	var pts []Point
	for i := from; i < from+n; i++ {
		pts = append(pts, Point{lbl(name, "h", "a"), int64(i) * 1000, float64(i)})
	}
	r, err := s.Append(pts)
	if err != nil || r.Accepted != n {
		t.Fatalf("append: %+v %v", r, err)
	}
}

func TestAppendSelectAcrossChunks(t *testing.T) {
	s := mustOpen(t, t.TempDir())
	defer s.Close()
	fill(t, s, "m", 0, 95)
	got := sel(t, s, "m")
	if len(got) != 95 || got[94].V != 94 || got[0].T != 0 {
		t.Fatalf("got %d samples", len(got))
	}
	out, _ := s.Select([]*Matcher{eq(t, NameLabel, "m")}, 10_000, 20_000)
	if len(out[0].Samples) != 11 {
		t.Fatalf("range select got %d", len(out[0].Samples))
	}
}

func TestRejections(t *testing.T) {
	s := mustOpen(t, t.TempDir())
	defer s.Close()
	fill(t, s, "m", 0, 3)
	r, _ := s.Append([]Point{
		{lbl("m", "h", "a"), 2000, 5}, // duplicate ts
		{lbl("m", "h", "a"), 1000, 5}, // older
		{lbl("m", "h", "a"), 9000, nan()},
		{NewLabels(map[string]string{"x": "y"}), 1, 1}, // no name
		{NewLabels(map[string]string{NameLabel: "m", "bad-name": "y"}), 1, 1},
		{lbl("m", "h", "a"), 3000, 3},
	})
	if r.Accepted != 1 || r.OutOfOrder != 2 || r.Invalid != 3 || r.FirstInvalid == "" {
		t.Fatalf("%+v", r)
	}
}

func TestCrashRecoveryFromWAL(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 55)
	// simulate crash: no Close, no flush; just drop the handle
	s.crash()
	s2 := mustOpen(t, dir)
	defer s2.Close()
	if got := sel(t, s2, "m"); len(got) != 55 || got[54].V != 54 {
		t.Fatalf("recovered %d", len(got))
	}
	if s2.Stats().RecoveredWAL != 55 {
		t.Fatalf("stats %+v", s2.Stats())
	}
	fill(t, s2, "m", 55, 5) // appends continue after recovery
	if got := sel(t, s2, "m"); len(got) != 60 {
		t.Fatalf("%d", len(got))
	}
}

func TestTornWALTail(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 20)
	s.crash()
	p := filepath.Join(dir, "wal.log")
	b, _ := os.ReadFile(p)
	os.WriteFile(p, b[:len(b)-5], 0o644) // tear the last record
	s2 := mustOpen(t, dir)
	defer s2.Close()
	if got := sel(t, s2, "m"); len(got) != 19 {
		t.Fatalf("expected 19 intact samples, got %d", len(got))
	}
	if s2.Stats().WALTornBytes == 0 {
		t.Fatal("torn bytes not reported")
	}
}

func TestFlushAndReopen(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 100)
	if err := s.Flush(); err != nil {
		t.Fatal(err)
	}
	st := s.Stats()
	if st.Blocks != 1 || st.HeadSamples != 0 || st.WALBytes != 0 || st.BlockSamples != 100 {
		t.Fatalf("%+v", st)
	}
	fill(t, s, "m", 100, 10)
	s.Close()
	s2 := mustOpen(t, dir)
	defer s2.Close()
	got := sel(t, s2, "m")
	if len(got) != 110 || got[109].V != 109 {
		t.Fatalf("got %d", len(got))
	}
}

func TestCrashBetweenBlockAndWALReset(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 30)
	walCopy, _ := os.ReadFile(filepath.Join(dir, "wal.log"))
	s.Flush()
	s.Close()
	os.WriteFile(filepath.Join(dir, "wal.log"), walCopy, 0o644) // WAL "survives" the crash
	s2 := mustOpen(t, dir)
	defer s2.Close()
	got := sel(t, s2, "m")
	if len(got) != 30 {
		t.Fatalf("duplicates leaked: %d", len(got))
	}
	for i, x := range got {
		if x.T != int64(i)*1000 {
			t.Fatal("not sorted/deduped")
		}
	}
}

func TestCorruptBlockDetected(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 30)
	s.Flush()
	s.Close()
	files, _ := filepath.Glob(filepath.Join(dir, "blocks", "*.blk"))
	b, _ := os.ReadFile(files[0])
	b[20] ^= 0x55
	os.WriteFile(files[0], b, 0o644)
	if _, err := Open(Options{Dir: dir}); err == nil {
		t.Fatal("expected corrupt block error")
	}
}

func TestAutoFlushByDuration(t *testing.T) {
	s, _ := Open(Options{Dir: t.TempDir(), BlockDuration: time.Minute})
	defer s.Close()
	fill(t, s, "m", 0, 100) // 99s span > 1m
	if s.Stats().Blocks != 1 {
		t.Fatalf("no auto flush: %+v", s.Stats())
	}
}

func TestCompactionDedupesAndShrinks(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 25)
	s.Flush()
	fill(t, s, "m", 25, 25)
	s.Flush()
	// overlapping re-send with different values for ts 40..49 in a third block
	var pts []Point
	for i := 20; i < 30; i++ {
		pts = append(pts, Point{lbl("m", "h", "a"), int64(i) * 1000, 999})
	}
	// head is empty after flush so these are accepted
	s.Append(pts)
	s.Flush()
	before := s.Stats()
	res, err := s.Compact()
	if err != nil || res.BlocksBefore != 3 || res.BlocksAfter != 1 || res.Duplicates != 10 {
		t.Fatalf("%+v %v", res, err)
	}
	got := sel(t, s, "m")
	if len(got) != 50 || got[25].V != 999 || got[19].V != 19 {
		t.Fatalf("after compaction: %d %+v", len(got), got[25])
	}
	if s.Stats().BlockSamples != 50 || before.BlockSamples != 60 {
		t.Fatal("sample accounting wrong")
	}
	files, _ := filepath.Glob(filepath.Join(dir, "blocks", "*"))
	if len(files) != 1 {
		t.Fatalf("old blocks not removed: %v", files)
	}
}

func TestInterruptedCompactionResolved(t *testing.T) {
	dir := t.TempDir()
	s := mustOpen(t, dir)
	fill(t, s, "m", 0, 10)
	s.Flush()
	fill(t, s, "m", 10, 10)
	s.Flush()
	// snapshot old blocks, compact, then restore old blocks as if delete never happened
	files, _ := filepath.Glob(filepath.Join(dir, "blocks", "*.blk"))
	saved := map[string][]byte{}
	for _, f := range files {
		saved[f], _ = os.ReadFile(f)
	}
	if _, err := s.Compact(); err != nil {
		t.Fatal(err)
	}
	s.Close()
	for f, b := range saved {
		os.WriteFile(f, b, 0o644)
	}
	s2 := mustOpen(t, dir)
	defer s2.Close()
	if s2.Stats().Blocks != 1 {
		t.Fatalf("stale sources not cleaned: %d blocks", s2.Stats().Blocks)
	}
	if len(sel(t, s2, "m")) != 20 {
		t.Fatal("data lost")
	}
}

func TestRetention(t *testing.T) {
	s := mustOpen(t, t.TempDir())
	defer s.Close()
	fill(t, s, "m", 0, 10)
	s.Flush()
	fill(t, s, "m", 100, 10)
	s.Flush()
	n, err := s.DropBefore(50_000)
	if err != nil || n != 1 {
		t.Fatalf("%d %v", n, err)
	}
	if got := sel(t, s, "m"); len(got) != 10 || got[0].T != 100_000 {
		t.Fatalf("%d", len(got))
	}
}

func TestMatchers(t *testing.T) {
	s := mustOpen(t, t.TempDir())
	defer s.Close()
	for _, h := range []string{"a1", "a2", "b1"} {
		s.Append([]Point{{lbl("cpu", "host", h, "dc", "x"), 1000, 1}, {lbl("mem", "host", h), 1000, 1}})
	}
	count := func(ms ...*Matcher) int {
		out, _ := s.Select(ms, 0, 1<<60)
		return len(out)
	}
	re := func(tp MatchType, n, v string) *Matcher {
		m, err := NewMatcher(tp, n, v)
		if err != nil {
			t.Fatal(err)
		}
		return m
	}
	if count(eq(t, NameLabel, "cpu")) != 3 {
		t.Fatal("eq")
	}
	if count(eq(t, NameLabel, "cpu"), re(MatchRe, "host", "a.*")) != 2 {
		t.Fatal("re")
	}
	if count(eq(t, NameLabel, "cpu"), re(MatchNre, "host", "a.*")) != 1 {
		t.Fatal("nre")
	}
	if count(eq(t, NameLabel, "mem"), re(MatchNe, "dc", "x")) != 3 { // missing label != "x"
		t.Fatal("ne on missing label")
	}
	if count(re(MatchRe, NameLabel, "c")) != 0 { // regex is fully anchored
		t.Fatal("anchoring")
	}
	if _, err := NewMatcher(MatchRe, "a", "("); err == nil {
		t.Fatal("bad regex accepted")
	}
}

func TestRandomizedAgainstModel(t *testing.T) {
	rng := rand.New(rand.NewSource(3))
	dir := t.TempDir()
	s := mustOpen(t, dir)
	model := map[string]map[int64]float64{}
	last := map[string]int64{}
	for round := 0; round < 40; round++ {
		var pts []Point
		for i := 0; i < 50; i++ {
			name := fmt.Sprintf("m%d", rng.Intn(4))
			last[name] += 1 + rng.Int63n(5000)
			v := float64(rng.Intn(100))
			pts = append(pts, Point{lbl(name), last[name], v})
			if model[name] == nil {
				model[name] = map[int64]float64{}
			}
			model[name][last[name]] = v
		}
		if _, err := s.Append(pts); err != nil {
			t.Fatal(err)
		}
		switch rng.Intn(6) {
		case 0:
			s.Flush()
		case 1:
			s.Compact()
		case 2:
			s.Close()
			s = mustOpen(t, dir)
		}
	}
	defer s.Close()
	for name, m := range model {
		got := sel(t, s, name)
		if len(got) != len(m) {
			t.Fatalf("%s: %d vs %d", name, len(got), len(m))
		}
		for i, x := range got {
			if m[x.T] != x.V || (i > 0 && got[i-1].T >= x.T) {
				t.Fatalf("%s mismatch at %d", name, x.T)
			}
		}
	}
}

func nan() float64 { var z float64; return z / z }

// crash simulates kill -9: file handles vanish with no flush or clean shutdown.
func (s *Store) crash() { s.wal.Close(); s.lock.Close() } // Append already fsynced; nothing is flushed here
