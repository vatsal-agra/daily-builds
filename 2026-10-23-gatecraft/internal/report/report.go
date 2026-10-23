// Package report renders a self-contained HTML report: design statistics,
// optimisation log, critical path, LUT mapping, property results and an
// interactive waveform viewer.
package report

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"html/template"
	"strings"

	"gatecraft/internal/aig"
	"gatecraft/internal/equiv"
	"gatecraft/internal/lutmap"
	"gatecraft/internal/sim"
)

//go:embed template.html
var tpl string

// Input gathers everything the report shows.
type Input struct {
	Title    string
	Files    []string
	Before   aig.Stats
	After    aig.Stats
	Passes   []aig.PassReport
	Verified *equiv.Result // end-to-end original ≡ optimised
	Path     aig.Path
	Maps     []*lutmap.Network
	Props    []equiv.PropResult
	PropsOf  *aig.AIG // design the properties belong to (for formatting traces)
	Waves    *sim.Trace
	TB       *sim.Result
	TBName   string
	Warnings []string
	Removed  map[string]string
}

type passRow struct {
	Name                    string
	AndsBefore, AndsAfter   int
	LatchBefore, LatchAfter int
	DepthBefore, DepthAfter int
	Time                    string
	Note                    string
	BarBefore, BarAfter     float64
}

type mapRow struct {
	K, LUTs, Depth int
	Bar            float64
	Hist           string
}

type propRow struct {
	Name, Status, Class, Detail string
	Trace                       []string
}

type pathRow struct {
	Level int
	Label string
	Inv   bool
	Bar   float64
	Gap   int // >0: this row stands for Gap anonymous gates
}

type removedRow struct{ Name, Why string }

type view struct {
	Input
	Passes2    []passRow
	Maps2      []mapRow
	Props2     []propRow
	Path2      []pathRow
	Removed2   []removedRow
	AndSaving  float64
	Wave       template.JS
	HasWave    bool
	TBSummary  string
	TBClass    string
	VerifiedOK bool
	VerifiedTx string
}

