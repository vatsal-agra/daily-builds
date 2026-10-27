package main

import (
	"flag"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"sort"
	"strings"

	"bayou/internal/bn"
	"bayou/internal/graph"
	"bayou/internal/infer"
	"bayou/internal/learn"
	"bayou/internal/parse"
)

func cmdInfo(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("info", flag.ContinueOnError)
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
	edges := 0
	maxPar := 0
	for _, v := range net.Vars {
		edges += len(v.Parents)
		maxPar = max(maxPar, len(v.Parents))
	}
	jt, err := graph.BuildJunctionTree(net, graph.MinFill)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "network   %s\nvariables %d\nedges     %d (max in-degree %d)\nparameters %d free\n", net.Name, len(net.Vars), edges, maxPar, net.NumParams())
	fmt.Fprintf(out, "treewidth %d (%d cliques)\n\n", jt.TreeWidth(), len(jt.Cliques))
	ch := net.Children()
	for v, x := range net.Vars {
		par := "—"
		if len(x.Parents) > 0 {
			par = strings.Join(nameList(net, x.Parents), ", ")
		}
		fmt.Fprintf(out, "  %-18s {%s}  parents: %s  children: %d\n", x.Name, strings.Join(x.States, ","), par, len(ch[v]))
	}
	return nil
}

func cmdCheck(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("check", flag.ContinueOnError)
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
	if errs := net.Validate(); len(errs) > 0 {
		for _, e := range errs {
			fmt.Fprintln(out, "error:", e)
		}
		return fmt.Errorf("%d problem(s) found", len(errs))
	}
	fmt.Fprintf(out, "ok: %s — %d variables, %d free parameters, acyclic, every CPT row sums to 1\n", net.Name, len(net.Vars), net.NumParams())
	return nil
}

func cmdConvert(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("convert", flag.ContinueOnError)
	to := fs.String("to", "", "target format: bn or bif")
	outFile := fs.String("o", "", "output file (default stdout)")
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
	w := out
	if *outFile != "" {
		f, err := os.Create(*outFile)
		if err != nil {
			return err
		}
		defer f.Close()
		w = f
	}
	switch *to {
	case "bn":
		_, err = io.WriteString(w, parse.FormatBN(net))
	case "bif":
		err = parse.WriteBIF(w, net)
	default:
		return usageError("--to must be 'bn' or 'bif'")
	}
	return err
}

// queryFlags are shared by the inference commands.
type queryFlags struct {
	q, e   *string
	engine *string
	asJSON *bool
}

func addQueryFlags(fs *flag.FlagSet, needQ bool) queryFlags {
	qf := queryFlags{e: fs.String("e", "", "evidence: NAME=state,NAME=state"), asJSON: fs.Bool("json", false, "machine-readable output")}
	if needQ {
		qf.q = fs.String("q", "", "query variables, comma separated")
	}
	qf.engine = fs.String("engine", "ve", "inference engine: ve, jt or enum")
	return qf
}

func (qf queryFlags) evidence(net *bn.Network) (bn.Evidence, error) {
	return net.ParseEvidence(splitList(*qf.e))
}

func cmdQuery(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("query", flag.ContinueOnError)
	qf := addQueryFlags(fs, true)
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
	var res *infer.Result
	switch *qf.engine {
	case "ve":
		res, err = infer.VE(net, q, ev)
	case "enum":
		res, err = infer.Enumerate(net, q, ev)
	case "jt":
		jt, e := infer.NewJT(net)
		if e != nil {
			return e
		}
		cal, e := jt.Calibrate(ev)
		if e != nil {
			err = e
			break
		}
		for _, v := range q {
			if _, obs := ev[v]; obs {
				return fmt.Errorf("variable %s is both queried and observed", net.Vars[v].Name)
			}
		}
		f, e := cal.Joint(q...)
		if e != nil {
			// fall back to variable elimination for joints spanning cliques
			res, err = infer.VE(net, q, ev)
			break
		}
		res = &infer.Result{Posterior: f, LogEvidence: cal.LogEvidence}
	default:
		return usageError("--engine must be ve, jt or enum")
	}
	if err == infer.ErrImpossible {
		return fmt.Errorf("the evidence %s is impossible under this model (probability 0)", net.EvidenceString(ev))
	}
	if err != nil {
		return err
	}
	if *qf.asJSON {
		return writeJSON(out, map[string]any{"query": nameList(net, q), "evidence": net.EvidenceString(ev),
			"log_evidence": res.LogEvidence, "p_evidence": math.Exp(res.LogEvidence), "table": jsonTable(net, res)})
	}
	if len(ev) > 0 {
		fmt.Fprintf(out, "P(%s | %s)    [P(evidence) = %.6g]\n", strings.Join(nameList(net, q), ", "), net.EvidenceString(ev), math.Exp(res.LogEvidence))
	} else {
		fmt.Fprintf(out, "P(%s)\n", strings.Join(nameList(net, q), ", "))
	}
	distTable(out, net, res.Posterior, "  ")
	return nil
}

