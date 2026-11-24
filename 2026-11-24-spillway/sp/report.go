package sp

import (
	"fmt"
	"html"
	"math"
	"sort"
	"strings"
)

// InterferenceEdges returns the interference graph of f (precise, per-point).
func InterferenceEdges(f *Function) [][2]int {
	lv := f.Liveness()
	seen := map[[2]int]bool{}
	var edges [][2]int
	f.LiveAfter(lv, func(bi, ii int, live Bitset) {
		in := &f.Blocks[bi].Instrs[ii]
		if !in.HasDst() {
			return
		}
		src := -1
		if in.Op == OpMov && !in.Args[0].Imm {
			src = in.Args[0].Reg
		}
		live.each(func(l int) {
			if l == in.Dst || l == src {
				return
			}
			a, b := l, in.Dst
			if a > b {
				a, b = b, a
			}
			if !seen[[2]int{a, b}] {
				seen[[2]int{a, b}] = true
				edges = append(edges, [2]int{a, b})
			}
		})
	})
	sort.Slice(edges, func(i, j int) bool {
		if edges[i][0] != edges[j][0] {
			return edges[i][0] < edges[j][0]
		}
		return edges[i][1] < edges[j][1]
	})
	return edges
}

func regColor(k int) string {
	// golden-angle hues keep neighbouring registers distinguishable
	h := math.Mod(float64(k)*137.508+20, 360)
	l := 52 + 10*float64(k%3)
	return fmt.Sprintf("hsl(%.0f,62%%,%.0f%%)", h, l)
}

func esc(s string) string { return html.EscapeString(s) }

