package main

import (
	"flag"
	"fmt"
	"io"
	"math/big"
	"os"
	"strings"
	"time"

	"dantzig/internal/bb"
	"dantzig/internal/exact"
	"dantzig/internal/model"
)

func loadModel(path string) (*model.Model, error) {
	var b []byte
	var err error
	if path == "-" {
		b, err = io.ReadAll(os.Stdin)
	} else {
		b, err = os.ReadFile(path)
	}
	if err != nil {
		return nil, err
	}
	m, err := model.Parse(string(b))
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return m, nil
}

type solveFlags struct {
	proof, branch, values string
	noProof, noDive       bool
	timeLimit             float64
	nodes                 int
	log, quiet            bool
}

func parseSolveFlags(name string, args []string) (*solveFlags, []string, error) {
	f := &solveFlags{}
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.Usage = func() {}
	fs.StringVar(&f.proof, "proof", "", "")
	fs.StringVar(&f.branch, "branch", "pseudo", "")
	fs.StringVar(&f.values, "values", "nonzero", "")
	fs.BoolVar(&f.noProof, "no-proof", false, "")
	fs.BoolVar(&f.noDive, "no-dive", false, "")
	fs.Float64Var(&f.timeLimit, "time", 0, "")
	fs.IntVar(&f.nodes, "nodes", 0, "")
	fs.BoolVar(&f.log, "log", false, "")
	fs.BoolVar(&f.quiet, "quiet", false, "")
	// allow flags after the positional model path
	var pos, rest []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if strings.HasPrefix(a, "-") && a != "-" {
			rest = append(rest, a)
			name := strings.TrimLeft(a, "-")
			if !strings.Contains(name, "=") {
				switch name {
				case "proof", "branch", "values", "time", "nodes":
					if i+1 < len(args) {
						i++
						rest = append(rest, args[i])
					}
				}
			}
		} else {
			pos = append(pos, a)
		}
	}
	if err := fs.Parse(rest); err != nil {
		return nil, nil, fmt.Errorf("%v (run `dantzig help` for the flag list)", err)
	}
	if f.branch != "pseudo" && f.branch != "mostfrac" {
		return nil, nil, fmt.Errorf("--branch must be pseudo or mostfrac")
	}
	if f.values != "nonzero" && f.values != "all" {
		return nil, nil, fmt.Errorf("--values must be nonzero or all")
	}
	if f.proof != "" && f.noProof {
		return nil, nil, fmt.Errorf("--proof and --no-proof contradict each other")
	}
	if f.timeLimit < 0 || f.nodes < 0 {
		return nil, nil, fmt.Errorf("limits must be non-negative")
	}
	return f, pos, nil
}

func cmdSolve(args []string) (int, error) {
	f, pos, err := parseSolveFlags("solve", args)
	if err != nil {
		return 2, err
	}
	if len(pos) != 1 {
		return 2, fmt.Errorf("solve needs exactly one model file")
	}
	m, err := loadModel(pos[0])
	if err != nil {
		return 2, err
	}
	res := runSolve(m, f)
	printResult(os.Stdout, m, res, f)
	if f.proof != "" && res.Proof != nil && !f.noProof {
		b, err := bb.MarshalProof(res.Proof)
		if err != nil {
			return 1, err
		}
		if err := os.WriteFile(f.proof, b, 0o644); err != nil {
			return 1, err
		}
		fmt.Printf("proof written to %s (%d bytes)\n", f.proof, len(b))
	}
	switch res.Status {
	case bb.Optimal:
		return 0, nil
	case bb.Infeasible, bb.Unbounded, bb.UnboundedRelaxation:
		return 10, nil
	}
	return 20, nil
}

func runSolve(m *model.Model, f *solveFlags) *bb.Result {
	opt := bb.Options{
		TimeLimit: time.Duration(f.timeLimit * float64(time.Second)),
		NodeLimit: f.nodes, Branch: f.branch, NoProof: f.noProof, NoDive: f.noDive,
	}
	if f.log {
		opt.Log = os.Stderr
	}
	return bb.Solve(m, opt)
}

func objStr(m *model.Model, r *big.Rat) string {
	if r.IsInt() && len(r.Num().String()) <= 30 {
		return r.Num().String()
	}
	if rs := r.RatString(); len(rs) > 48 {
		return fmt.Sprintf("≈ %s  (exact %d-digit fraction omitted)", model.DecStr(r), len(rs))
	}
	return fmt.Sprintf("%s  (≈ %s)", r.RatString(), model.DecStr(r))
}

