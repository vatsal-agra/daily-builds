package main

import (
	"flag"
	"fmt"
	"io"
	"os"

	"bayou/internal/infer"
	"bayou/internal/report"
)

func cmdReport(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("report", flag.ContinueOnError)
	e := fs.String("e", "", "initial evidence: NAME=state,NAME=state")
	outFile := fs.String("o", "", "output HTML file (required)")
	pos, err := parseArgs(fs, args)
	if err != nil {
		return err
	}
	if err := needPos(pos, 1, "network file"); err != nil {
		return err
	}
	if *outFile == "" {
		return usageError("-o report.html is required")
	}
	net, err := loadNet(pos[0])
	if err != nil {
		return err
	}
	ev, err := net.ParseEvidence(splitList(*e))
	if err != nil {
		return err
	}
	if _, err := infer.LogEvidence(net, ev); err != nil {
		if err == infer.ErrImpossible {
			return fmt.Errorf("the evidence %s is impossible under this model (probability 0)", net.EvidenceString(ev))
		}
		return err
	}
	page, err := report.Build(net, ev)
	if err != nil {
		return err
	}
	if err := os.WriteFile(*outFile, []byte(page), 0o644); err != nil {
		return err
	}
	fmt.Fprintf(out, "wrote %s (%d KB, self-contained)\n", *outFile, len(page)/1024)
	return nil
}