// rangeChart draws the live intervals of a rewritten function coloured by
// assigned physical register. Rows are sorted by interval start.
func rangeChart(a *Allocation) string {
	f := a.Rewritten
	lv := f.Liveness()
	ivs, nm := f.Intervals(lv)
	sort.Slice(ivs, func(i, j int) bool {
		if ivs[i].Start != ivs[j].Start {
			return ivs[i].Start < ivs[j].Start
		}
		return ivs[i].Reg < ivs[j].Reg
	})
	const maxRows = 90
	truncated := 0
	if len(ivs) > maxRows {
		truncated = len(ivs) - maxRows
		ivs = ivs[:maxRows]
	}
	rowH, left, top := 13, 92, 22
	width := 860
	plotW := float64(width - left - 14)
	total := float64(2*nm.Total + 2)
	h := top + len(ivs)*rowH + 10
	depth := f.LoopDepth()
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="live ranges coloured by register">`, width, h)
	for bi, b := range f.Blocks {
		x0 := float64(left) + plotW*float64(2*nm.BlockStart[bi])/total
		x1 := float64(left) + plotW*float64(2*nm.BlockEnd[bi]+2)/total
		if depth[bi] > 0 {
			fmt.Fprintf(&sb, `<rect x="%.1f" y="%d" width="%.1f" height="%d" class="loopband" opacity="%.2f"/>`, x0, top, x1-x0, h-top-6, 0.10+0.07*float64(min(depth[bi], 3)))
		}
		fmt.Fprintf(&sb, `<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="grid"/>`, x0, top-6, x0, h-6)
		if x1-x0 > 26 {
			fmt.Fprintf(&sb, `<text x="%.1f" y="%d" class="lbl small">%s</text>`, x0+3, top-9, esc(b.Name))
		}
	}
	for i, iv := range ivs {
		y := top + i*rowH
		x0 := float64(left) + plotW*float64(iv.Start)/total
		x1 := float64(left) + plotW*float64(iv.End+1)/total
		col := "var(--muted)"
		if r := a.Assign[iv.Reg]; r >= 0 {
			col = regColor(r)
		}
		tmp := strings.HasSuffix(f.RegName(iv.Reg), "~")
		cls := ""
		if tmp {
			cls = ` class="tmp"`
		}
		fmt.Fprintf(&sb, `<text x="%d" y="%d" class="lbl small" text-anchor="end">%s</text>`, left-6, y+rowH-3, esc(f.RegName(iv.Reg)))
		fmt.Fprintf(&sb, `<rect x="%.1f" y="%d" width="%.1f" height="%d" rx="2" fill="%s"%s><title>%s  [%d,%d]  r%d</title></rect>`,
			x0, y+2, math.Max(x1-x0, 2.5), rowH-4, col, cls, esc(f.RegName(iv.Reg)), iv.Start, iv.End, a.Assign[iv.Reg])
	}
	sb.WriteString(`</svg>`)
	if truncated > 0 {
		fmt.Fprintf(&sb, `<p class="note">%d further short ranges not drawn.</p>`, truncated)
	}
	return sb.String()
}

// graphChart draws the interference graph on a circle, nodes coloured by register.
func graphChart(a *Allocation) string {
	f := a.Rewritten
	edges := InterferenceEdges(f)
	var nodes []int
	deg := map[int]int{}
	for _, e := range edges {
		deg[e[0]]++
		deg[e[1]]++
	}
	for r := 0; r < f.NumRegs; r++ {
		if a.Assign[r] >= 0 {
			nodes = append(nodes, r)
		}
	}
	if len(nodes) > 70 {
		return fmt.Sprintf(`<p class="note">Interference graph has %d nodes and %d edges — too large to draw legibly.</p>`, len(nodes), len(edges))
	}
	// order around the circle by assigned register so same-colour nodes cluster
	sort.Slice(nodes, func(i, j int) bool {
		if a.Assign[nodes[i]] != a.Assign[nodes[j]] {
			return a.Assign[nodes[i]] < a.Assign[nodes[j]]
		}
		return nodes[i] < nodes[j]
	})
	const size = 520
	cx, cy, rad := float64(size)/2, float64(size)/2, float64(size)/2-46
	pos := map[int][2]float64{}
	for i, n := range nodes {
		ang := 2*math.Pi*float64(i)/float64(len(nodes)) - math.Pi/2
		pos[n] = [2]float64{cx + rad*math.Cos(ang), cy + rad*math.Sin(ang)}
	}
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="chart graph" viewBox="0 0 %d %d" role="img" aria-label="interference graph">`, size, size)
	for _, e := range edges {
		p, q := pos[e[0]], pos[e[1]]
		fmt.Fprintf(&sb, `<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="edge"/>`, p[0], p[1], q[0], q[1])
	}
	for _, n := range nodes {
		p := pos[n]
		fmt.Fprintf(&sb, `<circle cx="%.1f" cy="%.1f" r="9" fill="%s" class="node"><title>%s → r%d (degree %d)</title></circle>`,
			p[0], p[1], regColor(a.Assign[n]), esc(f.RegName(n)), a.Assign[n], deg[n])
		if len(nodes) <= 40 {
			dx, dy := p[0]-cx, p[1]-cy
			d := math.Hypot(dx, dy)
			fmt.Fprintf(&sb, `<text x="%.1f" y="%.1f" class="lbl small" text-anchor="middle">%s</text>`, p[0]+dx/d*21, p[1]+dy/d*21+3, esc(f.RegName(n)))
		}
	}
	sb.WriteString(`</svg>`)
	fmt.Fprintf(&sb, `<p class="note">%d nodes, %d interference edges. Node colour = assigned register.</p>`, len(nodes), len(edges))
	return sb.String()
}

