package main

import (
	"flag"
	"fmt"
	"math"
	"os"

	"girder/fem"
)

func cmdValidate(args []string) error {
	fs := flag.NewFlagSet("validate", flag.ContinueOnError)
	out := fs.String("o", "", "write an HTML report")
	if err := fs.Parse(args); err != nil {
		return err
	}
	cs, conv, err := fem.RunValidation()
	if err != nil {
		return err
	}
	failed := 0
	for _, c := range cs {
		st := "PASS"
		if !c.Pass() {
			st, failed = "FAIL", failed+1
		}
		fmt.Printf("[%s] %-46s got %-12.6g want %-12.6g err %.2e (tol %.0e)\n", st, c.Name, c.Got, c.Want, c.Err(), c.Tol)
	}
	fmt.Println("\nconvergence (L2 displacement error, Timoshenko-Goodier cantilever):")
	for _, r := range conv {
		rate := "   -"
		if !math.IsNaN(r.Rate) {
			rate = fmt.Sprintf("%.2f", r.Rate)
		}
		fmt.Printf("  %-5s h=%-7.4g dofs=%-6d err=%.3e order=%s\n", r.Type, r.H, r.DOFs, r.Err, rate)
	}
	if *out != "" {
		if err := os.WriteFile(*out, []byte(fem.ValidationReport(cs, conv)), 0o644); err != nil {
			return err
		}
	}
	if failed > 0 {
		return fmt.Errorf("%d validation check(s) failed", failed)
	}
	fmt.Printf("\nall %d checks passed\n", len(cs))
	return nil
}