// Build renders the report.
func Build(in Input) (string, error) {
	v := view{Input: in}
	maxAnds := 1
	for _, p := range in.Passes {
		if p.Before.Ands > maxAnds {
			maxAnds = p.Before.Ands
		}
	}
	for _, p := range in.Passes {
		v.Passes2 = append(v.Passes2, passRow{
			Name: p.Name, AndsBefore: p.Before.Ands, AndsAfter: p.After.Ands,
			LatchBefore: p.Before.Latches, LatchAfter: p.After.Latches,
			DepthBefore: p.Before.Depth, DepthAfter: p.After.Depth,
			Time: p.Elapsed.Round(1e3).String(), Note: p.Note,
			BarBefore: 100 * float64(p.Before.Ands) / float64(maxAnds),
			BarAfter:  100 * float64(p.After.Ands) / float64(maxAnds),
		})
	}
	if in.Before.Ands > 0 {
		v.AndSaving = 100 * float64(in.Before.Ands-in.After.Ands) / float64(in.Before.Ands)
	}
	maxLUT := 1
	for _, m := range in.Maps {
		if len(m.LUTs) > maxLUT {
			maxLUT = len(m.LUTs)
		}
	}
	for _, m := range in.Maps {
		h := m.Histogram()
		var parts []string
		for k := 1; k <= m.K; k++ {
			if h[k] > 0 {
				parts = append(parts, fmt.Sprintf("%d×%d-in", h[k], k))
			}
		}
		v.Maps2 = append(v.Maps2, mapRow{K: m.K, LUTs: len(m.LUTs), Depth: m.Depth, Bar: 100 * float64(len(m.LUTs)) / float64(maxLUT), Hist: strings.Join(parts, "  ")})
	}
	for _, p := range in.Props {
		row := propRow{Name: p.Name}
		switch p.Status {
		case equiv.PropProved:
			row.Status, row.Class = "proved", "good"
			row.Detail = fmt.Sprintf("by %d-induction", p.Depth)
		case equiv.PropFailed:
			row.Status, row.Class = "failed", "bad"
			row.Detail = fmt.Sprintf("counterexample at cycle %d", p.Depth)
			if p.Trace != nil && in.PropsOf != nil {
				for t, inp := range p.Trace.Inputs {
					row.Trace = append(row.Trace, fmt.Sprintf("cycle %d: %s", t, equiv.FormatInputs(in.PropsOf, inp)))
				}
			}
		default:
			row.Status, row.Class = "bounded", "warn"
			row.Detail = fmt.Sprintf("no counterexample within %d cycles; not inductive", p.Depth+1)
		}
		v.Props2 = append(v.Props2, row)
	}
	// Show named nets (inputs, registers, signals) and collapse runs of anonymous gates.
	gap, gapFrom := 0, 0
	flush := func() {
		if gap > 0 {
			bar := 0.0
			if in.Path.Depth > 0 {
				bar = 100 * float64(gapFrom+gap) / float64(in.Path.Depth)
			}
			v.Path2 = append(v.Path2, pathRow{Level: gapFrom, Label: fmt.Sprintf("%d logic gates", gap), Bar: bar, Gap: gap})
			gap = 0
		}
	}
	for i, st := range in.Path.Steps {
		last := i == len(in.Path.Steps)-1
		if st.Label == "" && !last {
			if gap == 0 {
				gapFrom = st.Level
			}
			gap++
			continue
		}
		flush()
		lab := st.Label
		if lab == "" {
			lab = fmt.Sprintf("n%d", st.Node)
		}
		bar := 0.0
		if in.Path.Depth > 0 {
			bar = 100 * float64(st.Level) / float64(in.Path.Depth)
		}
		v.Path2 = append(v.Path2, pathRow{Level: st.Level, Label: lab, Inv: st.Neg, Bar: bar})
	}
	flush()
	for k, why := range in.Removed {
		d := why
		switch why {
		case "0", "1":
			d = "constant " + why
		case "dead":
			d = "unobservable"
		default:
			d = "duplicate of " + why
		}
		v.Removed2 = append(v.Removed2, removedRow{k, d})
	}
	sortRemoved(v.Removed2)
	if in.Verified != nil {
		v.VerifiedOK = in.Verified.Verdict == equiv.Equivalent
		v.VerifiedTx = fmt.Sprintf("%s — %d obligations, %d SAT conflicts", in.Verified.Verdict, in.Verified.Obligations, in.Verified.Conflicts)
	}
	if in.TB != nil {
		v.TBSummary = fmt.Sprintf("%d checks, %d failed, %d cycles", in.TB.Checks, len(in.TB.Failures), in.TB.Cycles)
		v.TBClass = "good"
		if !in.TB.OK() {
			v.TBClass = "bad"
		}
	}
	if in.Waves != nil && len(in.Waves.Times) > 0 {
		js, err := json.Marshal(waveJSON(in.Waves))
		if err != nil {
			return "", err
		}
		// "</" inside inline <script> must not close the tag
		v.Wave = template.JS(strings.ReplaceAll(string(js), "</", "<\\/"))
		v.HasWave = true
	}
	t, err := template.New("report").Parse(tpl)
	if err != nil {
		return "", err
	}
	var sb strings.Builder
	if err := t.Execute(&sb, v); err != nil {
		return "", err
	}
	return sb.String(), nil
}

func sortRemoved(r []removedRow) {
	for i := 1; i < len(r); i++ {
		for j := i; j > 0 && r[j].Name < r[j-1].Name; j-- {
			r[j], r[j-1] = r[j-1], r[j]
		}
	}
}

type waveSig struct {
	N string   `json:"n"`
	W int      `json:"w"`
	C [][2]any `json:"c"`
}

func waveJSON(tr *sim.Trace) map[string]any {
	sigs := make([]waveSig, len(tr.Names))
	for i, n := range tr.Names {
		sigs[i] = waveSig{N: n, W: tr.Widths[i]}
		prev := ""
		for r, row := range tr.Values {
			if r == 0 || row[i] != prev {
				sigs[i].C = append(sigs[i].C, [2]any{tr.Times[r], row[i]})
				prev = row[i]
			}
		}
	}
	return map[string]any{"tmax": tr.Times[len(tr.Times)-1], "sigs": sigs}
}
