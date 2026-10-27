package main

import (
	"flag"
	"fmt"
	"io"
	"math"
	"strings"

	"bayou/internal/infer"
)

func cmdApprox(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("approx", flag.ContinueOnError)
	qf := addQueryFlags(fs, true)
	method := fs.String("method", "lw", "lw (likelihood weighting) or gibbs")
	n := fs.Int("n", 100000, "samples (per chain for gibbs)")
	burn := fs.Int("burn", 0, "gibbs burn-in sweeps (default n/5)")
	chains := fs.Int("chains", 4, "gibbs chains")
	seed := fs.Int64("seed", 1, "random seed")
	exact := fs.Bool("exact", true, "also compute the exact answer for comparison when feasible")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if err := needPos(pos, 1, "network file"); err != nil {
		return err
	}
	net, err := loadNet(pos[0])
	if err != nil {
		return err
	}
	q, err := net.ParseVarList(*qf.q)
	if err != nil {
		return err
	}
	if len(q) == 0 {
		return usageError("-q needs at least one variable")
	}
	ev, err := qf.evidence(net)
	if err != nil {
		return err
	}
	var res *infer.ApproxResult
	switch *method {
	case "lw":
		res, err = infer.LikelihoodWeighting(net, q, ev, *n, *seed)
	case "gibbs":
		res, err = infer.Gibbs(net, q, ev, infer.GibbsOptions{Samples: *n, Burn: *burn, Chains: *chains, Seed: *seed})
	default:
		return usageError("--method must be lw or gibbs")
	}
	if err != nil {
		return err
	}
	var ex *infer.Result
	if *exact {
		if r, e := infer.VE(net, q, ev); e == nil {
			ex = r
		}
	}
	if *qf.asJSON {
		m := map[string]any{"method": *method, "samples": res.Samples, "ess": res.ESS, "posterior": jsonTable(net, &infer.Result{Posterior: res.Posterior})}
		if !math.IsNaN(res.Rhat) && res.Rhat != 0 {
			m["rhat"] = res.Rhat
		}
		if ex != nil {
			m["max_abs_error"] = maxDiff(res.Posterior.Probs(), ex.Posterior.Probs())
		}
		return writeJSON(out, m)
	}
	label := map[string]string{"lw": "likelihood weighting", "gibbs": "Gibbs sampling"}[*method]
	fmt.Fprintf(out, "%s: %d samples, effective sample size %.0f", label, res.Samples, res.ESS)
	if *method == "gibbs" {
		fmt.Fprintf(out, ", R̂ = %.3f", res.Rhat)
		if res.Rhat > 1.1 {
			fmt.Fprint(out, "  ← chains disagree; do not trust this result")
		}
	} else if res.ESS < 100 {
		fmt.Fprint(out, "  ← evidence is rare; very few samples carry weight")
	}
	fmt.Fprintln(out)
	fmt.Fprintf(out, "P(%s | %s)\n", strings.Join(nameList(net, q), ", "), orNone(net.EvidenceString(ev)))
	distTable(out, net, res.Posterior, "  ")
	if ex != nil {
		fmt.Fprintf(out, "exact (variable elimination) differs by at most %.5f\n", maxDiff(res.Posterior.Probs(), ex.Posterior.Probs()))
	} else if *exact {
		fmt.Fprintln(out, "(exact inference is infeasible for this network, so no comparison is available)")
	}
	return nil
}

func maxDiff(a, b []float64) float64 {
	d := 0.0
	for i := range a {
		d = math.Max(d, math.Abs(a[i]-b[i]))
	}
	return d
}
