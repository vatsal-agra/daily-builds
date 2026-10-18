// Command mortise is an incremental build system.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"mortise/internal/build"
	"mortise/internal/mf"
)

const usage = `mortise — incremental build system

usage: mortise [flags] [targets...]          build targets (default: the Mortisefile's "default")
       mortise [flags] <command> [args...]

commands:
  build [targets]   build (the default command)
  why <target>      explain exactly why a target would be rebuilt (runs nothing)
  graph [targets]   print the dependency graph as Graphviz DOT
  list              list known targets and rules
  stats             show database/cache size and the last build's critical path
  clean [--all]     delete recorded outputs (--all also deletes .mortise: db + cache)
  watch [targets]   rebuild whenever an input changes

flags:
`

type config struct {
	file      string
	dir       string
	jobs      int
	keepGoing bool
	dryRun    bool
	noCache   bool
	verbose   bool
	quiet     bool
	trace     string
	all       bool
}

var commands = map[string]bool{"build": true, "why": true, "graph": true, "list": true, "stats": true, "clean": true, "watch": true}

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(args []string, stdout, stderr io.Writer) int {
	cmd := "build"
	var c config
	fs := flag.NewFlagSet("mortise", flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.StringVar(&c.file, "f", "Mortisefile", "build file")
	fs.StringVar(&c.dir, "C", ".", "change to `dir` before doing anything")
	fs.IntVar(&c.jobs, "j", 0, "parallel jobs (default: number of CPUs)")
	fs.BoolVar(&c.keepGoing, "k", false, "keep going after failures")
	fs.BoolVar(&c.dryRun, "n", false, "dry run: show what would be rebuilt and why")
	fs.BoolVar(&c.noCache, "no-cache", false, "do not use the action cache")
	fs.BoolVar(&c.verbose, "v", false, "print commands and up-to-date targets")
	fs.BoolVar(&c.quiet, "q", false, "only print errors")
	fs.StringVar(&c.trace, "trace", "", "write a Chrome trace of the build to `file`")
	fs.BoolVar(&c.all, "all", false, "clean: also delete .mortise (database and cache)")
	fs.Usage = func() { fmt.Fprint(stderr, usage); fs.PrintDefaults() }
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			if errors.Is(err, flag.ErrHelp) {
				return 0
			}
			return 2
		}
		if fs.NArg() == 0 {
			break
		}
		pos = append(pos, fs.Arg(0))
		args = fs.Args()[1:]
	}

	// The first positional word may name a command ("mortise -j4 why app");
	// to build a target that shares a command's name, say "mortise build list".
	if len(pos) > 0 && commands[pos[0]] {
		cmd, pos = pos[0], pos[1:]
	}

	root, err := filepath.Abs(c.dir)
	if err != nil {
		fmt.Fprintln(stderr, "mortise:", err)
		return 2
	}
	if st, err := os.Stat(root); err != nil || !st.IsDir() {
		fmt.Fprintf(stderr, "mortise: -C %s: not a directory\n", c.dir)
		return 2
	}
	file := c.file
	if !filepath.IsAbs(file) {
		file = filepath.Join(root, file)
	}
	f, err := mf.ParseFile(file, root)
	if err != nil {
		if os.IsNotExist(err) {
			fmt.Fprintf(stderr, "mortise: %s not found (use -f or -C)\n", c.file)
		} else {
			fmt.Fprintln(stderr, "mortise:", relErr(err, root))
		}
		return 2
	}
	f.Name = filepath.Base(file)

	if cmd == "clean" && c.all {
		return cleanAll(root, stdout, stderr)
	}

	// one mortise per directory
	if cmd != "list" && cmd != "graph" && cmd != "why" && !c.dryRun {
		unlock, err := lock(root)
		if err != nil {
			fmt.Fprintln(stderr, "mortise:", err)
			return 2
		}
		defer unlock()
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	opts := build.Options{Root: root, File: f, Jobs: c.jobs, KeepGoing: c.keepGoing,
		DryRun: c.dryRun || cmd == "why", NoCache: c.noCache, Verbose: c.verbose,
		Stdout: stdout, Stderr: stderr, Ctx: ctx}
	if c.quiet {
		opts.Stdout = io.Discard
	}
	targets := pos
	if len(targets) == 0 && cmd != "why" && cmd != "list" {
		targets = f.Default
	}

	switch cmd {
	case "build":
		return cmdBuild(opts, targets, &c, stdout, stderr)
	case "list":
		return cmdList(opts, stdout, stderr)
	case "clean":
		return cmdClean(opts, stdout, stderr)
	}
	fmt.Fprintf(stderr, "mortise: command %q is not implemented\n", cmd)
	return 2
}

func relErr(err error, root string) string {
	return strings.ReplaceAll(err.Error(), root+string(filepath.Separator), "")
}

