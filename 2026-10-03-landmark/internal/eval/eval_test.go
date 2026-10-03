package eval

import (
	"strings"
	"testing"

	"landmark/internal/index"
)

func TestHarnessEndToEnd(t *testing.T) {
	rep, err := Run(Config{Songs: 6, Negatives: 3, SongSeconds: 30, GenRate: 11025, ClipLens: []float64{6},
		Trials: 5, Seed: 7, Policy: index.DefaultPolicy(), Only: "clean"})
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 1 || rep.Rows[0].Cond != "clean" {
		t.Fatalf("Only filter ignored: %+v", rep.Rows)
	}
	c := rep.Rows[0].Cells[0]
	if c.Trials != 5 || c.Correct != 5 || c.WrongAccept != 0 || c.OffsetOK < 5 {
		t.Fatalf("clean cell %+v", c)
	}
	if rep.NegTrials == 0 || rep.NegAccepts != 0 {
		t.Fatalf("negatives %d/%d", rep.NegAccepts, rep.NegTrials)
	}
	if rep.TotalWrong() != 0 || rep.Accuracy("clean", 0) != 1 {
		t.Fatal("accounting")
	}
	for _, want := range []string{"| clean |", "False accepts", "Score margin"} {
		if !strings.Contains(rep.Markdown, want) {
			t.Fatalf("markdown lacks %q:\n%s", want, rep.Markdown)
		}
	}
}

func TestConditionBatteryIsComplete(t *testing.T) {
	cs := Conditions()
	if len(cs) < 10 {
		t.Fatalf("only %d conditions", len(cs))
	}
	seen := map[string]bool{}
	speed := 0
	for _, c := range cs {
		if seen[c.Name] || c.Apply == nil {
			t.Fatalf("bad/duplicate condition %q", c.Name)
		}
		seen[c.Name] = true
		if c.Speed > 0 {
			speed++
		}
	}
	if speed < 2 {
		t.Fatal("expected speed conditions")
	}
}
