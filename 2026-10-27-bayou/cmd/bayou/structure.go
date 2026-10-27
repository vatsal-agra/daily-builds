package main

import (
	"flag"
	"fmt"
	"io"
	"os"

	"bayou/internal/learn"
	"bayou/internal/parse"
)

func cmdStructure(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("structure", flag.ContinueOnError)
	score := fs.String("score", "bdeu", "bic, k2 or bdeu")
	maxPar := fs.Int("max-parents", 3, "maximum parents per variable")
	ess := fs.Float64("ess", 1, "equivalent sample size for bdeu")
	restarts := fs.Int("restarts", 0, "perturb-and-search restarts")
	seed := fs.Int64("seed", 1, "seed for restarts")
	alpha := fs.Float64("alpha", 1, "smoothing for the fitted parameters")
	truth := fs.String("truth", "", "reference network to compare the learned graph against")
	outFile := fs.String("o", "", "write the learned network (.bn) here")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if err := needPos(pos, 2, "network file (variables and states) and data.csv"); err != nil {
		return err
	}
	net, err := loadNet(pos[0])
	if err != nil {
		return err
	}
	sc, err := learn.ParseScore(*score)
	if err != nil {
		return usageError(err.Error())
	}
	f, err := os.Open(pos[1])
	if err != nil {
		return err
	}
	defer f.Close()
	ds, err := parse.ReadCSV(net, f)
	if err != nil {
		return err
	}
	res, err := learn.HillClimb(net, ds, learn.StructureOptions{Score: sc, MaxParents: *maxPar, ESS: *ess, Restarts: *restarts, Seed: *seed})
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "structure search (%s): %d rows used", sc, res.Rows)
	if res.Dropped > 0 {
		fmt.Fprintf(out, " (%d rows with missing cells dropped)", res.Dropped)
	}
	fmt.Fprintf(out, ", score %.3f, %d moves\n", res.Score, len(res.Steps))
	edges := 0
	for v, ps := range res.Parents {
		for _, p := range ps {
			fmt.Fprintf(out, "  %s → %s\n", net.Vars[p].Name, net.Vars[v].Name)
			edges++
		}
	}
	if edges == 0 {
		fmt.Fprintln(out, "  (no edges: the data look independent)")
	}
	if *truth != "" {
		tn, err := loadNet(*truth)
		if err != nil {
			return err
		}
		if len(tn.Vars) != len(net.Vars) {
			return fmt.Errorf("reference network has %d variables, expected %d", len(tn.Vars), len(net.Vars))
		}
		tp := make([][]int, len(tn.Vars))
		for v := range tn.Vars {
			id, ok := net.ID(tn.Vars[v].Name)
			if !ok || id != v {
				return fmt.Errorf("reference network must declare the same variables in the same order (%s)", tn.Vars[v].Name)
			}
			tp[v] = tn.Vars[v].Parents
		}
		d, err := learn.Compare(tp, res.Parents)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "vs. %s (compared as equivalence classes): SHD %d — missing %d, extra %d, misoriented %d, of %d true edges\n", tn.Name, d.SHD, d.Missing, d.Extra, d.Misoriented, d.TrueEdges)
	}
	if *outFile != "" {
		learned, err := res.Apply(net, ds, *alpha)
		if err != nil {
			return err
		}
		if err := os.WriteFile(*outFile, []byte(parse.FormatBN(learned)), 0o644); err != nil {
			return err
		}
		fmt.Fprintf(out, "wrote %s (structure + smoothed maximum-likelihood parameters)\n", *outFile)
	}
	return nil
}