func jsonTable(net *bn.Network, res *infer.Result) []map[string]any {
	f := res.Posterior
	probs := f.Probs()
	cnt := make([]int, len(f.Vars))
	var rows []map[string]any
	for i := range probs {
		a := map[string]string{}
		for k, v := range f.Vars {
			a[net.Vars[v].Name] = net.Vars[v].States[cnt[k]]
		}
		rows = append(rows, map[string]any{"assignment": a, "p": probs[i]})
		for k := len(cnt) - 1; k >= 0; k-- {
			if cnt[k]++; cnt[k] < f.Card[k] {
				break
			}
			cnt[k] = 0
		}
	}
	return rows
}

func cmdMarginals(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("marginals", flag.ContinueOnError)
	qf := addQueryFlags(fs, false)
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
	ev, err := qf.evidence(net)
	if err != nil {
		return err
	}
	jt, err := infer.NewJT(net)
	if err != nil {
		return err
	}
	ms, lpe, err := jt.Marginals(ev)
	if err == infer.ErrImpossible {
		return fmt.Errorf("the evidence %s is impossible under this model (probability 0)", net.EvidenceString(ev))
	}
	if err != nil {
		return err
	}
	if *qf.asJSON {
		m := map[string]map[string]float64{}
		for v, f := range ms {
			m[net.Vars[v].Name] = map[string]float64{}
			for s, p := range f.Probs() {
				m[net.Vars[v].Name][net.Vars[v].States[s]] = p
			}
		}
		return writeJSON(out, map[string]any{"evidence": net.EvidenceString(ev), "log_evidence": lpe, "marginals": m})
	}
	if len(ev) > 0 {
		fmt.Fprintf(out, "posterior marginals given %s    [P(evidence) = %.6g]\n", net.EvidenceString(ev), math.Exp(lpe))
	} else {
		fmt.Fprintln(out, "prior marginals")
	}
	for v, f := range ms {
		mark := ""
		if _, obs := ev[v]; obs {
			mark = "  (observed)"
		}
		fmt.Fprintf(out, "\n%s%s\n", net.Vars[v].Name, mark)
		distTable(out, net, f, "  ")
	}
	return nil
}

func printAssignment(out io.Writer, net *bn.Network, a map[int]int, ev bn.Evidence) {
	var ids []int
	for v := range a {
		ids = append(ids, v)
	}
	sort.Ints(ids)
	for _, v := range ids {
		fmt.Fprintf(out, "  %-18s = %s\n", net.Vars[v].Name, net.Vars[v].States[a[v]])
	}
}

func cmdMPE(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("mpe", flag.ContinueOnError)
	qf := addQueryFlags(fs, false)
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
	ev, err := qf.evidence(net)
	if err != nil {
		return err
	}
	return reportMAP(out, net, infer.HiddenVars(net, ev), ev, "most probable explanation", *qf.asJSON)
}

func cmdMAP(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("map", flag.ContinueOnError)
	qf := addQueryFlags(fs, true)
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
	return reportMAP(out, net, q, ev, "MAP assignment", *qf.asJSON)
}

func reportMAP(out io.Writer, net *bn.Network, vars []int, ev bn.Evidence, title string, asJSON bool) error {
	if len(vars) == 0 {
		return fmt.Errorf("nothing to explain: every variable is observed")
	}
	r, err := infer.MAP(net, vars, ev)
	if err == infer.ErrImpossible {
		return fmt.Errorf("the evidence %s is impossible under this model (probability 0)", net.EvidenceString(ev))
	}
	if err != nil {
		return err
	}
	if asJSON {
		a := map[string]string{}
		for v, s := range r.Assign {
			a[net.Vars[v].Name] = net.Vars[v].States[s]
		}
		return writeJSON(out, map[string]any{"assignment": a, "log_joint": r.LogJoint, "posterior": math.Exp(r.LogPost)})
	}
	fmt.Fprintf(out, "%s given %s\n", title, orNone(net.EvidenceString(ev)))
	printAssignment(out, net, r.Assign, ev)
	fmt.Fprintf(out, "  P(assignment | evidence) = %.6g    log P(assignment, evidence) = %.6f\n", math.Exp(r.LogPost), r.LogJoint)
	return nil
}

