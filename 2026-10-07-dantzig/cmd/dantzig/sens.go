package main

import (
	"fmt"
	"math/big"
	"os"
	"strings"
	"text/tabwriter"

	"dantzig/internal/bb"
	"dantzig/internal/model"
	"dantzig/internal/sens"
)

func ratCell(r *big.Rat) string {
	if r == nil {
		return "-"
	}
	if r.IsInt() {
		return r.Num().String()
	}
	if s := r.RatString(); len(s) <= 14 {
		return s
	}
	return model.DecStr(r)
}

func rangeCell(r sens.Range) string {
	lo, hi := "-inf", "+inf"
	if r.Lo != nil {
		lo = ratCell(r.Lo)
	}
	if r.Hi != nil {
		hi = ratCell(r.Hi)
	}
	return "[" + lo + ", " + hi + "]"
}

func cmdSens(args []string) (int, error) {
	if len(args) != 1 {
		return 2, fmt.Errorf("usage: dantzig sens <model.lp>")
	}
	m, err := loadModel(args[0])
	if err != nil {
		return 2, err
	}
	lpModel := m
	if m.HasInts() {
		res := bb.Solve(m, bb.Options{})
		if res.Status != bb.Optimal {
			return 10, fmt.Errorf("MIP is %s; sensitivity analysis needs an optimal solution", res.Status)
		}
		lpModel = sens.FixInts(m, res.X)
		fmt.Println("MIP: integer variables fixed at their optimal values; analysing the remaining LP")
	}
	rep, err := sens.Analyze(lpModel)
	if err != nil {
		return 10, err
	}
	sense := "min"
	if m.Maximize {
		sense = "max"
	}
	fmt.Printf("objective (%s): %s\n\n", sense, objStr(m, rep.Objective))
	w := tabwriter.NewWriter(os.Stdout, 2, 4, 2, ' ', 0)
	fmt.Fprintln(w, "VARIABLE\tVALUE\tSTATUS\tCOST\tREDUCED COST\tCOST RANGE (basis stays optimal)")
	for _, v := range rep.Vars {
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\n", v.Name, ratCell(v.Value), v.Status, ratCell(v.Cost), ratCell(v.ReducedCost), rangeCell(v.CostRange))
	}
	w.Flush()
	fmt.Println()
	w = tabwriter.NewWriter(os.Stdout, 2, 4, 2, ' ', 0)
	fmt.Fprintln(w, "CONSTRAINT\tACTIVITY\tSLACK\tBINDING\tSHADOW PRICE\tLIMIT RANGE (price stays valid)")
	for _, r := range rep.Rows {
		b := r.Binding
		if b == "" {
			b = "-"
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\n", r.Name, ratCell(r.Activity), ratCell(r.Slack), b, ratCell(r.Dual), rangeCell(r.LimitRange))
	}
	w.Flush()
	fmt.Println()
	fmt.Println(strings.TrimSpace(`
shadow price = change in the objective per unit increase of the binding limit (model's own sense).
All numbers are exact; ranges are valid for one change at a time.`))
	return 0, nil
}
