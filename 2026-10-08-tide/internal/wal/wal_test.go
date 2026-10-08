package wal

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func collect(t *testing.T, path string) ([]string, int64, *WAL) {
	t.Helper()
	var got []string
	w, dropped, err := Open(path, func(r []byte) error { got = append(got, string(r)); return nil })
	if err != nil {
		t.Fatal(err)
	}
	return got, dropped, w
}

func TestRoundTripAndAppendAfterReopen(t *testing.T) {
	p := filepath.Join(t.TempDir(), "wal")
	_, _, w := collect(t, p)
	for i := 0; i < 100; i++ {
		w.Append([]byte(fmt.Sprintf("rec-%d", i)))
	}
	w.Close()
	got, dropped, w := collect(t, p)
	if len(got) != 100 || dropped != 0 || got[99] != "rec-99" {
		t.Fatalf("got %d recs dropped=%d", len(got), dropped)
	}
	w.Append([]byte("more"))
	w.Close()
	got, _, w = collect(t, p)
	w.Close()
	if len(got) != 101 || got[100] != "more" {
		t.Fatalf("append after reopen lost: %d", len(got))
	}
}

func TestTornTailEveryCutPoint(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "wal")
	_, _, w := collect(t, p)
	for i := 0; i < 5; i++ {
		w.Append([]byte(fmt.Sprintf("record-number-%d", i)))
	}
	w.Close()
	full, _ := os.ReadFile(p)
	frame := len(full) / 5
	for cut := 0; cut <= len(full); cut++ {
		q := filepath.Join(dir, "cut")
		os.WriteFile(q, full[:cut], 0o644)
		got, dropped, w := collect(t, q)
		wantRecs := cut / frame
		if len(got) != wantRecs || dropped != int64(cut-wantRecs*frame) {
			t.Fatalf("cut=%d: recs=%d want %d dropped=%d", cut, len(got), wantRecs, dropped)
		}
		// log must be usable after recovery
		w.Append([]byte("after"))
		w.Close()
		got, d2, w := collect(t, q)
		w.Close()
		if len(got) != wantRecs+1 || got[len(got)-1] != "after" || d2 != 0 {
			t.Fatalf("cut=%d: post-recovery append broken", cut)
		}
	}
}

func TestCorruptByteStopsReplay(t *testing.T) {
	p := filepath.Join(t.TempDir(), "wal")
	_, _, w := collect(t, p)
	for i := 0; i < 4; i++ {
		w.Append([]byte("abcdefgh"))
	}
	w.Close()
	b, _ := os.ReadFile(p)
	b[16+8+3] ^= 0xff // flip a payload byte of record #2
	os.WriteFile(p, b, 0o644)
	got, dropped, w := collect(t, p)
	w.Close()
	if len(got) != 1 || dropped != 3*16 {
		t.Fatalf("recs=%d dropped=%d", len(got), dropped)
	}
}

func TestReset(t *testing.T) {
	p := filepath.Join(t.TempDir(), "wal")
	_, _, w := collect(t, p)
	w.Append([]byte("x"))
	w.Sync()
	if err := w.Reset(); err != nil || w.Size() != 0 {
		t.Fatal(err)
	}
	w.Append([]byte("y"))
	w.Close()
	got, _, w := collect(t, p)
	w.Close()
	if len(got) != 1 || got[0] != "y" {
		t.Fatalf("got %v", got)
	}
}