// sweepChart plots cycles against K for each allocator.
func sweepChart(sweep [][]Row) string {
	if len(sweep) == 0 {
		return ""
	}
	maxY := 1
	for _, rows := range sweep {
		for _, r := range rows {
			if r.Alloc != nil && r.Dyn.Cycles > maxY {
				maxY = r.Dyn.Cycles
			}
		}
	}
	const w, h, l, t, b, r = 640, 300, 64, 16, 40, 16
	px := func(i int) float64 { return float64(l) + float64(w-l-r)*float64(i)/math.Max(float64(len(sweep)-1), 1) }
	py := func(c int) float64 { return float64(t) + float64(h-t-b)*(1-float64(c)/float64(maxY)) }
	cols := []string{"var(--c1)", "var(--c2)", "var(--c3)"}
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="cycles versus register count">`, w, h)
	for i := 0; i <= 4; i++ {
		v := maxY * i / 4
		y := py(v)
		fmt.Fprintf(&sb, `<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/><text x="%d" y="%.1f" class="lbl small" text-anchor="end">%d</text>`, l, w-r, y, y, l-6, y+3, v)
	}
	for i, rows := range sweep {
		step := 1
		if len(sweep) > 14 {
			step = 2
		}
		if i%step == 0 {
			fmt.Fprintf(&sb, `<text x="%.1f" y="%d" class="lbl small" text-anchor="middle">%d</text>`, px(i), h-b+16, rows[0].K)
		}
	}
	fmt.Fprintf(&sb, `<text x="%d" y="%d" class="lbl small" text-anchor="middle">physical registers (K)</text>`, (l+w-r)/2, h-6)
	for ai := range Allocators {
		var pts []string
		for i, rows := range sweep {
			if rows[ai].Alloc != nil && rows[ai].Verified {
				pts = append(pts, fmt.Sprintf("%.1f,%.1f", px(i), py(rows[ai].Dyn.Cycles)))
			}
		}
		fmt.Fprintf(&sb, `<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2" stroke-linejoin="round"/>`, strings.Join(pts, " "), cols[ai])
		for _, p := range pts {
			xy := strings.Split(p, ",")
			fmt.Fprintf(&sb, `<circle cx="%s" cy="%s" r="2.6" fill="%s"/>`, xy[0], xy[1], cols[ai])
		}
	}
	sb.WriteString(`</svg><div class="legend">`)
	for ai, name := range Allocators {
		fmt.Fprintf(&sb, `<span><i style="background:%s"></i>%s</span>`, cols[ai], name)
	}
	sb.WriteString(`</div>`)
	return sb.String()
}

func asmListing(a *Allocation) string {
	var sb strings.Builder
	sb.WriteString(`<pre class="asm">`)
	for _, b := range a.Machine.Blocks {
		fmt.Fprintf(&sb, `<span class="lab">%s:</span>`+"\n", esc(b.Name))
		for i := range b.Instrs {
			in := &b.Instrs[i]
			cls := ""
			switch in.Op {
			case OpSpillLd, OpSpillSt:
				cls = ` class="spill"`
			case OpMov:
				cls = ` class="mv"`
			}
			fmt.Fprintf(&sb, `    <span%s>%s</span>`+"\n", cls, esc(a.Machine.FormatInstr(in)))
		}
	}
	sb.WriteString(`</pre>`)
	return sb.String()
}

// ReportInput configures HTML report generation.
type ReportInput struct {
	Source string // original IR text
	F      *Function
	K      int
	Inputs [][]int64
}

// MaxPressure is the largest number of simultaneously live values.
func MaxPressure(f *Function) int {
	lv := f.Liveness()
	m := 0
	f.LiveAfter(lv, func(bi, ii int, live Bitset) {
		if c := live.count(); c > m {
			m = c
		}
	})
	return m
}

