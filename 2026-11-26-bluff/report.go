package main

import (
	"fmt"
	"html"
	"io"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
)

type convPoint struct {
	iter int
	expl float64
}

func convergence(t *Tree, iters int) ([]convPoint, Profile) {
	s := NewSolver(t)
	var pts []convPoint
	next := 1
	for k := 1; k <= iters; k++ {
		s.Step()
		if k == next || k == iters {
			e, _, _ := t.Exploitability(s.Average())
			pts = append(pts, convPoint{k, math.Max(e, 1e-9)})
			for next <= k {
				next *= 2
			}
		}
	}
	return pts, s.Average()
}

func svgChart(title string, pts []convPoint) string {
	const w, h, l, r, tp, b = 460.0, 250.0, 56.0, 14.0, 14.0, 34.0
	maxI := float64(pts[len(pts)-1].iter)
	lo, hi := math.Inf(1), math.Inf(-1)
	for _, p := range pts {
		lo, hi = math.Min(lo, math.Log10(p.expl)), math.Max(hi, math.Log10(p.expl))
	}
	lo, hi = math.Floor(lo), math.Ceil(hi)
	if hi == lo {
		hi = lo + 1
	}
	x := func(i int) float64 { return l + (w-l-r)*math.Log10(float64(i))/math.Log10(maxI) }
	y := func(e float64) float64 { return tp + (h-tp-b)*(hi-math.Log10(e))/(hi-lo) }
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg viewBox="0 0 %g %g" role="img" aria-label="%s"><title>%s</title>`, w, h, html.EscapeString(title), html.EscapeString(title))
	for d := lo; d <= hi; d++ {
		yy := y(math.Pow(10, d))
		fmt.Fprintf(&sb, `<line class="grid" x1="%g" x2="%g" y1="%.1f" y2="%.1f"/><text class="tick" x="%g" y="%.1f" text-anchor="end">1e%d</text>`, l, w-r, yy, yy, l-6, yy+4, int(d))
	}
	for i := 1; float64(i) <= maxI; i *= 10 {
		fmt.Fprintf(&sb, `<text class="tick" x="%.1f" y="%g" text-anchor="middle">%d</text>`, x(i), h-b+16, i)
	}
	fmt.Fprintf(&sb, `<text class="tick" x="%g" y="%g" text-anchor="middle">CFR+ iterations</text>`, (l+w-r)/2, h-4)
	var path []string
	for _, p := range pts {
		path = append(path, fmt.Sprintf("%.1f,%.1f", x(p.iter), y(p.expl)))
	}
	fmt.Fprintf(&sb, `<polyline class="line" points="%s"/>`, strings.Join(path, " "))
	for _, p := range pts {
		fmt.Fprintf(&sb, `<circle class="dot" cx="%.1f" cy="%.1f" r="3"><title>%d iterations: exploitability %.2e</title></circle>`, x(p.iter), y(p.expl), p.iter, p.expl)
	}
	sb.WriteString(`</svg>`)
	return sb.String()
}

func actionClass(a string) string {
	switch a {
	case "fold":
		return "a-fold"
	case "check":
		return "a-check"
	case "call":
		return "a-call"
	}
	return "a-raise"
}

func stratBars(t *Tree, prof Profile, filter func(ISet) bool) string {
	idx := []int{}
	for i, s := range t.Sets {
		if filter(s) {
			idx = append(idx, i)
		}
	}
	sort.Slice(idx, func(a, b int) bool {
		x, y := t.Sets[idx[a]], t.Sets[idx[b]]
		if x.Player != y.Player {
			return x.Player < y.Player
		}
		if len(x.Key) != len(y.Key) && strings.SplitN(x.Key, ":", 2)[1] != strings.SplitN(y.Key, ":", 2)[1] {
			return len(strings.SplitN(x.Key, ":", 2)[1]) < len(strings.SplitN(y.Key, ":", 2)[1])
		}
		return x.Key < y.Key
	})
	var sb strings.Builder
	sb.WriteString(`<div class="bars">`)
	for _, i := range idx {
		s := t.Sets[i]
		hist := strings.SplitN(s.Key, ":", 2)[1]
		if hist == "" {
			hist = "first to act"
		}
		fmt.Fprintf(&sb, `<div class="row"><span class="lab">P%d · %s · <code>%s</code></span><span class="bar">`, s.Player, html.EscapeString(strings.SplitN(s.Key[1:], ":", 2)[0]), html.EscapeString(hist))
		for a, an := range s.Actions {
			p := prof[i][a]
			if p < 0.0005 {
				continue
			}
			lab := ""
			if p >= 0.12 {
				lab = fmt.Sprintf("%s %.0f%%", an, 100*p)
			}
			fmt.Fprintf(&sb, `<i class="%s" style="width:%.2f%%" title="%s %.1f%%">%s</i>`, actionClass(an), 100*p, an, 100*p, lab)
		}
		sb.WriteString(`</span></div>`)
	}
	sb.WriteString(`</div>`)
	return sb.String()
}

func pfGrid(freq *[nClass]float64, name string) string {
	var sb strings.Builder
	fmt.Fprintf(&sb, `<div class="pf"><div class="pfh">%s</div><div class="g13">`, name)
	for r := 0; r < 13; r++ {
		for c := 0; c < 13; c++ {
			id := r*13 + c
			f := freq[id]
			fmt.Fprintf(&sb, `<b style="--f:%.2f" title="%s: %.0f%%">%s</b>`, f, ClassName(id), 100*f, ClassName(id))
		}
	}
	sb.WriteString(`</div></div>`)
	return sb.String()
}

const reportCSS = `
:root{--bg:#f7f6f2;--card:#fff;--ink:#1c1b19;--mut:#6a675f;--line:#e4e1d8;--accent:#b4302b;--fold:#8a8f98;--check:#4c8c6b;--call:#2f6db5;--raise:#c2412d;--cell:196,65,45}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14130f;--card:#1e1c17;--ink:#ece9df;--mut:#9a968a;--line:#34312a;--accent:#e2574f;--fold:#6b7078;--check:#5aa882;--call:#5a97e0;--raise:#d9604b;--cell:226,95,76}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:40px 16px 80px}
h1{font:700 44px/1.05 Georgia,"Times New Roman",serif;letter-spacing:-.02em;margin:0 0 6px}h1 span{color:var(--accent)}
.sub{color:var(--mut);margin:0 0 32px;max-width:640px}h2{font:600 22px Georgia,serif;margin:44px 0 6px}p.note{color:var(--mut);margin:0 0 16px;max-width:700px;font-size:15px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}.card b{display:block;font:600 28px Georgia,serif}.card small{color:var(--mut)}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}.charts .card h3{margin:0 0 4px;font-size:15px}
svg{width:100%;height:auto}.grid{stroke:var(--line)}.tick{fill:var(--mut);font-size:11px}.line{fill:none;stroke:var(--accent);stroke-width:2}.dot{fill:var(--accent)}
.bars{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 14px}.row{display:grid;grid-template-columns:minmax(150px,230px) 1fr;gap:12px;align-items:center;padding:4px 0}
.lab{font-size:13px;color:var(--mut)}.lab code{color:var(--ink)}.bar{display:flex;height:22px;border-radius:5px;overflow:hidden;background:var(--line)}
.bar i{font:600 11px/22px ui-sans-serif,sans-serif;font-style:normal;color:#fff;text-align:center;white-space:nowrap;overflow:hidden}
.a-fold{background:var(--fold)}.a-check{background:var(--check)}.a-call{background:var(--call)}.a-raise{background:var(--raise)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:15px}
th,td{padding:9px 14px;text-align:right;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600;font-size:13px}tr:last-child td{border:0}
.pfs{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}.pfh{font-size:13px;color:var(--mut);margin-bottom:6px}
.g13{display:grid;grid-template-columns:repeat(13,1fr);gap:2px}.g13 b{aspect-ratio:1;display:flex;align-items:center;justify-content:center;font:500 clamp(7px,1.5vw,10.5px) ui-monospace,monospace;border-radius:3px;
background:rgba(var(--cell),calc(.07 + var(--f)*.93));color:var(--ink)}.g13 b[style*="--f:1"],.g13 b[style*="--f:0.9"],.g13 b[style*="--f:0.8"]{color:#fff}
.stk{font:600 18px Georgia,serif;margin:20px 0 8px}.stk span{color:var(--mut);font:400 14px ui-sans-serif,sans-serif}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--mut);margin:0 0 10px}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
footer{margin-top:60px;color:var(--mut);font-size:13px}
`

// WriteReport renders the HTML report to path.
func WriteReport(w io.Writer, iters int, stacks []float64, samples int, progress io.Writer) error {
	kt, err := Compile(Kuhn{})
	if err != nil {
		return err
	}
	lt, err := Compile(Leduc{})
	if err != nil {
		return err
	}
	kpts, kprof := convergence(kt, iters)
	lpts, lprof := convergence(lt, iters)
	kv, lv := kt.Value(kprof), lt.Value(lprof)
	ke, _, _ := kt.Exploitability(kprof)
	le, _, _ := lt.Exploitability(lprof)

	var sb strings.Builder
	sb.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bluff report</title><style>` + reportCSS + `</style></head><body><main>`)
	sb.WriteString(`<h1>Bl<span>u</span>ff</h1><p class="sub">Poker solved from first principles: counterfactual regret minimization finds the equilibrium, an exact best-response engine proves how close it is.</p>`)
	fmt.Fprintf(&sb, `<div class="cards"><div class="card"><b>%+.4f</b><small>Kuhn value for the first player (theory: −0.0556)</small></div>
<div class="card"><b>%+.4f</b><small>Leduc value for the first player (literature: −0.0856)</small></div>
<div class="card"><b>%.1e</b><small>Leduc exploitability after %d iterations, chips/hand</small></div>
<div class="card"><b>%d</b><small>Leduc information sets (%d tree nodes)</small></div></div>`, kv, lv, le, iters, len(lt.Sets), len(lt.Nodes))
	sb.WriteString(`<h2>Convergence</h2><p class="note">Exploitability is how many chips per hand a perfect opponent could win from the strategy. Zero means a Nash equilibrium. CFR+ drives it down roughly as a power law.</p><div class="charts">`)
	fmt.Fprintf(&sb, `<div class="card"><h3>Kuhn poker (final %.1e)</h3>%s</div><div class="card"><h3>Leduc hold'em (final %.1e)</h3>%s</div></div>`, ke, svgChart("Kuhn exploitability", kpts), le, svgChart("Leduc exploitability", lpts))
	sb.WriteString(`<h2>Kuhn poker equilibrium</h2><p class="note">The solver rediscovers bluffing and slow-playing: the first player bets the Jack with some probability α ≤ ⅓ and the King 3α; the second player calls with a Queen exactly ⅓ of the time.</p><div class="legend"><span><i class="a-fold"></i>fold</span><span><i class="a-check"></i>check</span><span><i class="a-call"></i>call</span><span><i class="a-raise"></i>bet / raise</span></div>`)
	sb.WriteString(stratBars(kt, kprof, func(ISet) bool { return true }))
	sb.WriteString(`<h2>Leduc hold'em, first betting round</h2><p class="note">Strategy for every first-round decision. The full 288-information-set strategy is available as JSON via <code>bluff solve leduc -out</code>.</p>`)
	sb.WriteString(stratBars(lt, lprof, func(s ISet) bool { return !strings.Contains(s.Key, "/") && strings.Contains(s.Key, "|-:") }))

	sb.WriteString(`<h2>Exploiting the weak</h2><p class="note">Exact best responses against simple bots in Leduc, and what the solved strategy earns against each one.</p><table><tr><th>Opponent</th><th>Best response wins</th><th>Solved strategy wins</th></tr>`)
	for _, name := range BotNames() {
		b, _ := lt.BotProfile(name)
		e, _, _ := lt.Exploitability(b)
		ev := (lt.Value(lt.Compose(lprof, b)) - lt.Value(lt.Compose(b, lprof))) / 2
		fmt.Fprintf(&sb, `<tr><td>%s</td><td>%+.3f</td><td>%+.3f</td></tr>`, name, e, ev)
	}
	fmt.Fprintf(&sb, `<tr><td>solved (CFR+)</td><td>%+.5f</td><td>—</td></tr></table>`, le)

	if len(stacks) > 0 {
		m, err := BuildEqMatrix(samples, 1, progress)
		if err != nil {
			return err
		}
		sb.WriteString(`<h2>Heads-up push/fold</h2><p class="note">Nash shove and call ranges for the small blind (shoves or folds) and big blind (calls or folds) at different effective stacks. Rows and columns are ranks; suited hands sit above the diagonal, offsuit below. Darker means a higher frequency.</p>`)
		for _, st := range stacks {
			pf, err := SolvePushFold(m, st, 4000)
			if err != nil {
				return err
			}
			fmt.Fprintf(&sb, `<div class="stk">%s bb <span>SB shoves %.0f%% · BB calls %.0f%% · SB EV %+.3f bb</span></div><div class="pfs">%s%s</div>`,
				strconv.FormatFloat(st, 'f', -1, 64), pf.ShovePct, pf.CallPct, pf.SBValue, pfGrid(&pf.Shove, "Small blind shoves"), pfGrid(&pf.Call, "Big blind calls"))
		}
	}
	sb.WriteString(`<footer>Generated by Bluff — CFR+ solver, exact best response and Monte-Carlo equities, written in Go from scratch.</footer></main></body></html>`)
	_, err = io.WriteString(w, sb.String())
	return err
}

func cmdReport(args []string, out io.Writer) error {
	fs := newFlags("report")
	path := fs.String("out", "bluff-report.html", "output file")
	iters := fs.Int("iters", 2000, "CFR+ iterations")
	stacks := fs.String("stacks", "4,8,12,20", "push/fold stack depths in bb (empty to skip)")
	samples := fs.Int("samples", 1500, "equity samples per matchup for push/fold")
	if _, err := parseInterleaved(fs, args); err != nil {
		return err
	}
	if *iters < 2 {
		return fmt.Errorf("-iters must be ≥ 2")
	}
	var st []float64
	for _, f := range strings.FieldsFunc(*stacks, func(r rune) bool { return r == ',' || r == ' ' }) {
		v, err := strconv.ParseFloat(f, 64)
		if err != nil || v < 1 || v > 1000 {
			return fmt.Errorf("bad stack %q (want numbers between 1 and 1000)", f)
		}
		st = append(st, v)
	}
	f, err := os.Create(*path)
	if err != nil {
		return err
	}
	defer f.Close()
	if err := WriteReport(f, *iters, st, *samples, out); err != nil {
		return err
	}
	fmt.Fprintf(out, "wrote %s\n", *path)
	return nil
}
