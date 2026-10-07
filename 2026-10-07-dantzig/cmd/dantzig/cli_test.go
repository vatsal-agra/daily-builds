package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var binPath string

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "dantzig-cli")
	if err != nil {
		panic(err)
	}
	binPath = filepath.Join(dir, "dantzig")
	if out, err := exec.Command("go", "build", "-o", binPath, ".").CombinedOutput(); err != nil {
		panic(string(out))
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// run executes the CLI and returns stdout+stderr and the exit code.
func run(t *testing.T, stdin string, args ...string) (string, int) {
	t.Helper()
	cmd := exec.Command(binPath, args...)
	var buf bytes.Buffer
	cmd.Stdout, cmd.Stderr = &buf, &buf
	if stdin != "" {
		cmd.Stdin = strings.NewReader(stdin)
	}
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	return buf.String(), code
}

func example(name string) string { return filepath.Join("..", "..", "examples", name) }

func tmpFile(t *testing.T, name, content string) string {
	p := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func mustContain(t *testing.T, out string, subs ...string) {
	t.Helper()
	for _, s := range subs {
		if !strings.Contains(out, s) {
			t.Errorf("output lacks %q:\n%s", s, out)
		}
	}
}

func TestSolveAndCheckExamples(t *testing.T) {
	cases := []struct {
		file   string
		status string
		code   int
		extra  []string
	}{
		{"knapsack.lp", "OPTIMAL", 0, []string{"objective (max): 29"}},
		{"diet.lp", "OPTIMAL", 0, []string{"1268/9"}},
		{"production.lp", "OPTIMAL", 0, []string{"objective (max): 560"}},
		{"infeasible.lp", "INFEASIBLE", 10, nil},
		{"unbounded.lp", "UNBOUNDED", 10, nil},
		{"parity.lp", "INFEASIBLE", 10, nil},
	}
	for _, c := range cases {
		proof := filepath.Join(t.TempDir(), "p.json")
		out, code := run(t, "", "solve", example(c.file), "--proof", proof)
		if code != c.code {
			t.Errorf("%s: exit code %d, want %d\n%s", c.file, code, c.code, out)
		}
		mustContain(t, out, "status: "+c.status+" (exact certificate verified)")
		mustContain(t, out, c.extra...)
		out, code = run(t, "", "check", example(c.file), proof)
		if code != 0 {
			t.Errorf("%s: check exit code %d\n%s", c.file, code, out)
		}
		mustContain(t, out, "VERIFIED")
	}
}

func TestCheckRejectsTamperedProof(t *testing.T) {
	dir := t.TempDir()
	proof := filepath.Join(dir, "p.json")
	run(t, "", "solve", example("knapsack.lp"), "--proof", proof)
	b, _ := os.ReadFile(proof)
	bad := strings.Replace(string(b), `"objective": "29"`, `"objective": "31"`, 1)
	if bad == string(b) {
		t.Fatal("could not tamper")
	}
	badPath := tmpFile(t, "bad.json", bad)
	out, code := run(t, "", "check", example("knapsack.lp"), badPath)
	if code != 3 {
		t.Errorf("exit %d, want 3\n%s", code, out)
	}
	mustContain(t, out, "REJECTED")
	// the proof must not verify against a different model
	other := tmpFile(t, "other.lp", strings.Replace(readFile(t, example("knapsack.lp")), "<= 15", "<= 16", 1))
	out, code = run(t, "", "check", other, proof)
	if code != 3 {
		t.Errorf("accepted proof for another model: %s", out)
	}
}

func readFile(t *testing.T, p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// Review regression: zero-variable model once produced a proof the checker rejected.
func TestRegressionZeroVariableModel(t *testing.T) {
	m := tmpFile(t, "empty.lp", "Minimize\n o: 5\nSubject To\nEnd\n")
	proof := filepath.Join(t.TempDir(), "p.json")
	out, code := run(t, "", "solve", m, "--proof", proof)
	if code != 0 {
		t.Fatalf("exit %d\n%s", code, out)
	}
	out, code = run(t, "", "check", m, proof)
	if code != 0 {
		t.Fatalf("check failed (%d)\n%s", code, out)
	}
}

// Review regression: out-of-range numbers must be rejected with a clear message.
func TestRegressionNumericRange(t *testing.T) {
	big := tmpFile(t, "big.lp", "Minimize\n o: x\nSubject To\n c: 1e400 x >= 1\nEnd\n")
	out, code := run(t, "", "solve", big)
	if code == 0 {
		t.Fatalf("accepted 1e400:\n%s", out)
	}
	mustContain(t, out, "too large", "rescale")
	tiny := tmpFile(t, "tiny.lp", "Minimize\n o: x\nSubject To\n c: 0.000000000000000000001 x >= 1\nEnd\n")
	out, code = run(t, "", "solve", tiny)
	if code == 0 {
		t.Fatalf("accepted 1e-21:\n%s", out)
	}
	mustContain(t, out, "too small", "rescale")
}

// Review regression: --time must bind even when a single LP is expensive.
func TestRegressionTimeLimitBindsOnHardSudoku(t *testing.T) {
	gen, code := run(t, "", "gen", "sudoku", "hard")
	if code != 0 {
		t.Fatal(gen)
	}
	m := tmpFile(t, "sudoku.lp", gen)
	start := time.Now()
	out, _ := run(t, "", "solve", m, "--time", "0.3", "--quiet")
	if el := time.Since(start); el > 4*time.Second {
		t.Errorf("--time 0.3 took %v", el)
	}
	if !strings.Contains(out, "time limit reached") && !strings.Contains(out, "OPTIMAL") {
		t.Errorf("unexpected output:\n%s", out)
	}
}

// Review regression: an endless integer search must stop at the limit and still
// leave a proof that `check` can read (deep trees used to break the JSON decoder).
func TestRegressionEndlessSearchLeavesReadableProof(t *testing.T) {
	m := tmpFile(t, "endless.lp", "Minimize\n o: 0 x\nSubject To\n c: x - y = 0\n d: x + y - 2 z = 1\nBounds\n x free\n y free\n z free\nInteger\n x y z\nEnd\n")
	proof := filepath.Join(t.TempDir(), "p.json")
	out, _ := run(t, "", "solve", m, "--time", "0.5", "--proof", proof)
	mustContain(t, out, "time limit reached", "proof written")
	out, code := run(t, "", "check", m, proof)
	if code != 0 {
		t.Fatalf("check of a limit proof failed (%d):\n%s", code, out)
	}
}

func TestRegressionFlagErrors(t *testing.T) {
	for _, tc := range []struct {
		args []string
		want string
	}{
		{[]string{"solve", example("knapsack.lp"), "--bogus"}, "not defined"},
		{[]string{"solve", example("knapsack.lp"), "--branch", "x"}, "--branch"},
		{[]string{"solve", example("knapsack.lp"), "--time", "-1"}, "non-negative"},
		{[]string{"solve", example("knapsack.lp"), "--values", "some"}, "--values"},
		{[]string{"solve", example("knapsack.lp"), "--proof", "x.json", "--no-proof"}, "contradict"},
		{[]string{"solve"}, "exactly one model"},
		{[]string{"solve", "does-not-exist.lp"}, "no such file"},
		{[]string{"nonsense"}, "unknown command"},
		{[]string{"gen", "tsp"}, "numeric argument"},
		{[]string{"gen", "tsp", "99"}, "3 <= N <= 14"},
		{[]string{"gen", "tsp", "x"}, "not a number"},
		{[]string{"gen", "nosuch", "3"}, "unknown generator"},
	} {
		out, code := run(t, "", tc.args...)
		if code == 0 {
			t.Errorf("%v: expected failure", tc.args)
		}
		if !strings.Contains(out, tc.want) {
			t.Errorf("%v: output lacks %q:\n%s", tc.args, tc.want, out)
		}
		if strings.Contains(out, "Usage of") || strings.Contains(out, "goroutine") {
			t.Errorf("%v: noisy or crashing output:\n%s", tc.args, out)
		}
	}
}

func TestParseErrorShowsPositionAndCaret(t *testing.T) {
	m := tmpFile(t, "bad.lp", "Minimize\n o: x + y\nSubject To\n c: x + y @ 2 <= 4\nEnd\n")
	out, code := run(t, "", "solve", m)
	if code != 2 {
		t.Errorf("exit %d", code)
	}
	mustContain(t, out, "line 4, col 11", "^")
}

func TestStdinModel(t *testing.T) {
	out, code := run(t, "Maximize\n o: x\nSubject To\n c: x <= 7\nEnd\n", "solve", "-", "--quiet")
	if code != 0 {
		t.Fatalf("exit %d\n%s", code, out)
	}
	mustContain(t, out, "objective (max): 7")
}

func TestFmtIsStableForEveryGenerator(t *testing.T) {
	for _, spec := range [][]string{
		{"knapsack", "20", "1"}, {"setcover", "15", "20", "1"}, {"assignment", "5", "1"}, {"tsp", "5", "1"},
		{"sudoku"}, {"facility", "3", "5", "1"}, {"transport", "3", "4", "1"}, {"diet"},
	} {
		text, code := run(t, "", append([]string{"gen"}, spec...)...)
		if code != 0 {
			t.Fatalf("gen %v: %s", spec, text)
		}
		path := tmpFile(t, "g.lp", text)
		again, code := run(t, "", "fmt", path)
		if code != 0 || again != text {
			t.Errorf("gen %v: fmt(gen) differs from gen (code %d)", spec, code)
		}
	}
}