func orNone(s string) string {
	if s == "" {
		return "(no evidence)"
	}
	return s
}

func cmdDsep(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("dsep", flag.ContinueOnError)
	x := fs.String("x", "", "first variable set")
	y := fs.String("y", "", "second variable set")
	z := fs.String("z", "", "conditioning set")
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
	xs, err := net.ParseVarList(*x)
	if err != nil {
		return err
	}
	ys, err := net.ParseVarList(*y)
	if err != nil {
		return err
	}
	zs, err := net.ParseVarList(*z)
	if err != nil {
		return err
	}
	if len(xs) == 0 || len(ys) == 0 {
		return usageError("-x and -y each need at least one variable")
	}
	sets := map[int]string{}
	for _, g := range []struct {
		ids  []int
		name string
	}{{xs, "x"}, {ys, "y"}, {zs, "z"}} {
		for _, v := range g.ids {
			if prev, dup := sets[v]; dup {
				return fmt.Errorf("variable %s is in both the %s and %s sets", net.Vars[v].Name, prev, g.name)
			}
			sets[v] = g.name
		}
	}
	sep := graph.DSeparated(net, xs, ys, zs)
	given := "nothing"
	if len(zs) > 0 {
		given = strings.Join(nameList(net, zs), ", ")
	}
	rel := "are d-separated"
	if !sep {
		rel = "are NOT d-separated (dependent in general)"
	}
	fmt.Fprintf(out, "{%s} and {%s} %s given {%s}\n", strings.Join(nameList(net, xs), ", "), strings.Join(nameList(net, ys), ", "), rel, given)
	return nil
}

func cmdBlanket(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("blanket", flag.ContinueOnError)
	v := fs.String("v", "", "variable")
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
	ids, err := net.ParseVarList(*v)
	if err != nil || len(ids) != 1 {
		if err == nil {
			err = usageError("-v needs exactly one variable")
		}
		return err
	}
	fmt.Fprintf(out, "Markov blanket of %s: %s\n", net.Vars[ids[0]].Name, orDash(strings.Join(nameList(net, graph.MarkovBlanket(net, ids[0])), ", ")))
	return nil
}

func orDash(s string) string {
	if s == "" {
		return "(empty)"
	}
	return s
}

func cmdIndependencies(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("independencies", flag.ContinueOnError)
	z := fs.String("z", "", "conditioning set")
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
	zs, err := net.ParseVarList(*z)
	if err != nil {
		return err
	}
	inZ := map[int]bool{}
	for _, v := range zs {
		inZ[v] = true
	}
	n := 0
	for a := range net.Vars {
		for b := a + 1; b < len(net.Vars); b++ {
			if inZ[a] || inZ[b] {
				continue
			}
			if graph.DSeparated(net, []int{a}, []int{b}, zs) {
				fmt.Fprintf(out, "%s ⫫ %s | {%s}\n", net.Vars[a].Name, net.Vars[b].Name, strings.Join(nameList(net, zs), ", "))
				n++
			}
		}
	}
	if n == 0 {
		fmt.Fprintln(out, "no pair of variables is d-separated given that set")
	}
	return nil
}

func cmdTree(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("tree", flag.ContinueOnError)
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
	jt, err := graph.BuildJunctionTree(net, graph.MinFill)
	if err != nil {
		return err
	}
	fmt.Fprintf(out, "junction tree: %d cliques, treewidth %d\n", len(jt.Cliques), jt.TreeWidth())
	for i, c := range jt.Cliques {
		fmt.Fprintf(out, "  C%-2d {%s}\n", i, strings.Join(nameList(net, c), ", "))
	}
	for _, e := range jt.Edges {
		fmt.Fprintf(out, "  C%d — C%d  separator {%s}\n", e.A, e.B, strings.Join(nameList(net, e.Sep), ", "))
	}
	return nil
}

