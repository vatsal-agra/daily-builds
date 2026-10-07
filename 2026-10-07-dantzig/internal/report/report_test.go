package report

import (
	"strings"
	"testing"

	"dantzig/internal/bb"
	"dantzig/internal/model"
	"dantzig/internal/sens"
)

func build(t *testing.T, src string, withSens bool) string {
	t.Helper()
	m, err := model.Parse(src)
	if err != nil {
		t.Fatal(err)
	}
	res := bb.Solve(m, bb.Options{})
	var sr *sens.Report
	if withSens && res.X != nil {
		lm := m
		if m.HasInts() {
			lm = sens.FixInts(m, res.X)
		}
		sr, _ = sens.Analyze(lm)
	}
	return Build("<test & model>.lp", m, res, sr)
}

func TestReportContents(t *testing.T) {
	doc := build(t, `
Maximize
 v: 10 a + 13 b + 7 c + 8 d + 12 e + 4 f
Subject To
 w: 5 a + 8 b + 3 c + 4 d + 7 e + 2 f <= 15
Binary
 a b c d e f
End`, true)
	for _, want := range []string{"<!doctype html>", "OPTIMAL", "exact certificate verified", "Proof tree", "<svg", "Sensitivity analysis", "Model SHA-256", "&lt;test &amp; model&gt;.lp"} {
		if !strings.Contains(doc, want) {
			t.Errorf("report lacks %q", want)
		}
	}
	if strings.Count(doc, "<svg") != strings.Count(doc, "</svg>") {
		t.Error("unbalanced svg tags")
	}
	if strings.Contains(doc, "<test &") {
		t.Error("model name not escaped")
	}
}

func TestReportInfeasibleAndLimit(t *testing.T) {
	doc := build(t, "Minimize\n o: x\nSubject To\n a: x >= 5\n b: x <= 3\nEnd", false)
	if !strings.Contains(doc, "INFEASIBLE") {
		t.Error("status missing")
	}
	m, _ := model.Parse("Minimize\n o: 0 x\nSubject To\n c: x - y = 0\n d: x + y - 2 z = 1\nBounds\n x free\n y free\n z free\nInteger\n x y z\nEnd")
	res := bb.Solve(m, bb.Options{NodeLimit: 3000})
	doc = Build("endless", m, res, nil)
	if !strings.Contains(doc, "LIMIT") || !strings.Contains(doc, "collapsed") {
		t.Error("large partial tree should be collapsed with a note")
	}
	if len(doc) > 3_000_000 {
		t.Errorf("report too large: %d bytes", len(doc))
	}
}
