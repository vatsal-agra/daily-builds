// Command dantzig is a certifying LP / MIP solver.
package main

import (
	"fmt"
	"os"
)

const usage = `dantzig — a certifying LP / MIP solver (exact rational certificates)

usage:
  dantzig solve  <model.lp> [flags]    solve; --proof FILE writes the certificate
  dantzig check  <model.lp> <proof.json>   independently re-verify a proof exactly
  dantzig sens   <model.lp>            exact sensitivity analysis of the LP optimum
  dantzig gen    <kind> [args]         print a generated model (dantzig gen list)
  dantzig fmt    <model.lp>            parse and print the canonical form
  dantzig report <model.lp> <out.html> solve and write an HTML report

solve flags:
  --proof FILE     write the JSON proof
  --no-proof       skip exact leaf certificates (faster, uncertified MIP bounds)
  --time SECONDS   wall-clock limit            --nodes N   node limit
  --branch RULE    pseudo | mostfrac           --no-dive   disable diving
  --log            print search progress       --quiet     only the status line
  --values all     print zero-valued variables too
`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	var err error
	code := 0
	switch os.Args[1] {
	case "solve":
		code, err = cmdSolve(os.Args[2:])
	case "check":
		code, err = cmdCheck(os.Args[2:])
	case "fmt":
		code, err = cmdFmt(os.Args[2:])
	case "sens":
		code, err = cmdSens(os.Args[2:])
	case "gen":
		code, err = cmdGen(os.Args[2:])
	case "report":
		code, err = cmdReport(os.Args[2:])
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n%s", os.Args[1], usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		if code == 0 {
			code = 1
		}
	}
	os.Exit(code)
}