// Report renders a self-contained HTML page comparing the allocators.
func Report(in ReportInput) (string, error) {
	f := in.F
	rows := Compare(f, in.K, in.Inputs, true)
	for _, r := range rows {
		if r.Err != nil {
			return "", fmt.Errorf("%s: %w", r.Allocator, r.Err)
		}
	}
	kmax := min(max(MaxPressure(f)+2, 8), 24)
	sweep := Sweep(f, MinK, kmax, in.Inputs, true)
	for _, rs := range sweep {
		for _, r := range rs {
			if r.Err != nil {
				return "", fmt.Errorf("sweep K=%d %s: %w", r.K, r.Allocator, r.Err)
			}
		}
	}
	colorA, linA := rows[0].Alloc, rows[1].Alloc
	noPost, err := Allocate(f, "color", in.K, Options{Coalesce: true, NoPost: true})
	if err != nil {
		return "", err
	}
	noPostStats, err := Verify(f, noPost, in.Inputs)
	if err != nil {
		return "", err
	}
	best := rows[0]
	for _, r := range rows[:2] {
		if r.Dyn.Cycles < best.Dyn.Cycles {
			best = r
		}
	}
	var sb strings.Builder
	sb.WriteString(reportHead)
	fmt.Fprintf(&sb, `<header><h1>Spillway <span>register allocation report</span></h1>
<p class="sub"><b>%s</b> · %d virtual registers · %d blocks · %d instructions · max pressure <b>%d</b> · compiled for <b>K = %d</b> physical registers</p></header>`,
		esc(f.Name), f.NumRegs, len(f.Blocks), f.NumInstrs(), MaxPressure(f), in.K)
	sb.WriteString(`<section><h2>Allocators head to head</h2><div class="cards">`)
	for i, r := range rows {
		badge := ""
		if r.Allocator == best.Allocator {
			badge = `<em>fastest</em>`
		}
		fmt.Fprintf(&sb, `<div class="card c%d"><h3>%s %s</h3><div class="big">%d<small> cycles</small></div><ul>
<li><b>%d</b> variables spilled</li><li><b>%d</b> / <b>%d</b> static reloads / stores</li><li><b>%d</b> dynamic spill ops</li><li><b>%d</b> moves left (of %d)</li><li>output identical to reference ✓</li></ul></div>`,
			i+1, r.Allocator, badge, r.Dyn.Cycles, r.Alloc.SpilledVars, r.Static.SpillLoads, r.Static.SpillStores,
			r.Dyn.SpillLoads+r.Dyn.SpillStores, r.Static.Moves, r.Alloc.MovesBefore)
	}
	sb.WriteString(`</div>`)
	fmt.Fprintf(&sb, `<p class="note">Cycle model: ALU/mov/const 1 · mul 3 · div/rem 12 · load/store/spill 4 · branch 1–2. Totals cover %d input vector(s). Post-allocation clean-up took the colouring allocator from <b>%d</b> to <b>%d</b> cycles (%d reloads dropped, %d turned into moves, %d dead stores removed, stack slots %d → %d).</p></section>`,
		len(in.Inputs), noPostStats.Cycles, rows[0].Dyn.Cycles, colorA.Post.LoadsDropped, colorA.Post.LoadsToMoves, colorA.Post.DeadStores, colorA.Post.SlotsBefore, colorA.Post.SlotsAfter)

	sb.WriteString(`<section><h2>Cost as the register file grows</h2>` + sweepChart(sweep))
	sb.WriteString(`<table><tr><th>K</th>`)
	for _, n := range Allocators {
		fmt.Fprintf(&sb, `<th>%s cycles</th><th>spill ops</th>`, n)
	}
	sb.WriteString(`</tr>`)
	for _, rs := range sweep {
		fmt.Fprintf(&sb, `<tr><td>%d</td>`, rs[0].K)
		for _, r := range rs {
			fmt.Fprintf(&sb, `<td>%d</td><td>%d</td>`, r.Dyn.Cycles, r.Dyn.SpillLoads+r.Dyn.SpillStores)
		}
		sb.WriteString(`</tr>`)
	}
	sb.WriteString(`</table></section>`)

	sb.WriteString(`<section><h2>Live ranges — graph colouring</h2><p class="note">Each bar is one value's live interval (x = program position, banded areas are loops); colour = physical register, grey = no register. Faded bars are spill-reload temporaries.</p>` + rangeChart(colorA) + `</section>`)
	sb.WriteString(`<section><h2>Live ranges — linear scan</h2>` + rangeChart(linA) + `</section>`)
	sb.WriteString(`<section><h2>Interference graph (colouring allocator)</h2>` + graphChart(colorA) + `</section>`)
	sb.WriteString(`<section><h2>Generated machine code — graph colouring, K=` + fmt.Sprint(in.K) + `</h2><p class="note"><span class="spill">spill traffic</span> and <span class="mv">surviving moves</span> highlighted.</p>` + asmListing(colorA) + `</section>`)
	sb.WriteString(`<section><h2>Source IR</h2><pre class="asm">` + esc(strings.TrimSpace(in.Source)) + `</pre></section>`)
	sb.WriteString(`<footer>Generated by Spillway — every number above comes from executing the allocated machine code and comparing it with the reference interpreter.</footer></body></html>`)
	return sb.String(), nil
}

