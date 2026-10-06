package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"runtime/debug"
	"strings"

	"milner/internal/lang"
	"milner/internal/syntax"
)

const usage = `milner — an ML-family language with Hindley–Milner type inference

usage:
  milner run   [-v] [--fuel N] [--deny-warnings] FILE|-
                                        type-check, then run a program (-v prints each binding;
                                        --fuel limits evaluation steps; warnings can fail the run)
  milner check [--deny-warnings] FILE|- type-check and pattern-check only; print inferred types
  milner type  'EXPR'                   print the type of an expression
  milner repl                           interactive session (end inputs with ;;)
`

func main() {
	// The evaluator allocates many small short-lived objects; trade memory for fewer GC cycles.
	debug.SetGCPercent(800)
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

func readSource(name string, stdin io.Reader) (string, string, error) {
	if name == "-" {
		b, err := io.ReadAll(stdin)
		return strings.TrimPrefix(string(b), "\ufeff"), "<stdin>", err
	}
	b, err := os.ReadFile(name)
	return strings.TrimPrefix(string(b), "\ufeff"), name, err
}

func report(w io.Writer, err error, src, file string) {
	if d, ok := err.(*syntax.Diag); ok {
		fmt.Fprint(w, d.Render(src, file))
		return
	}
	fmt.Fprintln(w, "error:", err)
}

func run(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprint(stderr, usage)
		return 2
	}
	switch args[0] {
	case "run", "check":
		verbose, deny := false, false
		var fuel int64
		var file string
		rest := args[1:]
		for i := 0; i < len(rest); i++ {
			switch {
			case rest[i] == "-v":
				verbose = true
			case rest[i] == "--deny-warnings":
				deny = true
			case rest[i] == "--fuel" && i+1 < len(rest):
				fmt.Sscan(rest[i+1], &fuel)
				i++
			case file == "":
				file = rest[i]
			default:
				fmt.Fprint(stderr, usage)
				return 2
			}
		}
		if file == "" {
			fmt.Fprint(stderr, usage)
			return 2
		}
		src, name, err := readSource(file, stdin)
		if err != nil {
			fmt.Fprintln(stderr, "error:", err)
			return 2
		}
		return runFile(args[0] == "run", verbose, deny, fuel, src, name, stdout, stderr)
	case "type":
		if len(args) != 2 {
			fmt.Fprint(stderr, usage)
			return 2
		}
		s, err := lang.NewSession(io.Discard)
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 3
		}
		t, err := s.TypeOf(args[1])
		if err != nil {
			report(stderr, err, args[1], "<expr>")
			return 1
		}
		fmt.Fprintln(stdout, t)
		return 0
	case "repl":
		return repl(stdin, stdout, stderr)
	case "-h", "--help", "help":
		fmt.Fprint(stdout, usage)
		return 0
	}
	fmt.Fprintf(stderr, "unknown command %q\n\n%s", args[0], usage)
	return 2
}

func runFile(evaluate, verbose, deny bool, fuel int64, src, name string, stdout, stderr io.Writer) int {
	bw := bufio.NewWriter(stdout)
	defer bw.Flush()
	s, err := lang.NewSession(bw)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 3
	}
	s.Interp.M.MaxSteps = fuel
	decls, d := syntax.ParseProgram(src)
	if d != nil {
		bw.Flush()
		report(stderr, d, src, name)
		return 1
	}
	warned := 0
	for _, decl := range decls {
		o, err := s.Step(decl, evaluate)
		if o != nil {
			for _, w := range o.Warnings {
				bw.Flush()
				fmt.Fprint(stderr, w.Render(src, name))
				warned++
			}
		}
		if err != nil {
			bw.Flush()
			report(stderr, err, src, name)
			return 1
		}
		if verbose || !evaluate {
			if _, bare := decl.(*syntax.DExpr); !bare || verbose {
				fmt.Fprint(bw, o.Format())
			}
		}
	}
	if warned > 0 && deny {
		bw.Flush()
		fmt.Fprintf(stderr, "%d warning(s) treated as errors (--deny-warnings)\n", warned)
		return 1
	}
	return 0
}

func repl(stdin io.Reader, stdout, stderr io.Writer) int {
	s, err := lang.NewSession(stdout)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 3
	}
	fmt.Fprintln(stdout, "Milner — end each input with ;;   (Ctrl-D to quit)")
	sc := bufio.NewScanner(stdin)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	var buf strings.Builder
	prompt := func() {
		if buf.Len() == 0 {
			fmt.Fprint(stdout, "# ")
		} else {
			fmt.Fprint(stdout, "  ")
		}
	}
	prompt()
	for sc.Scan() {
		buf.WriteString(sc.Text() + "\n")
		if replComplete(buf.String()) {
			src := buf.String()
			buf.Reset()
			evalREPL(s, src, stdout)
		}
		prompt()
	}
	if strings.TrimSpace(buf.String()) != "" {
		fmt.Fprintln(stdout)
		evalREPL(s, buf.String(), stdout) // report whatever was left unterminated
	}
	fmt.Fprintln(stdout)
	return 0
}

// replComplete reports whether the buffer holds a `;;` token (a `;;` inside a string or comment does
// not count, and an unterminated string/comment keeps the REPL reading).
func replComplete(src string) bool {
	toks, d := syntax.Lex(src)
	if d != nil {
		return !strings.Contains(d.Msg, "unterminated") // genuine lex errors are reported right away
	}
	for _, t := range toks {
		if t.Kind == syntax.SYM && t.Text == ";;" {
			return true
		}
	}
	return false
}

func evalREPL(s *lang.Session, src string, out io.Writer) {
	decls, d := syntax.ParseProgram(src)
	if d != nil {
		fmt.Fprint(out, d.Render(src, "<repl>"))
		return
	}
	for _, decl := range decls {
		o, err := s.Step(decl, true)
		if o != nil {
			for _, w := range o.Warnings {
				fmt.Fprint(out, w.Render(src, "<repl>"))
			}
		}
		if err != nil {
			report(out, err, src, "<repl>")
			return
		}
		fmt.Fprint(out, o.Format())
	}
}
