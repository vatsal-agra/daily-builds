package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

var bin string

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "domtest")
	if err != nil {
		panic(err)
	}
	bin = filepath.Join(dir, "dom")
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		panic(string(out))
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

type res struct {
	out, err string
	code     int
}

func dom(t *testing.T, args ...string) res {
	t.Helper()
	cmd := exec.Command(bin, args...)
	var o, e bytes.Buffer
	cmd.Stdout, cmd.Stderr = &o, &e
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	return res{o.String(), e.String(), code}
}

func write(t *testing.T, name, content string) string {
	p := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestRunEveryExampleEveryWay(t *testing.T) {
	files, _ := filepath.Glob("../../examples/*.dom")
	for _, f := range files {
		ref := dom(t, "run", "-O0", "-interp", f)
		if ref.code != 0 {
			t.Fatalf("%s: reference run failed: %+v", f, ref)
		}
		for _, args := range [][]string{{"-O0"}, {"-O1"}, {"-O2"}, {"-O3"}, {"-O2", "-interp"}, {"-O3", "-regs", "4"}, {"-O2", "-regs", "6"}} {
			r := dom(t, append(append([]string{"run"}, args...), f)...)
			if r.code != 0 || r.out != ref.out || r.err != ref.err {
				t.Errorf("%s %v: differs from reference\n got %q %q (rc %d)\nwant %q %q", filepath.Base(f), args, r.out, r.err, r.code, ref.out, ref.err)
			}
		}
	}
}

func TestSubcommands(t *testing.T) {
	fib := "../../examples/fib.dom"
	if r := dom(t, "ir", "-O2", "-stats", fib); r.code != 0 || !strings.Contains(r.out, "func @fib") || !strings.Contains(r.err, "mem2reg=") {
		t.Errorf("ir: %+v", r)
	}
	if r := dom(t, "ir", "-passes", "simplifycfg,mem2reg", "-trace", fib); r.code != 0 || !strings.Contains(r.err, "[pass] mem2reg") || strings.Contains(r.out, "alloca") {
		t.Errorf("ir -passes: %+v", r)
	}
	if r := dom(t, "asm", "-report", "-regs", "6", fib); r.code != 0 || !strings.Contains(r.out, "fib:") || !strings.Contains(r.err, "callee-saved") {
		t.Errorf("asm: %+v", r)
	}
	if r := dom(t, "check", fib); r.code != 0 || !strings.Contains(r.out, "verified") {
		t.Errorf("check: %+v", r)
	}
	if r := dom(t, "passes"); r.code != 0 || !strings.Contains(r.out, "sccp") || !strings.Contains(r.out, "unroll") {
		t.Errorf("passes: %+v", r)
	}
	if r := dom(t, "bench", "-regs", "8", "../../examples/gcd.dom", "../../examples/sieve.dom"); r.code != 0 || strings.Count(r.out, "x") < 2 || strings.Contains(r.out, "MISCOMPILE") {
		t.Errorf("bench: %+v", r)
	}
	if r := dom(t, "fuzz", "-n", "15", "-seed", "3"); r.code != 0 || !strings.Contains(r.out, "0 FAILED") {
		t.Errorf("fuzz: %+v", r)
	}
	if r := dom(t, "fuzz", "-ir", "-n", "30", "-seed", "3"); r.code != 0 || !strings.Contains(r.out, "0 FAILED") {
		t.Errorf("fuzz -ir: %+v", r)
	}
	if r := dom(t, "fuzz", "-show", "-seed", "5"); r.code != 0 || !strings.Contains(r.out, "fn main()") {
		t.Errorf("fuzz -show: %+v", r)
	}
	out := filepath.Join(t.TempDir(), "r.html")
	if r := dom(t, "report", "-O3", "-o", out, "../../examples/gcd.dom"); r.code != 0 || !strings.Contains(r.out, "wrote") {
		t.Errorf("report: %+v", r)
	}
	if b, err := os.ReadFile(out); err != nil || !strings.Contains(string(b), "const D = ") {
		t.Errorf("report file: %v", err)
	}
	if r := dom(t, "help"); r.code != 0 || !strings.Contains(r.out, "usage:") {
		t.Errorf("help: %+v", r)
	}
}

func TestExitCodesAndDiagnostics(t *testing.T) {
	cases := []struct {
		name string
		args []string
		code int
		want string // substring of stderr+stdout
	}{
		{"no args", nil, 2, "usage:"},
		{"unknown command", []string{"frob"}, 2, "unknown command"},
		{"missing file", []string{"run", "/no/such/file.dom"}, 1, "no such file"},
		{"no file", []string{"run"}, 1, "exactly one input file"},
		{"bad level", []string{"run", "-O", "9", "../../examples/fib.dom"}, 1, "level must be 0-3"},
		{"bad regs", []string{"run", "-regs", "2", "../../examples/fib.dom"}, 1, "register count"},
		{"bad pass", []string{"ir", "-passes", "zzz", "../../examples/fib.dom"}, 1, "unknown pass"},
	}
	for _, c := range cases {
		r := dom(t, c.args...)
		if r.code != c.code || !strings.Contains(r.out+r.err, c.want) {
			t.Errorf("%s: %+v, want rc=%d containing %q", c.name, r, c.code, c.want)
		}
	}
	syn := write(t, "bad.dom", "fn main() {\n    var x = 1 +;\n}\n")
	if r := dom(t, "run", syn); r.code != 1 || !strings.Contains(r.err, "2:") || !strings.Contains(r.err, "var x = 1 +;") || !strings.Contains(r.err, "^") {
		t.Errorf("source diagnostic should show the line and a caret: %+v", r)
	}
	empty := write(t, "empty.dom", "// nothing here\n")
	if r := dom(t, "run", empty); r.code != 1 || !strings.Contains(r.err, "no functions") {
		t.Errorf("empty program: %+v", r)
	}
	nomain := write(t, "nomain.dom", "fn f() { return 1; }\n")
	if r := dom(t, "run", nomain); r.code != 1 || !strings.Contains(r.err, "@main") {
		t.Errorf("no main: %+v", r)
	}
	trap := write(t, "trap.dom", "fn main() { print(1); var z = 0; return 5 / z; }\n")
	if r := dom(t, "run", trap); r.code != 3 || r.out != "1\n" || !strings.Contains(r.err, "division by zero") {
		t.Errorf("trap: %+v", r)
	}
	spin := write(t, "spin.dom", "fn main() { while 1 { } return 0; }\n")
	if r := dom(t, "run", "-fuel", "100000", spin); r.code != 3 || !strings.Contains(r.err, "fuel exhausted") {
		t.Errorf("fuel: %+v", r)
	}
	badIR := write(t, "bad.ir", "func @main() {\nentry:\n  %x = add 1\n  ret %x\n}\n")
	if r := dom(t, "run", badIR); r.code != 1 || !strings.Contains(r.err, "takes 2 operands") || strings.Contains(r.err, "ir:ir") {
		t.Errorf("ir diagnostic: %+v", r)
	}
	okIR := write(t, "ok.ir", "func @main() {\nentry:\n  print 5\n  ret 7\n}\n")
	if r := dom(t, "run", okIR); r.code != 0 || r.out != "5\n" || !strings.Contains(r.err, "exit value: 7") {
		t.Errorf(".ir input: %+v", r)
	}
}
