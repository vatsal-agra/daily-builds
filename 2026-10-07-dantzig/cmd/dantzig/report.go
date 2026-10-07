package main

import (
	"fmt"
	"os"
	"path/filepath"

	"dantzig/internal/bb"
	"dantzig/internal/report"
	"dantzig/internal/sens"
)

func cmdReport(args []string) (int, error) {
	f, pos, err := parseSolveFlags("report", args)
	if err != nil {
		return 2, err
	}
	if len(pos) != 2 {
		return 2, fmt.Errorf("usage: dantzig report <model.lp> <out.html> [solve flags]")
	}
	m, err := loadModel(pos[0])
	if err != nil {
		return 2, err
	}
	f.noProof = false
	res := runSolve(m, f)
	var sr *sens.Report
	if res.Status == bb.Optimal && res.X != nil {
		lpm := m
		if m.HasInts() {
			lpm = sens.FixInts(m, res.X)
		}
		if r, err := sens.Analyze(lpm); err == nil {
			sr = r
		}
	}
	doc := report.Build(filepath.Base(pos[0]), m, res, sr)
	if err := os.WriteFile(pos[1], []byte(doc), 0o644); err != nil {
		return 1, err
	}
	fmt.Printf("status: %s — report written to %s (%d bytes)\n", res.Status, pos[1], len(doc))
	return 0, nil
}
