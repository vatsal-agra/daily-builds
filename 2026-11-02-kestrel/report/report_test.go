package report

import (
	"strings"
	"testing"

	"kestrel/sim"
	"kestrel/tracker"
)

func TestHTMLReport(t *testing.T) {
	sc, _ := sim.Lookup("crossing")
	o := tracker.DefaultOptions()
	o.Trace = true
	cfg, _ := tracker.ForScenario(sc, o)
	fr, _ := sc.Run(1)
	r, err := tracker.RunFrames(sc, fr, cfg)
	if err != nil {
		t.Fatal(err)
	}
	for _, sm := range []bool{false, true} {
		page, err := HTML(r, "Test <run>", sm)
		if err != nil {
			t.Fatal(err)
		}
		for _, want := range []string{"<svg", "polyline", "Mean OSPA", "&lt;run&gt;", "prefers-color-scheme", "Confirmed tracks"} {
			if !strings.Contains(page, want) {
				t.Errorf("smoothed=%v: report missing %q", sm, want)
			}
		}
		if strings.Contains(page, "NaN") || strings.Contains(page, "Inf") {
			t.Error("report contains NaN/Inf coordinates")
		}
	}
	if _, err := HTML(nil, "x", false); err == nil {
		t.Error("nil run must error")
	}
}
