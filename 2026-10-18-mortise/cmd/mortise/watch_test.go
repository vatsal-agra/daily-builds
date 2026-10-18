package main

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestWatchRebuildsOnChangeAndNewFiles(t *testing.T) {
	dir := project(t, "default all.txt\nSRC = $(glob src/*.txt)\nall.txt: $(SRC)\n    cat $(SRC) > all.txt\n", nil)
	os.Mkdir(filepath.Join(dir, "src"), 0o755)
	os.WriteFile(filepath.Join(dir, "src", "a.txt"), []byte("A"), 0o644)

	ctx, cancel := context.WithCancel(context.Background())
	var mu sync.Mutex
	var so, se bytes.Buffer
	sw := &syncW{mu: &mu, w: &so}
	done := make(chan int, 1)
	go func() { done <- runCtx(ctx, []string{"-C", dir, "watch"}, sw, &syncW{mu: &mu, w: &se}) }()

	wait := func(want string) {
		t.Helper()
		deadline := time.Now().Add(6 * time.Second)
		for time.Now().Before(deadline) {
			b, _ := os.ReadFile(filepath.Join(dir, "all.txt"))
			if string(b) == want {
				return
			}
			time.Sleep(50 * time.Millisecond)
		}
		mu.Lock()
		defer mu.Unlock()
		t.Fatalf("all.txt never became %q\nstdout:\n%s\nstderr:\n%s", want, so.String(), se.String())
	}
	wait("A")
	time.Sleep(300 * time.Millisecond)
	os.WriteFile(filepath.Join(dir, "src", "a.txt"), []byte("A2"), 0o644)
	wait("A2")
	os.WriteFile(filepath.Join(dir, "src", "b.txt"), []byte("B"), 0o644) // new file picked up by glob
	wait("A2B")
	cancel()
	select {
	case code := <-done:
		if code != 0 {
			t.Fatalf("exit %d", code)
		}
	case <-time.After(4 * time.Second):
		t.Fatal("watch did not stop on cancel")
	}
	mu.Lock()
	defer mu.Unlock()
	if strings.Count(so.String(), "change detected") < 2 {
		t.Fatalf("stdout:\n%s", so.String())
	}
}

type syncW struct {
	mu *sync.Mutex
	w  *bytes.Buffer
}

func (s *syncW) Write(b []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.w.Write(b)
}

func TestFingerprintDetectsDirListingChanges(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "a"), []byte("1"), 0o644)
	f1 := fingerprint(dir, []string{"a"})
	if f1 != fingerprint(dir, []string{"a"}) {
		t.Fatal("fingerprint must be stable")
	}
	os.WriteFile(filepath.Join(dir, "b"), nil, 0o644)
	if f1 == fingerprint(dir, []string{"a"}) {
		t.Fatal("new sibling file must change the fingerprint")
	}
}
