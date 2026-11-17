// Command orrery is the command-line front end of the N-body laboratory.
package main

import (
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"strings"
	"time"

	"orrery/orrery"
)

const usage = `orrery — N-body gravity laboratory

usage: orrery <command> [flags] <scenario>

  <scenario> is a built-in name (see 'list') or a path to a scenario file.

commands:
  list                       show built-in scenarios and integrators
  gen      <builtin>         print a built-in scenario in file format (-n, -seed)
  run      <scenario>        integrate and print conserved-quantity diagnostics
  bench    <scenario>        compare all integrators on one problem
  elements <scenario>        orbital elements of every body about body 0
  bh       <scenario>        Barnes–Hut force error and speed vs opening angle
  order    [scenario]        measure each integrator's empirical convergence order
  reverse  <scenario>        time-reversibility test (forward T, then back T)
  lyap     <scenario>        largest Lyapunov exponent (shadow-orbit method)
  report   <scenario>        write a self-contained HTML report (-o file.html)

common flags: -m method  -dt step  -T duration  -theta θ  -n N  -seed S
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	if err := dispatch(os.Args[1], os.Args[2:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "orrery:", err)
		os.Exit(1)
	}
}

type opts struct {
	method   string
	dt, T    float64
	theta    float64
	thetaSet bool
	n        int
	seed     int64
	tol      float64
	out      string
	samples  int
	args     []string
}

func parse(name string, args []string) (*opts, error) {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	o := &opts{}
	fs.StringVar(&o.method, "m", "leapfrog", "integration method")
	fs.Float64Var(&o.dt, "dt", 0.01, "time step")
	fs.Float64Var(&o.T, "T", 10, "duration")
	fs.Float64Var(&o.theta, "theta", -1, "Barnes–Hut opening angle (0 = exact)")
	fs.IntVar(&o.n, "n", 0, "particle count for generators")
	fs.Int64Var(&o.seed, "seed", 1, "random seed")
	fs.Float64Var(&o.tol, "tol", 1e-10, "dopri5 tolerance")
	fs.StringVar(&o.out, "o", "", "output file")
	fs.IntVar(&o.samples, "samples", 10, "diagnostic rows to print")
	// allow flags after positional args
	var pos []string
	for len(args) > 0 {
		if err := fs.Parse(args); err != nil {
			return nil, err
		}
		rest := fs.Args()
		if len(rest) == 0 {
			break
		}
		pos = append(pos, rest[0])
		args = rest[1:]
	}
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "theta" {
			o.thetaSet = true
		}
	})
	o.args = pos
	if !(o.tol > 0) {
		return nil, fmt.Errorf("-tol must be positive, got %v", o.tol)
	}
	if o.samples < 2 {
		return nil, fmt.Errorf("-samples must be at least 2, got %d", o.samples)
	}
	return o, nil
}

func load(o *opts) (*orrery.System, error) {
	if len(o.args) != 1 {
		return nil, fmt.Errorf("expected exactly one scenario argument (built-in name or file), got %d", len(o.args))
	}
	name := o.args[0]
	var s *orrery.System
	if data, err := os.ReadFile(name); err == nil {
		s, err = orrery.ParseScenario(string(data))
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
	} else if strings.ContainsAny(name, "/.") {
		return nil, fmt.Errorf("cannot read scenario file: %v", err)
	} else {
		s, err = orrery.Builtin(name, o.n, o.seed)
		if err != nil {
			return nil, err
		}
	}
	if o.thetaSet {
		s.Theta = o.theta
	}
	return s, nil
}

func dispatch(cmd string, args []string, w io.Writer) error {
	switch cmd {
	case "help", "-h", "--help":
		fmt.Fprint(w, usage)
		return nil
	case "list":
		fmt.Fprintln(w, "built-in scenarios:")
		for _, b := range orrery.Builtins() {
			fmt.Fprintf(w, "  %-12s %s\n", b.Name, b.Desc)
		}
		fmt.Fprintln(w, "\nintegrators:")
		for _, m := range orrery.Methods() {
			sym := "      "
			if m.Symplectic() {
				sym = "symplc"
			}
			fmt.Fprintf(w, "  %-9s order %d  %s\n", m, m.Order(), sym)
		}
		return nil
	}
	o, err := parse(cmd, args)
	if err != nil {
		return err
	}
	switch cmd {
	case "gen":
		s, err := load(o)
		if err != nil {
			return err
		}
		fmt.Fprint(w, orrery.FormatScenario(s))
	case "run":
		return cmdRun(o, w)
	case "bench":
		return cmdBench(o, w)
	case "elements":
		return cmdElements(o, w)
	case "bh":
		return cmdBH(o, w)
	case "order":
		return cmdOrder(o, w)
	case "reverse":
		return cmdReverse(o, w)
	case "lyap":
		return cmdLyap(o, w)
	case "report":
		return cmdReport(o, w)
	default:
		return fmt.Errorf("unknown command %q\n\n%s", cmd, usage)
	}
	return nil
}

func cmdRun(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	m, err := orrery.ParseMethod(o.method)
	if err != nil {
		return err
	}
	res, err := orrery.Run(s, m, o.dt, o.T, o.samples, o.tol)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%s — %d bodies, %s, dt=%g, T=%g\n", titleOf(s), len(s.Bodies), m, res.Dt, o.T)
	fmt.Fprintf(w, "%10s %14s %14s %14s %10s\n", "t", "dE/|E0|", "dL/|L0|", "|dP|", "2K/|U|")
	for k := range res.Times {
		fmt.Fprintf(w, "%10.4f %14.3e %14.3e %14.3e %10.4f\n", res.Times[k], res.EnergyErr[k], res.LErr[k], res.PDrift[k], res.Virial[k])
	}
	fmt.Fprintf(w, "steps=%d force-evals=%d elapsed=%v E0=%.10g\n", res.Steps, res.Evals, res.Elapsed.Round(1e3), res.E0)
	warnIfBad(w, m, res)
	if res.Err != nil {
		return fmt.Errorf("integration stopped early: %w", res.Err)
	}
	return nil
}

// warnIfBad shouts when a run's energy error says the numbers are not trustworthy.
func warnIfBad(w io.Writer, m orrery.Method, res *orrery.Result) {
	if res.Err != nil {
		return
	}
	if e := res.MaxAbsEnergyErr(); e > 0.01 || math.IsNaN(e) {
		hint := "reduce -dt"
		if m != orrery.DOPRI5 {
			hint += " or use -m dopri5 (adaptive steps handle close encounters)"
		}
		fmt.Fprintf(w, "WARNING: max |dE/E0| = %.3g — this trajectory is not physically trustworthy; %s.\n", e, hint)
	}
}

func fmtDur(d time.Duration) string {
	switch {
	case d < time.Microsecond:
		return fmt.Sprintf("%dns", d.Nanoseconds())
	case d < time.Millisecond:
		return fmt.Sprintf("%.1fµs", float64(d)/1e3)
	case d < time.Second:
		return fmt.Sprintf("%.1fms", float64(d)/1e6)
	}
	return fmt.Sprintf("%.2fs", d.Seconds())
}

func titleOf(s *orrery.System) string {
	if s.Title != "" {
		return s.Title
	}
	return "system"
}

func cmdBench(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%s — %d bodies, dt=%g, T=%g\n", titleOf(s), len(s.Bodies), o.dt, o.T)
	fmt.Fprintf(w, "%-10s %-4s %14s %14s %10s %12s\n", "method", "sym", "max|dE/E0|", "max|dL/L0|", "evals", "elapsed")
	for _, m := range orrery.Methods() {
		res, err := orrery.Run(s, m, o.dt, o.T, 200, o.tol)
		if err != nil {
			fmt.Fprintf(w, "%-10s %-4s %s\n", m, "", "n/a: "+err.Error())
			continue
		}
		sym := ""
		if m.Symplectic() {
			sym = "yes"
		}
		status := ""
		if res.Err != nil {
			status = "  FAILED: " + res.Err.Error()
		}
		if status == "" && res.MaxAbsEnergyErr() > 0.01 {
			status = "  WARNING: untrustworthy (energy error > 1%)"
		}
		fmt.Fprintf(w, "%-10s %-4s %14.3e %14.3e %10d %12v%s\n", m, sym, res.MaxAbsEnergyErr(), res.MaxLErr(), res.Evals, res.Elapsed.Round(1e3), status)
	}
	return nil
}

func cmdElements(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	if len(s.Bodies) < 2 {
		return fmt.Errorf("need at least two bodies")
	}
	c := s.Bodies[0]
	fmt.Fprintf(w, "elements about %s (mu = G(M+m)); angles in degrees\n", c.Name)
	fmt.Fprintf(w, "%-10s %10s %8s %8s %9s %9s %9s %9s %10s\n", "body", "a", "e", "i", "raan", "argp", "nu", "M", "period")
	d := 180 / math.Pi
	for _, b := range s.Bodies[1:] {
		el, err := orrery.ElementsFromState(b.Pos.Sub(c.Pos), b.Vel.Sub(c.Vel), s.G*(c.M+b.M))
		if err != nil {
			fmt.Fprintf(w, "%-10s %v\n", b.Name, err)
			continue
		}
		fmt.Fprintf(w, "%-10s %10.5g %8.5f %8.3f %9.3f %9.3f %9.3f %9.3f %10.5g\n", b.Name, el.A, el.E, el.I*d, el.Raan*d, el.Argp*d, el.Nu*d, el.M*d, el.Period)
	}
	return nil
}

func cmdBH(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%s — %d bodies\n%8s %12s %12s %12s %12s %9s\n", titleOf(s), len(s.Bodies), "theta", "rms rel err", "max rel err", "tree", "direct", "speedup")
	for _, th := range []float64{1.2, 1.0, 0.7, 0.5, 0.3, 0.2, 0.1} {
		r, err := orrery.BHError(s, th)
		if err != nil {
			return err
		}
		sp := "n/a"
		if r.Tree > 0 {
			sp = fmt.Sprintf("%.1fx", float64(r.Direct)/float64(r.Tree))
		}
		fmt.Fprintf(w, "%8.2f %12.3e %12.3e %12v %12v %9s\n", th, r.RMSRel, r.MaxRel, fmtDur(r.Tree), fmtDur(r.Direct), sp)
	}
	return nil
}

func cmdReport(o *opts, w io.Writer) error {
	s, err := load(o)
	if err != nil {
		return err
	}
	if o.out == "" {
		return fmt.Errorf("report needs -o <file.html>")
	}
	var ms []orrery.Method
	for _, m := range orrery.Methods() {
		if m == orrery.WisdomHolman && (s.Eps != 0 || len(s.Bodies) > 50) {
			continue
		}
		if m == orrery.Euler && len(s.Bodies) > 50 {
			continue
		}
		ms = append(ms, m)
	}
	view, err := orrery.ParseMethod(o.method)
	if err != nil {
		return err
	}
	found := false
	for _, m := range ms {
		found = found || m == view
	}
	if !found {
		ms = append(ms, view)
	}
	page, err := orrery.BuildReport(s, ms, view, o.dt, o.T, o.tol)
	if err != nil {
		return err
	}
	if err := os.WriteFile(o.out, []byte(page), 0o644); err != nil {
		return err
	}
	fmt.Fprintf(w, "wrote %s (%d KiB)\n", o.out, len(page)/1024)
	return nil
}
