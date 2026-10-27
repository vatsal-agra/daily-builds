// Command bayou is the command-line front end of the Bayou Bayesian-network engine.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
)

type command struct {
	name, args, help string
	run              func(args []string, out io.Writer) error
}

var commands []command

func init() {
	commands = []command{
		{"info", "NET", "summarise a network: variables, edges, parameters, treewidth", cmdInfo},
		{"check", "NET", "validate a network file (exit 1 with all problems listed)", cmdCheck},
		{"convert", "NET --to bn|bif", "translate between the .bn language and BIF", cmdConvert},
		{"query", "NET -q A,B [-e X=s,...] [--engine ve|jt|enum]", "posterior P(query | evidence)", cmdQuery},
		{"marginals", "NET [-e X=s,...]", "every variable's posterior in one junction-tree pass", cmdMarginals},
		{"mpe", "NET [-e X=s,...]", "most probable explanation of the evidence", cmdMPE},
		{"map", "NET -q A,B [-e X=s,...]", "maximum a-posteriori assignment of some variables", cmdMAP},
		{"dsep", "NET -x A -y B [-z C,D]", "are A and B d-separated given C,D?", cmdDsep},
		{"blanket", "NET -v A", "Markov blanket of a variable", cmdBlanket},
		{"independencies", "NET [-z C,D]", "list every pair d-separated given Z", cmdIndependencies},
		{"tree", "NET", "print the junction tree (cliques and separators)", cmdTree},
		{"sample", "NET -n N [--seed S] [--missing P] [--hide A,B] [-o data.csv]", "forward-sample a dataset", cmdSample},
		{"learn", "NET data.csv [--alpha A] [--em] [-o out.bn] [--truth NET]", "learn parameters (MLE or EM)", cmdLearn},
		{"structure", "NET data.csv [--score bic|k2|bdeu] [--truth NET] [-o out.bn]", "learn the graph from data (tabu search)", cmdStructure},
		{"voi", "NET -q A [-e ...] [--cost X=2,...] [--detail]", "which next observation is most informative about A?", cmdVOI},
		{"report", "NET [-e ...] -o report.html", "interactive self-contained HTML report", cmdReport},
		{"approx", "NET -q A [-e ...] [--method lw|gibbs] [-n N]", "approximate inference (sampling) with error vs. exact", cmdApprox},
		{"gen", "--vars N [--seed S] [-o out.bn]", "generate a random network", cmdGen},
	}
}

func usage(w io.Writer) {
	fmt.Fprint(w, "bayou — a Bayesian-network engine\n\nusage: bayou <command> [args]\n\n")
	names := make([]string, 0, len(commands))
	width := 0
	for _, c := range commands {
		names = append(names, c.name)
		if l := len(c.name) + 1 + len(c.args); l > width {
			width = l
		}
	}
	sort.Strings(names)
	for _, c := range commands {
		fmt.Fprintf(w, "  %-*s  %s\n", width, c.name+" "+c.args, c.help)
	}
	fmt.Fprintln(w, "\nNetworks are .bn files (see examples/) or BIF files. Evidence is NAME=state,NAME=state.")
}

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
		usage(stdout)
		if len(args) == 0 {
			return 2
		}
		return 0
	}
	for _, c := range commands {
		if c.name == args[0] {
			if err := c.run(args[1:], stdout); err != nil {
				if errors.Is(err, flag.ErrHelp) {
					return 0
				}
				var ue usageError
				if errors.As(err, &ue) {
					fmt.Fprintf(stderr, "bayou %s: %v\nusage: bayou %s %s\n", c.name, err, c.name, c.args)
					return 2
				}
				fmt.Fprintf(stderr, "bayou %s: %v\n", c.name, err)
				return 1
			}
			return 0
		}
	}
	fmt.Fprintf(stderr, "bayou: unknown command %q\n\n", args[0])
	usage(stderr)
	return 2
}

type usageError string

func (u usageError) Error() string { return string(u) }

// parseArgs parses flags interspersed with positional arguments.
func parseArgs(fs *flag.FlagSet, args []string) ([]string, error) {
	fs.SetOutput(io.Discard)
	var pos []string
	for {
		if err := fs.Parse(args); err != nil {
			if errors.Is(err, flag.ErrHelp) {
				fs.SetOutput(os.Stdout)
				fmt.Fprintf(os.Stdout, "usage of bayou %s:\n", fs.Name())
				fs.PrintDefaults()
				return nil, err
			}
			return nil, usageError(err.Error())
		}
		rest := fs.Args()
		if len(rest) == 0 {
			return pos, nil
		}
		pos = append(pos, rest[0])
		args = rest[1:]
	}
}

func splitList(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