func printResult(w io.Writer, m *model.Model, res *bb.Result, f *solveFlags) {
	nint := 0
	for _, v := range m.Vars {
		if v.Int {
			nint++
		}
	}
	kind := "LP"
	if nint > 0 {
		kind = "MIP"
	}
	if !f.quiet {
		fmt.Fprintf(w, "model: %s with %d variables (%d integer), %d constraints\n", kind, len(m.Vars), nint, len(m.Rows))
	}
	st := strings.ToUpper(string(res.Status))
	cert := ""
	switch {
	case f.noProof:
		cert = " (uncertified: --no-proof)"
	case res.Certified:
		cert = " (exact certificate verified)"
	case res.Status == bb.Limit || res.Status == bb.Unknown:
		cert = ""
	default:
		cert = " (NOT certified)"
	}
	fmt.Fprintf(w, "status: %s%s\n", st, cert)
	if res.Note != "" {
		fmt.Fprintf(w, "note: %s\n", res.Note)
	}
	if res.Status == bb.UnboundedRelaxation && res.Note == "" {
		fmt.Fprintln(w, "note: the LP relaxation is unbounded, so the MIP is either unbounded or infeasible")
	}
	if res.Obj != nil {
		sense := "min"
		if m.Maximize {
			sense = "max"
		}
		fmt.Fprintf(w, "objective (%s): %s\n", sense, objStr(m, res.Obj))
	}
	if res.Bound != nil && res.Status == bb.Limit {
		fmt.Fprintf(w, "proven bound: %s\n", objStr(m, res.Bound))
	}
	if f.quiet {
		return
	}
	if res.X != nil {
		if res.Status == bb.Unbounded {
			fmt.Fprintln(w, "a feasible point (the objective improves without limit along the certified ray):")
		}
		type kv struct {
			name string
			v    *big.Rat
		}
		var rows []kv
		for j, v := range m.Vars {
			if res.X[j].Sign() != 0 || f.values == "all" {
				rows = append(rows, kv{v.Name, res.X[j]})
			}
		}
		for _, r := range rows {
			fmt.Fprintf(w, "  %-14s = %s\n", r.name, objStr(m, r.v))
		}
		if len(rows) == 0 {
			fmt.Fprintln(w, "  (all variables are zero)")
		}
		if err := exact.CheckPoint(m, exact.BoxOf(m), res.X, true); err != nil {
			fmt.Fprintf(w, "WARNING: reported solution fails exact verification: %v\n", err)
		}
	}
	if kind == "MIP" || f.log {
		root := ""
		if res.RootLP != nil {
			root = fmt.Sprintf(", root LP %.6g", *res.RootLP)
		}
		fmt.Fprintf(w, "search: %d nodes, %d simplex iterations%s, %d from diving, %.2fs\n",
			res.Nodes, res.LPIters, root, res.DiveFound, res.Elapsed.Seconds())
	} else {
		fmt.Fprintf(w, "search: %d simplex iterations, %.3fs\n", res.LPIters, res.Elapsed.Seconds())
	}
	if res.Uncertified > 0 {
		fmt.Fprintf(w, "WARNING: %d leaves could not be certified exactly\n", res.Uncertified)
	}
}

func cmdCheck(args []string) (int, error) {
	if len(args) != 2 {
		return 2, fmt.Errorf("usage: dantzig check <model.lp> <proof.json>")
	}
	m, err := loadModel(args[0])
	if err != nil {
		return 2, err
	}
	raw, err := os.ReadFile(args[1])
	if err != nil {
		return 2, err
	}
	p, err := bb.UnmarshalProof(raw)
	if err != nil {
		return 2, fmt.Errorf("%s: %w", args[1], err)
	}
	rep, err := bb.Check(m, p)
	if err != nil {
		fmt.Printf("REJECTED: %v\n", err)
		return 3, nil
	}
	fmt.Printf("VERIFIED: status %s (checked with exact rational arithmetic)\n", rep.Status)
	if rep.Objective != nil {
		fmt.Printf("  objective %s\n", objStr(m, rep.Objective))
	}
	if rep.Leaves > 0 {
		fmt.Printf("  proof tree: %d nodes, %d leaves (%d bound, %d Farkas, %d open, %d uncertified)\n",
			rep.Nodes, rep.Leaves, rep.BoundLeaves, rep.FarkasLeaves, rep.OpenLeaves, rep.Uncertified)
	}
	if rep.GlobalBound != nil && !rep.Complete {
		fmt.Printf("  proven bound %s\n", objStr(m, rep.GlobalBound))
	}
	if !rep.Complete {
		fmt.Println("  note: proof is incomplete (search stopped early); only the listed claims are verified")
	}
	return 0, nil
}

func cmdFmt(args []string) (int, error) {
	if len(args) != 1 {
		return 2, fmt.Errorf("usage: dantzig fmt <model.lp>")
	}
	m, err := loadModel(args[0])
	if err != nil {
		return 2, err
	}
	fmt.Print(model.Format(m))
	return 0, nil
}
