package main

import (
	"flag"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"

	"bayou/internal/infer"
)

func cmdVOI(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("voi", flag.ContinueOnError)
	qf := addQueryFlags(fs, true)
	top := fs.Int("top", 8, "how many candidates to list")
	costs := fs.String("cost", "", "per-test costs NAME=c,NAME=c (ranks by gain per unit cost; default cost 1)")
	detail := fs.Bool("detail", false, "show what each outcome of the best test would tell you")
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
	cost := map[int]float64{}
	for _, kv := range splitList(*costs) {
		k := strings.IndexByte(kv, '=')
		if k < 0 {
			return usageError("--cost expects NAME=number pairs")
		}
		id, ok := net.ID(strings.TrimSpace(kv[:k]))
		if !ok {
			return fmt.Errorf("--cost: unknown variable %q", kv[:k])
		}
		c, err := strconv.ParseFloat(strings.TrimSpace(kv[k+1:]), 64)
		if err != nil || c <= 0 || math.IsInf(c, 0) || math.IsNaN(c) {
			return fmt.Errorf("--cost: %q is not a positive number", kv[k+1:])
		}
		cost[id] = c
	}
	res, err := infer.ValueOfInformation(net, q, ev)
	if err == infer.ErrImpossible {
		return fmt.Errorf("the evidence %s is impossible under this model (probability 0)", net.EvidenceString(ev))
	}
	if err != nil {
		return err
	}
	c := func(v int) float64 {
		if x, ok := cost[v]; ok {
			return x
		}
		return 1
	}
	rows := res.Rows
	if len(cost) > 0 { // re-rank by gain per cost
		sortStable(rows, func(a, b infer.VOIRow) bool { return a.Gain/c(a.Var) > b.Gain/c(b.Var) })
	}
	const bits = 1 / math.Ln2
	if *qf.asJSON {
		type jr struct {
			Variable string  `json:"variable"`
			GainBits float64 `json:"gain_bits"`
			Cost     float64 `json:"cost"`
		}
		var list []jr
		for _, r := range rows {
			list = append(list, jr{net.Vars[r.Var].Name, r.Gain * bits, c(r.Var)})
		}
		return writeJSON(out, map[string]any{"entropy_bits": res.Entropy * bits, "candidates": list})
	}
	fmt.Fprintf(out, "uncertainty about %s given %s: %.4f bits\n", strings.Join(nameList(net, q), ", "), orNone(net.EvidenceString(ev)), res.Entropy*bits)
	if len(rows) == 0 {
		fmt.Fprintln(out, "nothing left to observe")
		return nil
	}
	fmt.Fprintf(out, "\n  %-18s %10s %10s", "next observation", "gain(bits)", "expected")
	if len(cost) > 0 {
		fmt.Fprintf(out, " %6s %9s", "cost", "gain/cost")
	}
	fmt.Fprintln(out)
	for i, r := range rows {
		if i >= *top {
			break
		}
		fmt.Fprintf(out, "  %-18s %10.4f %10.4f", net.Vars[r.Var].Name, r.Gain*bits, r.Expected*bits)
		if len(cost) > 0 {
			fmt.Fprintf(out, " %6g %9.4f", c(r.Var), r.Gain*bits/c(r.Var))
		}
		fmt.Fprintf(out, "  %s\n", bar(r.Gain/res.Entropy, 24))
	}
	if *detail {
		r := rows[0]
		fmt.Fprintf(out, "\nif you observe %s:\n", net.Vars[r.Var].Name)
		for _, o := range r.Outcomes {
			fmt.Fprintf(out, "  %s = %-10s (p=%.4f) →\n", net.Vars[r.Var].Name, net.Vars[r.Var].States[o.State], o.Prob)
			distTable(out, net, o.Posterior, "      ")
		}
	}
	return nil
}

func sortStable(rows []infer.VOIRow, less func(a, b infer.VOIRow) bool) {
	for i := 1; i < len(rows); i++ { // insertion sort: stable and tiny
		for j := i; j > 0 && less(rows[j], rows[j-1]); j-- {
			rows[j], rows[j-1] = rows[j-1], rows[j]
		}
	}
}