func lock(root string) (func(), error) {
	dir := filepath.Join(root, ".mortise")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	lf, err := os.OpenFile(filepath.Join(dir, "lock"), os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(lf.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		lf.Close()
		return nil, errors.New("another mortise is already running in this directory")
	}
	return func() { syscall.Flock(int(lf.Fd()), syscall.LOCK_UN); lf.Close() }, nil
}

func newEngine(opts build.Options, stderr io.Writer) (*build.Engine, error) {
	e, err := build.New(opts)
	if err != nil {
		return nil, err
	}
	for _, w := range e.Warnings {
		fmt.Fprintln(stderr, "mortise: warning:", w)
	}
	return e, nil
}

func cmdBuild(opts build.Options, targets []string, c *config, stdout, stderr io.Writer) int {
	if len(targets) == 0 {
		fmt.Fprintln(stderr, "mortise: no targets given and the Mortisefile has no `default` line")
		return 2
	}
	e, err := newEngine(opts, stderr)
	if err != nil {
		fmt.Fprintln(stderr, "mortise:", err)
		return 2
	}
	sum, err := e.Build(targets)
	closeErr := e.Close()
	if opts.Ctx.Err() != nil {
		fmt.Fprintln(stderr, "mortise: interrupted")
		return 130
	}
	code := 0
	if err != nil {
		code = report(err, e, stderr)
	}
	if closeErr != nil {
		fmt.Fprintln(stderr, "mortise: warning:", closeErr)
	}
	if code == 2 {
		return 2
	}
	if !c.quiet || code != 0 {
		printSummary(stdout, sum, opts.DryRun)
	}
	if opts.DryRun {
		for _, r := range e.Results() {
			if r.Status == build.WouldRun && r.Task.HasCmds() {
				fmt.Fprintf(stdout, "  would build %s\n", r.Task.ID)
				for _, why := range r.Reasons {
					fmt.Fprintf(stdout, "      - %s\n", why)
				}
			}
		}
	}
	if c.trace != "" {
		if err := os.WriteFile(c.trace, e.Trace(), 0o644); err != nil {
			fmt.Fprintln(stderr, "mortise: trace:", err)
		}
	}
	return code
}

// report prints a build error and returns the exit code.
func report(err error, e *build.Engine, stderr io.Writer) int {
	if errors.Is(err, build.ErrBuildFailed) {
		for _, r := range e.Results() {
			if r.Status == build.Failed {
				fmt.Fprintf(stderr, "FAILED: %s: %v\n", r.Task.ID, r.Err)
			}
		}
		return 1
	}
	var nr *build.NoRuleError
	var cy *build.CycleError
	var pe *mf.Error
	switch {
	case errors.As(err, &nr), errors.As(err, &cy), errors.As(err, &pe):
		fmt.Fprintln(stderr, "mortise:", err)
		if errors.As(err, &nr) {
			if s := e.Suggest(nr.Target); s != "" && !nr.IsDir {
				fmt.Fprintf(stderr, "        did you mean %q?\n", s)
			}
		}
		return 2
	}
	fmt.Fprintln(stderr, "mortise:", err)
	return 1
}

func printSummary(w io.Writer, s *build.Summary, dry bool) {
	var parts []string
	add := func(n int, what string) {
		if n > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", n, what))
		}
	}
	add(s.Ran, "ran")
	add(s.Cached, "from cache")
	add(s.WouldRun, "would run")
	add(s.UpToDate, "up to date")
	add(s.Failed, "failed")
	add(s.Skipped, "skipped")
	if len(parts) == 0 {
		parts = append(parts, "nothing to do")
	}
	extra := ""
	if s.Cutoffs+s.SavedByCutoff > 0 {
		extra = fmt.Sprintf(" [early cutoff: %d identical rebuilds, %d downstream skips]", s.Cutoffs, s.SavedByCutoff)
	}
	fmt.Fprintf(w, "mortise: %s%s in %.2fs\n", strings.Join(parts, ", "), extra, s.Wall.Seconds())
}

func cmdList(opts build.Options, stdout, stderr io.Writer) int {
	for _, r := range opts.File.Rules {
		kind := "rule"
		if r.IsPattern() {
			kind = "pattern"
		} else if r.Phony {
			kind = "phony"
		}
		fmt.Fprintf(stdout, "%-8s %s: %s\n", kind, strings.Join(r.Targets, " "), strings.Join(r.Deps, " "))
	}
	if len(opts.File.Default) > 0 {
		fmt.Fprintf(stdout, "default  %s\n", strings.Join(opts.File.Default, " "))
	}
	return 0
}

func cmdClean(opts build.Options, stdout, stderr io.Writer) int {
	e, err := newEngine(opts, stderr)
	if err != nil {
		fmt.Fprintln(stderr, "mortise:", err)
		return 2
	}
	n, err := e.Clean()
	if err != nil {
		fmt.Fprintln(stderr, "mortise:", err)
		return 1
	}
	fmt.Fprintf(stdout, "mortise: removed %d output file(s)\n", n)
	return 0
}

func cleanAll(root string, stdout, stderr io.Writer) int {
	// Recorded outputs come from the database, so no Mortisefile is needed.
	e, err := build.New(build.Options{Root: root, File: &mf.File{Vars: map[string]string{}}})
	if err == nil {
		n, _ := e.Clean()
		fmt.Fprintf(stdout, "mortise: removed %d output file(s)\n", n)
	}
	if err := os.RemoveAll(filepath.Join(root, ".mortise")); err != nil {
		fmt.Fprintln(stderr, "mortise:", err)
		return 1
	}
	fmt.Fprintln(stdout, "mortise: removed .mortise")
	return 0
}
