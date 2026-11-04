package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"gosper/life"
)

const usage = `gosper — a Hashlife cellular-automaton laboratory

usage: gosper <command> [flags] [pattern]

  patterns                     list built-in patterns
  info     <pattern>           parse a pattern and print its facts
  run      <pattern> -gens N   jump N generations (Hashlife) and report; -o writes RLE/MC/cells
  analyze  <pattern>           period, spaceship speed, settling, growth class
  verify                       differential test: Hashlife vs naive simulator on random soups
  census                       random-soup ash census (named still lifes / oscillators / ships)
  render   <pattern> -gens N   PNG snapshot (zoomable, density shading)
  report   <pattern>           self-contained HTML report

<pattern> is a built-in name, or a path to .rle / .cells / .mc (or "-" for stdin).
Rule defaults to the file's rule, else B3/S23; override with -rule B36/S23.
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	var err error
	switch cmd {
	case "patterns":
		err = cmdPatterns()
	case "info":
		err = cmdInfo(args)
	case "run":
		err = cmdRun(args)
	case "analyze":
		err = cmdAnalyze(args)
	case "verify":
		err = cmdVerify(args)
	case "help", "-h", "--help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "gosper: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
	if errors.Is(err, flag.ErrHelp) {
		return
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "gosper:", err)
		os.Exit(1)
	}
}

// loaded is a pattern resolved to cells and a rule. If mc is set, the pattern
// came from a Macrocell file and sim is the ready-made universe.
type loaded struct {
	name  string
	rule  life.Rule
	cells []life.Point
	sim   *life.Sim
}

func loadPattern(arg, ruleOverride string) (*loaded, error) {
	if arg == "" {
		return nil, fmt.Errorf("missing pattern argument")
	}
	var override *life.Rule
	if ruleOverride != "" {
		r, err := life.ParseRule(ruleOverride)
		if err != nil {
			return nil, err
		}
		override = &r
	}
	if p, ok := life.LookupPattern(arg); ok {
		l := &loaded{name: p.Name, rule: p.Rule, cells: p.Cells}
		if override != nil {
			l.rule = *override
		}
		return l, nil
	}
	var data []byte
	var err error
	if arg == "-" {
		data, err = io.ReadAll(io.LimitReader(os.Stdin, 1<<28))
	} else {
		data, err = os.ReadFile(arg)
	}
	if err != nil {
		return nil, fmt.Errorf("%q is neither a built-in pattern nor a readable file: %v", arg, err)
	}
	text := string(data)
	if strings.HasPrefix(strings.TrimSpace(text), "[M2]") {
		def := life.Life
		if override != nil {
			def = *override
		}
		sim, err := life.LoadMacrocell(text, def)
		if err != nil {
			return nil, err
		}
		l := &loaded{name: arg, rule: sim.U.Rule, sim: sim}
		if override != nil && *override != sim.U.Rule {
			return nil, fmt.Errorf("-rule cannot override the rule stored in a macrocell file")
		}
		return l, nil
	}
	p, err := life.ParsePattern(text)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", arg, err)
	}
	l := &loaded{name: p.Name, rule: life.Life, cells: p.Cells}
	if l.name == "" {
		l.name = arg
		if arg == "-" {
			l.name = "stdin"
		}
	}
	if p.HasRule {
		l.rule = p.Rule
	}
	if override != nil {
		l.rule = *override
	}
	return l, nil
}

func (l *loaded) newSim() *life.Sim {
	if l.sim != nil {
		return l.sim
	}
	s := life.NewSim(l.rule)
	if err := s.SetCells(append([]life.Point(nil), l.cells...), true); err != nil {
		fmt.Fprintln(os.Stderr, "gosper:", err)
		os.Exit(1)
	}
	return s
}

// cellsOf returns the live cells (erroring if there are too many to list).
func (l *loaded) cellsOf() ([]life.Point, error) {
	if l.sim == nil {
		return l.cells, nil
	}
	pts, ok := l.sim.Cells(life.MaxListCells)
	if !ok {
		return nil, fmt.Errorf("pattern has %d cells; too many to enumerate for this command", l.sim.Population())
	}
	return pts, nil
}

// parseGens accepts 1000, 2^40, 1e9, 1_000_000.
func parseGens(s string) (uint64, error) {
	s = strings.ReplaceAll(strings.TrimSpace(s), "_", "")
	if strings.HasPrefix(s, "2^") {
		e, err := strconv.Atoi(s[2:])
		if err != nil || e < 0 || e > 56 {
			return 0, fmt.Errorf("bad generation count %q (2^0..2^56)", s)
		}
		return 1 << uint(e), nil
	}
	if n, err := strconv.ParseUint(s, 10, 64); err == nil {
		if n > 1<<56 {
			return 0, fmt.Errorf("generation count %s exceeds 2^56", s)
		}
		return n, nil
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil || f < 0 || f > float64(uint64(1)<<56) || f != float64(uint64(f)) {
		return 0, fmt.Errorf("bad generation count %q", s)
	}
	return uint64(f), nil
}

func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

// splitArgs lets flags appear before or after the positional pattern.
func splitArgs(fs *flag.FlagSet, args []string) (string, error) {
	var pos []string
	for len(args) > 0 {
		if err := fs.Parse(args); err != nil {
			return "", err
		}
		args = fs.Args()
		if len(args) > 0 {
			pos = append(pos, args[0])
			args = args[1:]
		}
	}
	if len(pos) > 1 {
		return "", fmt.Errorf("expected one pattern, got %d: %v", len(pos), pos)
	}
	if len(pos) == 0 {
		return "", nil
	}
	return pos[0], nil
}

func cmdPatterns() error {
	for _, p := range life.Library() {
		fmt.Printf("%-20s %-10s %s\n", p.Name, p.Rule, p.Note)
	}
	return nil
}

func human(n uint64) string {
	s := strconv.FormatUint(n, 10)
	var out []byte
	for i, c := range []byte(s) {
		if i > 0 && (len(s)-i)%3 == 0 {
			out = append(out, ',')
		}
		out = append(out, c)
	}
	return string(out)
}

func since(t time.Time) string { return time.Since(t).Round(time.Millisecond).String() }