func cmdSample(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("sample", flag.ContinueOnError)
	n := fs.Int("n", 1000, "number of rows")
	seed := fs.Int64("seed", 1, "random seed")
	missing := fs.Float64("missing", 0, "probability each cell is blanked")
	hide := fs.String("hide", "", "variables to omit from the output (latent)")
	outFile := fs.String("o", "", "output CSV (default stdout)")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if err := needPos(pos, 1, "network file"); err != nil {
		return err
	}
	if *n < 0 {
		return usageError("-n must be >= 0")
	}
	if *missing < 0 || *missing >= 1 {
		return usageError("--missing must be in [0,1)")
	}
	net, err := loadNet(pos[0])
	if err != nil {
		return err
	}
	hid, err := net.ParseVarList(*hide)
	if err != nil {
		return err
	}
	if len(hid) >= len(net.Vars) {
		return fmt.Errorf("cannot hide every variable")
	}
	ds := learn.Simulate(net, *n, rand.New(rand.NewSource(*seed)), *missing, hid)
	w := out
	if *outFile != "" {
		f, err := os.Create(*outFile)
		if err != nil {
			return err
		}
		defer f.Close()
		w = f
	}
	return parse.WriteCSV(w, net, ds)
}

func cmdLearn(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("learn", flag.ContinueOnError)
	alpha := fs.Float64("alpha", 1, "Dirichlet smoothing pseudo-count")
	em := fs.Bool("em", false, "use EM (needed for missing cells / latent variables)")
	restarts := fs.Int("restarts", 0, "extra random EM restarts")
	random := fs.Bool("random", false, "start EM from random CPTs")
	iters := fs.Int("iters", 200, "maximum EM iterations")
	seed := fs.Int64("seed", 1, "seed for EM initialisation")
	outFile := fs.String("o", "", "write the learned network (.bn) here")
	truth := fs.String("truth", "", "reference network to compare against")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if err := needPos(pos, 2, "network file and data.csv"); err != nil {
		return err
	}
	net, err := loadNet(pos[0])
	if err != nil {
		return err
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
	var learned *bn.Network
	if *em {
		res, err := learn.EM(net, ds, learn.EMOptions{MaxIter: *iters, Alpha: *alpha, Restarts: *restarts, Seed: *seed, Random: *random})
		if err != nil {
			return err
		}
		learned = res.Net
		fmt.Fprintf(out, "EM: %d iterations, converged=%v, log-likelihood %.4f → %.4f (restart %d)\n", len(res.LogLik)-1, res.Converged, res.LogLik[0], res.LogLik[len(res.LogLik)-1], res.Restart)
	} else {
		learned, err = learn.Fit(net, ds, *alpha)
		if err != nil {
			return err
		}
		ll, err := learn.LogLikelihood(learned, ds)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "maximum likelihood (alpha=%g) on %d rows: log-likelihood %.4f\n", *alpha, len(ds.Rows), ll)
	}
	if *truth != "" {
		tn, err := loadNet(*truth)
		if err != nil {
			return err
		}
		kl, err := learn.KLJoint(tn, learned)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "vs. %s: KL(truth‖learned) = %.6f nats, max CPT difference %.4f\n", tn.Name, kl, learn.MaxCPTDiff(tn, learned))
	}
	if *outFile != "" {
		if err := os.WriteFile(*outFile, []byte(parse.FormatBN(learned)), 0o644); err != nil {
			return err
		}
		fmt.Fprintf(out, "wrote %s\n", *outFile)
	} else {
		fmt.Fprint(out, "\n"+parse.FormatBN(learned))
	}
	return nil
}

func cmdGen(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("gen", flag.ContinueOnError)
	vars := fs.Int("vars", 10, "number of variables")
	seed := fs.Int64("seed", 1, "random seed")
	maxPar := fs.Int("parents", 3, "max parents per variable")
	maxCard := fs.Int("card", 3, "max states per variable")
	outFile := fs.String("o", "", "output file (default stdout)")
	_, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if *vars < 1 || *vars > 5000 || *maxPar < 0 || *maxCard < 2 {
		return usageError("need 1 <= vars <= 5000, parents >= 0, card >= 2")
	}
	net := bn.Random(rand.New(rand.NewSource(*seed)), bn.RandomOpts{Vars: *vars, MaxParents: *maxPar, MaxCard: *maxCard})
	src := parse.FormatBN(net)
	if *outFile != "" {
		return os.WriteFile(*outFile, []byte(src), 0o644)
	}
	_, err = io.WriteString(out, src)
	return err
}
