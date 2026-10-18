package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func project(t *testing.T, mfSrc string, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "Mortisefile"), []byte(mfSrc), 0o644)
	for n, b := range files {
		os.WriteFile(filepath.Join(dir, n), []byte(b), 0o644)
	}
	return dir
}

func mortise(t *testing.T, dir string, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	var so, se bytes.Buffer
	code = run(append([]string{"-C", dir}, args...), &so, &se)
	return code, so.String(), se.String()
}

const simple = "default out\nout: in\n    tr a-z A-Z < in > out\n"

func TestCLIBuildRebuildAndExitCodes(t *testing.T) {
	dir := project(t, simple, map[string]string{"in": "abc\n"})
	code, so, _ := mortise(t, dir)
	if code != 0 || !strings.Contains(so, "1 ran") {
		t.Fatalf("code=%d out=%q", code, so)
	}
	code, so, _ = mortise(t, dir)
	if code != 0 || !strings.Contains(so, "1 up to date") {
		t.Fatalf("code=%d out=%q", code, so)
	}
	if b, _ := os.ReadFile(filepath.Join(dir, "out")); string(b) != "ABC\n" {
		t.Fatalf("out=%q", b)
	}
}

func TestCLIErrorsHaveExitCode2AndPositions(t *testing.T) {
	if code, _, se := mortise(t, t.TempDir()); code != 2 {
		t.Fatalf("missing Mortisefile: code %d %q", code, se)
	}
	dir := project(t, "a: b\n    ok\nnonsense\n", nil)
	code, _, se := mortise(t, dir)
	if code != 2 || !strings.Contains(se, "Mortisefile:3:") {
		t.Fatalf("parse error: %d %q", code, se)
	}
	dir = project(t, simple, map[string]string{"in": "x"})
	code, _, se = mortise(t, dir, "zzzzzz")
	if code != 2 || !strings.Contains(se, "no rule to make target") {
		t.Fatalf("%d %q", code, se)
	}
	code, _, se = mortise(t, dir, "ot")
	if code != 2 || !strings.Contains(se, `did you mean "out"`) {
		t.Fatalf("suggestion: %d %q", code, se)
	}
	dir = project(t, "x: y\n    touch x\ny: x\n    touch y\n", nil)
	if code, _, se = mortise(t, dir, "x"); code != 2 || !strings.Contains(se, "dependency cycle: x -> y -> x") {
		t.Fatalf("cycle: %d %q", code, se)
	}
	dir = project(t, "x:\n    true\n", nil)
	if code, _, _ = mortise(t, dir); code != 2 {
		t.Fatal("no default target must be a usage error")
	}
	if code, _, _ = mortise(t, dir, "--bogus"); code != 2 {
		t.Fatal("bad flag")
	}
}

func TestCLIFailureExitCode1(t *testing.T) {
	dir := project(t, "default a\na:\n    echo nope >&2; exit 7\n", nil)
	code, so, se := mortise(t, dir)
	if code != 1 || !strings.Contains(se, "FAILED: a") || !strings.Contains(se, "exit status 7") || !strings.Contains(so, "1 failed") {
		t.Fatalf("code=%d\nout=%s\nerr=%s", code, so, se)
	}
}

func TestCLIDryRunAndClean(t *testing.T) {
	dir := project(t, simple, map[string]string{"in": "abc\n"})
	code, so, _ := mortise(t, dir, "-n")
	if code != 0 || !strings.Contains(so, "would build out") || !strings.Contains(so, "never built") {
		t.Fatalf("%d %q", code, so)
	}
	if _, err := os.Stat(filepath.Join(dir, "out")); err == nil {
		t.Fatal("-n built something")
	}
	mortise(t, dir)
	code, so, _ = mortise(t, dir, "clean")
	if code != 0 || !strings.Contains(so, "removed 1 output") {
		t.Fatalf("%d %q", code, so)
	}
	if _, err := os.Stat(filepath.Join(dir, "in")); err != nil {
		t.Fatal("clean must never delete sources")
	}
	code, so, _ = mortise(t, dir)
	if code != 0 || !strings.Contains(so, "from cache") {
		t.Fatalf("rebuild after clean should come from the cache: %q", so)
	}
	mortise(t, dir, "clean", "--all")
	if _, err := os.Stat(filepath.Join(dir, ".mortise")); err == nil {
		t.Fatal("clean --all must remove .mortise")
	}
}

func TestCLIAbsoluteTargetInsideProject(t *testing.T) {
	dir := project(t, simple, map[string]string{"in": "abc\n"})
	code, so, se := mortise(t, dir, filepath.Join(dir, "out"))
	if code != 0 || !strings.Contains(so, "1 ran") {
		t.Fatalf("%d %q %q", code, so, se)
	}
}

func TestCLILockPreventsConcurrentRuns(t *testing.T) {
	dir := project(t, simple, map[string]string{"in": "abc\n"})
	unlock, err := lock(dir)
	if err != nil {
		t.Fatal(err)
	}
	code, _, se := mortise(t, dir)
	unlock()
	if code != 2 || !strings.Contains(se, "already running") {
		t.Fatalf("%d %q", code, se)
	}
	if code, _, _ := mortise(t, dir); code != 0 {
		t.Fatal("lock must be released")
	}
}
