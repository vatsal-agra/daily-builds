package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func run(t *testing.T, args ...string) (string, error) {
	t.Helper()
	var b bytes.Buffer
	err := dispatch(args[0], args[1:], &b)
	return b.String(), err
}

func TestCLICommandsEndToEnd(t *testing.T) {
	cases := []struct {
		args []string
		want []string
	}{
		{[]string{"list"}, []string{"figure8", "wh", "symplc"}},
		{[]string{"run", "figure8", "-m", "yoshida4", "-dt", "0.005", "-T", "6.3259"}, []string{"Figure-eight", "force-evals"}},
		{[]string{"bench", "twobody", "-dt", "0.01", "-T", "20"}, []string{"euler", "dopri5", "wh", "max|dE/E0|"}},
		{[]string{"elements", "solar"}, []string{"Jupiter", "5.2026", "0.0484"}},
		{[]string{"bh", "plummer", "-n", "300"}, []string{"rms rel err", "0.10"}},
		{[]string{"order"}, []string{"yoshida4", "observed"}},
		{[]string{"reverse", "figure8", "-dt", "0.01", "-T", "3"}, []string{"reversible (round-off only)", "irreversible"}},
		{[]string{"lyap", "plummer", "-n", "16", "-dt", "0.005", "-T", "20", "-m", "yoshida4"}, []string{"CHAOTIC"}},
		{[]string{"gen", "figure8"}, []string{"body A m=1", "G 1"}},
	}
	for _, c := range cases {
		out, err := run(t, c.args...)
		if err != nil {
			t.Errorf("%v: %v", c.args, err)
			continue
		}
		for _, w := range c.want {
			if !strings.Contains(out, w) {
				t.Errorf("%v: output lacks %q:\n%s", c.args, w, out)
			}
		}
	}
}

func TestCLIErrors(t *testing.T) {
	bad := []struct {
		args []string
		want string
	}{
		{[]string{"run"}, "exactly one scenario"},
		{[]string{"run", "nosuch"}, "unknown built-in"},
		{[]string{"run", "twobody", "-m", "zz"}, "unknown method"},
		{[]string{"run", "twobody", "-dt", "0"}, "dt must be positive"},
		{[]string{"run", "twobody", "-tol", "-1"}, "-tol must be positive"},
		{[]string{"run", "twobody", "-samples", "1"}, "-samples"},
		{[]string{"run", "plummer", "-n", "1"}, "needs 2 <= n"},
		{[]string{"run", "twobody", "-bogus"}, "not defined"},
		{[]string{"run", "/no/such/file.sc"}, "cannot read"},
		{[]string{"report", "twobody"}, "needs -o"},
		{[]string{"frobnicate"}, "unknown command"},
		{[]string{"order", "figure8"}, "two-body"},
	}
	for _, c := range bad {
		out, err := run(t, c.args...)
		msg := out
		if err != nil {
			msg += err.Error()
		}
		if c.args[0] == "order" && err == nil && strings.Contains(out, c.want) {
			continue // order prints per-method errors inline
		}
		if err == nil || !strings.Contains(msg, c.want) {
			t.Errorf("%v: want error containing %q, got err=%v out=%q", c.args, c.want, err, out)
		}
	}
}

func TestCLIWarnsOnUntrustworthyRun(t *testing.T) {
	out, err := run(t, "run", "pythagorean", "-dt", "0.01", "-T", "70")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out, "WARNING") {
		t.Errorf("a blown-up run must warn:\n%s", out)
	}
	out, _ = run(t, "run", "pythagorean", "-m", "dopri5", "-dt", "0.1", "-T", "70")
	if strings.Contains(out, "WARNING") {
		t.Errorf("adaptive run should be clean:\n%s", out)
	}
}

func TestCLIScenarioFileAndReport(t *testing.T) {
	dir := t.TempDir()
	sc := filepath.Join(dir, "x.sc")
	os.WriteFile(sc, []byte("title Mini\nG 1\nbody Sun m=1\nbody P m=1e-3 orbit=Sun a=1 e=0.1\n"), 0o644)
	out, err := run(t, "elements", sc)
	if err != nil || !strings.Contains(out, "0.10000") {
		t.Fatalf("elements from file: %v %s", err, out)
	}
	html := filepath.Join(dir, "r.html")
	if _, err := run(t, "report", sc, "-m", "leapfrog", "-dt", "0.01", "-T", "2", "-o", html); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(html)
	if err != nil || !bytes.Contains(b, []byte("<canvas")) || !bytes.Contains(b, []byte("Mini")) {
		t.Fatalf("report file wrong: %v", err)
	}
	// a malformed file reports its line number
	bad := filepath.Join(dir, "bad.sc")
	os.WriteFile(bad, []byte("G 1\nbody A m=1\nbody B m=x\n"), 0o644)
	if _, err := run(t, "run", bad); err == nil || !strings.Contains(err.Error(), "line 3") {
		t.Errorf("want line 3 error, got %v", err)
	}
}
