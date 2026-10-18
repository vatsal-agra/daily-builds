package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// fingerprint summarises the observable state of the watched inputs: size and
// mtime of every file, plus the directory listing of each containing directory
// so that new files (which a $(glob) would pick up) are noticed.
func fingerprint(root string, inputs []string) string {
	h := sha256.New()
	dirs := map[string]bool{}
	for _, in := range inputs {
		p := in
		if !filepath.IsAbs(p) {
			p = filepath.Join(root, p)
		}
		if st, err := os.Stat(p); err == nil {
			fmt.Fprintf(h, "%s|%d|%d\n", in, st.Size(), st.ModTime().UnixNano())
		} else {
			fmt.Fprintf(h, "%s|missing\n", in)
		}
		dirs[filepath.Dir(p)] = true
	}
	names := make([]string, 0, len(dirs))
	for d := range dirs {
		names = append(names, d)
	}
	sort.Strings(names)
	for _, d := range names {
		ents, _ := os.ReadDir(d)
		var ns []string
		for _, e := range ents {
			ns = append(ns, e.Name())
		}
		fmt.Fprintf(h, "dir %s: %s\n", d, strings.Join(ns, ","))
	}
	return hex.EncodeToString(h.Sum(nil))
}

// watchLoop runs buildOnce, then re-runs it whenever an input changes. It
// returns when ctx is cancelled. buildOnce returns the inputs to watch.
func watchLoop(ctx context.Context, root string, poll time.Duration, stdout io.Writer, buildOnce func() []string) {
	for round := 1; ; round++ {
		inputs := buildOnce()
		fp := fingerprint(root, inputs)
		fmt.Fprintf(stdout, "mortise: watching %d input(s); change one to rebuild (Ctrl-C to stop)\n", len(inputs))
		t := time.NewTicker(poll)
		changed := false
		for !changed {
			select {
			case <-ctx.Done():
				t.Stop()
				return
			case <-t.C:
				if fingerprint(root, inputs) != fp {
					changed = true
				}
			}
		}
		t.Stop()
		// debounce: wait until the inputs stop changing (editors write in bursts)
		for {
			cur := fingerprint(root, inputs)
			select {
			case <-ctx.Done():
				return
			case <-time.After(poll):
			}
			if fingerprint(root, inputs) == cur {
				break
			}
		}
		fmt.Fprintln(stdout, "mortise: change detected, rebuilding")
	}
}
