package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func runCLI(t *testing.T, stdin string, args ...string) (int, string, string) {
	t.Helper()
	var out, errb bytes.Buffer
	code := run(args, strings.NewReader(stdin), &out, &errb)
	return code, out.String(), errb.String()
}

func TestCLIRun(t *testing.T) {
	code, out, _ := runCLI(t, `print_endline "hello"; print_int (fold_left (+) 0 [1;2;3])`, "run", "-")
	if code != 0 || out != "hello\n6" {
		t.Errorf("code=%d out=%q", code, out)
	}
}

func TestCLIRunVerbose(t *testing.T) {
	code, out, _ := runCLI(t, "let double x = x * 2\ndouble 21;;", "run", "-v", "-")
	if code != 0 || !strings.Contains(out, "val double : int -> int = <fun>") || !strings.Contains(out, "- : int = 42") {
		t.Errorf("code=%d out=%q", code, out)
	}
}

func TestCLICheck(t *testing.T) {
	code, out, _ := runCLI(t, "let id x = x\nlet n = id 3", "check", "-")
	if code != 0 || !strings.Contains(out, "val id : 'a -> 'a\n") || !strings.Contains(out, "val n : int\n") {
		t.Errorf("code=%d out=%q", code, out)
	}
	if strings.Contains(out, "=") && strings.Contains(out, "<fun>") {
		t.Errorf("check must not evaluate: %q", out)
	}
}

func TestCLITypeError(t *testing.T) {
	code, _, errs := runCLI(t, `let x = 1 + "a"`, "run", "-")
	if code != 1 || !strings.Contains(errs, "error[type]") || !strings.Contains(errs, "^^^") {
		t.Errorf("code=%d err=%q", code, errs)
	}
}

func TestCLIWarningDoesNotFail(t *testing.T) {
	code, out, errs := runCLI(t, "type t = A | B\nlet f x = match x with A -> 1\nlet () = print_int (f A)", "run", "-")
	if code != 0 || out != "1" || !strings.Contains(errs, "warning[pattern]") || !strings.Contains(errs, "`B`") {
		t.Errorf("code=%d out=%q err=%q", code, out, errs)
	}
}

func TestCLIRuntimeError(t *testing.T) {
	code, out, errs := runCLI(t, `print_endline "before"; print_int (1 / 0)`, "run", "-")
	if code != 1 || out != "before\n" || !strings.Contains(errs, "Division_by_zero") {
		t.Errorf("code=%d out=%q err=%q", code, out, errs)
	}
}

func TestCLIType(t *testing.T) {
	code, out, _ := runCLI(t, "", "type", "fun f g x -> f (g x)")
	if code != 0 || strings.TrimSpace(out) != "('a -> 'b) -> ('c -> 'a) -> 'c -> 'b" {
		t.Errorf("code=%d out=%q", code, out)
	}
	code, _, errs := runCLI(t, "", "type", "1 + true")
	if code != 1 || !strings.Contains(errs, "mismatched") {
		t.Errorf("code=%d err=%q", code, errs)
	}
}

func TestCLIRepl(t *testing.T) {
	in := "let x = 20;;\nx + 1;;\ntype t = A | B;;\nlet f = function A -> 1;;\nx + \"a\";;\nf B;;\n"
	code, out, _ := runCLI(t, in, "repl")
	for _, want := range []string{"val x : int = 20", "- : int = 21", "type t = A | B", "val f : t -> int = <fun>", "warning[pattern]", "error[type]", "Match_failure"} {
		if !strings.Contains(out, want) {
			t.Errorf("repl output lacks %q:\n%s", want, out)
		}
	}
	if code != 0 {
		t.Errorf("code %d", code)
	}
}

func TestCLIUsage(t *testing.T) {
	if code, _, errs := runCLI(t, ""); code != 2 || !strings.Contains(errs, "usage") {
		t.Errorf("code=%d err=%q", code, errs)
	}
	if code, _, _ := runCLI(t, "", "bogus"); code != 2 {
		t.Errorf("code=%d", code)
	}
	if code, _, _ := runCLI(t, "", "run", "/nonexistent/file.ml"); code != 2 {
		t.Errorf("code=%d", code)
	}
}

