package lang

import (
	"strings"
	"testing"

	"milner/internal/syntax"
)

// Regression tests: one per issue found in the adversarial review (see REVIEW.md).

func TestReviewR01AnnotationVarsAreNotReusedAfterGeneralisation(t *testing.T) {
	// used to panic: "internal error: unifying generic variable"
	got := typeOf(t, `let f x = let g (y : 'a) = y in (fun (z : 'a) -> z) 1;; f`)
	if got != "'a -> int" {
		t.Errorf("got %s", got)
	}
}

func TestReviewR02CyclicValuesDoNotCrash(t *testing.T) {
	src := `type t = N of t ref | Nil
let a = ref Nil
let () = a := N a
let shown = a`
	s, _ := newSession(t)
	outs, err := s.Run(src, true) // printing a cyclic value used to overflow the Go stack (fatal)
	if err != nil {
		t.Fatal(err)
	}
	if f := outs[len(outs)-1].Format(); !strings.Contains(f, "...") || len(f) > 5000 {
		t.Errorf("cyclic value not truncated: %d bytes", len(f))
	}
	_, err = s.Run(`let c = (a = a)`, true) // comparing used to recurse forever
	if err == nil || !strings.Contains(err.Error(), "compare") {
		t.Errorf("expected a compare error, got %v", err)
	}
}

func TestReviewR03LongListsCompareWithoutDeepRecursion(t *testing.T) {
	if got := value(t, `let xs = range 0 300000 in xs = xs @ []`); got != "true" {
		t.Errorf("got %s", got)
	}
	if got := value(t, `compare (range 0 100000) (range 0 100001)`); got != "-1" {
		t.Errorf("got %s", got)
	}
}

func TestReviewR04DeepRecursionIsBoundedNotFatal(t *testing.T) {
	// a 120k-deep non-tail recursion works; an unbounded one fails with a normal error
	if got := value(t, `let rec build n = if n = 0 then [] else n :: build (n - 1);; length (build 120000)`); got != "120000" {
		t.Errorf("got %s", got)
	}
	msg := runtimeErr(t, `let rec f n = 1 + f n;; f 0`)
	if !strings.Contains(msg, "stack overflow") {
		t.Errorf("got %q", msg)
	}
}

func TestReviewR05OperandNoteOnlyForDirectArguments(t *testing.T) {
	s, _ := newSession(t)
	_, err := s.Run(`let f = ref (fun x -> x + 1);; !f "a"`, false)
	d, ok := err.(*syntax.Diag)
	if !ok {
		t.Fatalf("expected a type error, got %v", err)
	}
	for _, n := range d.Notes {
		if strings.Contains(n, "operand 2 of `!`") {
			t.Errorf("misleading note: %s", n)
		}
	}
}

func TestReviewR06HoleOnUnconstrainedTypeIsNotNoisy(t *testing.T) {
	s, _ := newSession(t)
	_, err := s.Run(`let f x = _`, false)
	d, _ := err.(*syntax.Diag)
	if d == nil || len(d.Notes) != 1 || strings.Contains(d.Notes[0], "could fit") {
		t.Errorf("got %v", err)
	}
}

func TestReviewR07StarParenNote(t *testing.T) {
	_, d := syntax.Lex("let (*) a b = a")
	if d == nil || len(d.Notes) == 0 || !strings.Contains(d.Notes[0], "( * )") {
		t.Errorf("got %v", d)
	}
}

func TestReviewR08DiagnosticSpanEndingAtLineStart(t *testing.T) {
	src := "let x = \"unterminated\n"
	_, d := syntax.Lex(src)
	if d == nil {
		t.Fatal("expected error")
	}
	out := d.Render(src, "f")
	if strings.Count(out, "\n") > 6 {
		t.Errorf("render shows a phantom empty line:\n%s", out)
	}
}

func TestReviewR09BoundaryDescription(t *testing.T) {
	_, d := syntax.ParseProgram("let x = (1, 2\nlet y = 3")
	if d == nil || !strings.Contains(d.Msg, "start of a new declaration") {
		t.Errorf("got %v", d)
	}
}

func TestReviewR10LetInResultIsNotNeedlesslyWeak(t *testing.T) {
	if got := typeOf(t, `let x = fun y -> y in x`); got != "'a -> 'a" {
		t.Errorf("got %s", got)
	}
}