const reportHead = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Spillway report</title><style>
:root{--bg:#f6f4ef;--fg:#1d1b18;--muted:#9a948a;--card:#fffdf8;--line:#e2ddd2;--accent:#b4451f;--c1:#c2410c;--c2:#0e7490;--c3:#8a8576;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--loop:#b4451f}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15130f;--fg:#ece7dc;--muted:#6f695d;--card:#1e1b16;--line:#332f27;--accent:#f08a5d;--c1:#fb923c;--c2:#22d3ee;--c3:#8f8978;--loop:#f08a5d}}
*{box-sizing:border-box}body{margin:0 auto;max-width:960px;padding:28px 16px 60px;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}
h1{font-size:28px;margin:0;letter-spacing:-.02em}h1 span{display:block;font-size:14px;font-weight:500;color:var(--accent);letter-spacing:.08em;text-transform:uppercase;margin-top:2px}
h2{font-size:18px;margin:0 0 10px}h3{margin:0 0 4px;font-size:15px;text-transform:capitalize}
.sub{color:var(--muted);margin:10px 0 0}section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:20px 0;overflow:hidden}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;border-top:4px solid var(--c1)}
.card.c2{border-top-color:var(--c2)}.card.c3{border-top-color:var(--c3)}.card em{font-style:normal;font-size:11px;background:var(--accent);color:#fff;border-radius:99px;padding:2px 8px;margin-left:6px;vertical-align:middle;text-transform:uppercase;letter-spacing:.05em}
.big{font-size:34px;font-weight:700;letter-spacing:-.02em}.big small{font-size:13px;font-weight:500;color:var(--muted)}ul{margin:8px 0 0;padding-left:18px;color:var(--fg)}li{margin:2px 0}
.note{color:var(--muted);font-size:13px;margin:10px 0 0}table{border-collapse:collapse;width:100%;margin-top:14px;font-size:13px;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:600}td:first-child,th:first-child{text-align:left}
.chart{width:100%;height:auto;display:block}.chart .grid{stroke:var(--line);stroke-width:1}.chart .lbl{fill:var(--muted);font:11px var(--mono)}.chart .small{font-size:9.5px}.chart .loopband{fill:var(--loop)}
.chart .edge{stroke:var(--muted);stroke-opacity:.35;stroke-width:1}.chart .node{stroke:var(--card);stroke-width:2}.chart rect.tmp{opacity:.6}.chart.graph{max-width:520px;margin:0 auto}
.legend{display:flex;gap:16px;justify-content:center;font-size:13px;margin-top:6px}.legend i{display:inline-block;width:18px;height:4px;border-radius:2px;margin-right:6px;vertical-align:middle}
.asm{font:12.5px/1.5 var(--mono);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px 14px;overflow:auto;max-height:520px;margin:10px 0 0}.asm .lab{color:var(--accent);font-weight:700}.spill{color:#fff;background:#b4451f;border-radius:3px;padding:0 3px}.mv{color:var(--c2);font-weight:600}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .spill{background:#8f3a1c}}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:30px}@media (max-width:560px){body{padding:16px 10px}section{padding:14px}.big{font-size:28px}}
</style></head><body>`