func TestCLIDenyWarnings(t *testing.T) {
	src := "type t = A | B\nlet f x = match x with A -> 1\n"
	if code, _, _ := runCLI(t, src, "check", "-"); code != 0 {
		t.Errorf("warnings alone must not fail: %d", code)
	}
	code, _, errs := runCLI(t, src, "check", "--deny-warnings", "-")
	if code != 1 || !strings.Contains(errs, "treated as errors") {
		t.Errorf("code=%d err=%q", code, errs)
	}
}

func TestCLIBOMAndCRLF(t *testing.T) {
	src := "\ufefflet x = 1\r\nlet y = x + 1\r\nlet () = print_int y\r\n"
	code, out, errs := runCLI(t, src, "run", "-")
	if code != 0 || out != "2" {
		t.Errorf("code=%d out=%q err=%q", code, out, errs)
	}
}

func TestCLIReplSemicolonsInStringsAndComments(t *testing.T) {
	in := "let s = \"a;;b\";;\n(* ;; *) let t = 1;;\nlet u = \"multi\nline\";;\ns;;\n"
	_, out, _ := runCLI(t, in, "repl")
	for _, want := range []string{`val s : string = "a;;b"`, "val t : int = 1", `val u : string = "multi\nline"`} {
		if !strings.Contains(out, want) {
			t.Errorf("repl output lacks %q:\n%s", want, out)
		}
	}
}

// Every program in examples/ runs warning-free and prints exactly its golden .out file.
func TestExamplesGolden(t *testing.T) {
	files, err := filepath.Glob("../../examples/*.ml")
	if err != nil || len(files) < 8 {
		t.Fatalf("expected the example gallery, found %d files (%v)", len(files), err)
	}
	for _, f := range files {
		want, err := os.ReadFile(strings.TrimSuffix(f, ".ml") + ".out")
		if err != nil {
			t.Errorf("%s: missing golden file: %v", f, err)
			continue
		}
		code, out, errs := runCLI(t, "", "run", "--deny-warnings", f)
		if code != 0 {
			t.Errorf("%s: exit %d\n%s", f, code, errs)
			continue
		}
		if out != string(want) {
			t.Errorf("%s: output differs from golden file\n--- got\n%s\n--- want\n%s", f, out, want)
		}
	}
}

func TestCLIReplCommands(t *testing.T) {
	in := ":env\nlet sq x = x * x;;\n:env\n:type map sq\n:explain sq 3\n:type 1 +\n:bogus\n:help\n:quit\nlet unreachable = 1;;\n"
	code, out, _ := runCLI(t, in, "repl")
	for _, want := range []string{"(nothing defined yet)", "val sq : int -> int", "int list -> int list", "unify", "error[syntax]", "unknown command :bogus", ":explain EXPR"} {
		if !strings.Contains(out, want) {
			t.Errorf("repl output lacks %q:\n%s", want, out)
		}
	}
	if strings.Contains(out, "unreachable") || code != 0 {
		t.Errorf(":quit must stop the session (code %d):\n%s", code, out)
	}
}

func TestCLIExplain(t *testing.T) {
	code, out, _ := runCLI(t, "", "explain", "fun x -> x")
	if code != 0 || !strings.Contains(out, "result: 'a -> 'a") {
		t.Errorf("code=%d out=%q", code, out)
	}
	code, out, errs := runCLI(t, "", "explain", "1 + true")
	if code != 1 || !strings.Contains(out, "✗ fails") || !strings.Contains(errs, "error[type]") {
		t.Errorf("code=%d out=%q err=%q", code, out, errs)
	}
	code, _, _ = runCLI(t, "let id x = x\nlet n = id 1", "explain", "-f", "-")
	if code != 0 {
		t.Errorf("explain -f - failed: %d", code)
	}
}

func TestCLIEmptyAndInvalidInput(t *testing.T) {
	for _, src := range []string{"", "   \n", "(* just a comment *)", ";;"} {
		if code, out, errs := runCLI(t, src, "run", "-"); code != 0 || out != "" || errs != "" {
			t.Errorf("%q: code=%d out=%q err=%q", src, code, out, errs)
		}
	}
	if code, _, errs := runCLI(t, "", "type", ""); code != 1 || !strings.Contains(errs, "expected an expression") {
		t.Errorf("code=%d err=%q", code, errs)
	}
	if code, _, errs := runCLI(t, "\x00\x01", "run", "-"); code != 1 || !strings.Contains(errs, "unexpected character") {
		t.Errorf("code=%d err=%q", code, errs)
	}
}
