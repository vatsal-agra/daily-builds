package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

var bin string

func TestMain(m *testing.M) {
	dir, _ := os.MkdirTemp("", "wf")
	bin = filepath.Join(dir, "wf")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		panic(string(out))
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

func run(t *testing.T, stdin string, args ...string) (string, int) {
	t.Helper()
	c := exec.Command(bin, args...)
	c.Stdin = strings.NewReader(stdin)
	out, err := c.CombinedOutput()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	}
	return string(out), code
}

func TestCLIPipeline(t *testing.T) {
	dir := t.TempDir()
	mp := filepath.Join(dir, "m.txt")
	if out, code := run(t, "", "gen", "-kind", "rooms", "-w", "50", "-h", "24", "-seed", "5", "-o", mp); code != 0 {
		t.Fatal(out)
	}
	out, code := run(t, "", "compare", "-map", mp)
	if code != 0 || !strings.Contains(out, "dijkstra") || !strings.Contains(out, "jps") || !strings.Contains(out, "theta") || !strings.Contains(out, "hpa") {
		t.Fatalf("compare: %d %s", code, out)
	}
	for _, a := range []string{"dijkstra", "astar", "jps", "theta", "hpa"} {
		out, code := run(t, "", "solve", "-map", mp, "-algo", a, "-draw")
		if code != 0 || !strings.Contains(out, "cost=") || !strings.Contains(out, "*") {
			t.Fatalf("solve %s: %d %s", a, code, out)
		}
	}
	out, code = run(t, "", "explore", "-map", mp, "-radius", "3", "-draw")
	if code != 0 || !strings.Contains(out, "reached goal") || !strings.Contains(out, "work") {
		t.Fatalf("explore: %d %s", code, out)
	}
	html := filepath.Join(dir, "o.html")
	if out, code = run(t, "", "html", "-map", mp, "-o", html); code != 0 {
		t.Fatal(out)
	}
	b, _ := os.ReadFile(html)
	if !strings.Contains(string(b), "d* lite explore") || !strings.Contains(string(b), `"name":"theta*"`) {
		t.Fatal("html missing sections")
	}
}

func TestCLIStdinAndUnreachable(t *testing.T) {
	out, code := run(t, "S.#.G\n..#..\n", "solve", "-map", "-", "-algo", "astar")
	if code != 3 || !strings.Contains(out, "no path") {
		t.Fatalf("unreachable: %d %s", code, out)
	}
	out, code = run(t, "S...G\n", "solve", "-map", "-", "-algo", "jps")
	if code != 0 || !strings.Contains(out, "cost=    4.000") {
		t.Fatalf("straight line: %d %s", code, out)
	}
}

func TestCLIErrors(t *testing.T) {
	for _, args := range [][]string{{}, {"nope"}, {"solve"}, {"solve", "-map", "/does/not/exist"}, {"gen", "-kind", "zzz"},
		{"gen", "-w", "2"}, {"explore", "-map", "-", "-radius", "0"}, {"fuzz", "-n", "0"}, {"bench", "-size", "5"}} {
		out, code := run(t, "S.G\n", args...)
		if code == 0 || out == "" {
			t.Errorf("%v: expected failure with message, got code %d out %q", args, code, out)
		}
	}
	if out, code := run(t, "S.~G\n", "solve", "-map", "-", "-algo", "jps"); code == 0 || !strings.Contains(out, "uniform") {
		t.Errorf("jps on terrain: %d %s", code, out)
	}
}

func TestCLIFuzzAndBench(t *testing.T) {
	out, code := run(t, "", "fuzz", "-n", "120", "-seed", "9000")
	if code != 0 || !strings.Contains(out, "fuzz OK") {
		t.Fatalf("fuzz: %d %s", code, out)
	}
	out, code = run(t, "", "bench", "-size", "40", "-seeds", "2")
	if code != 0 || !strings.Contains(out, "cost/optimal") || !strings.Contains(out, "caves") {
		t.Fatalf("bench: %d %s", code, out)
	}
}
