package sable

import (
	"fmt"
	"html"
	"sort"
	"strings"
)

// ---- CFG drawing (layered layout, inline SVG) ----

type nodeBox struct {
	b        *Block
	lines    []string
	x, y     float64
	w, h     float64
	layer    int
	isHeader bool
}

const (
	charW   = 7.4
	lineH   = 15.0
	padX    = 10.0
	padY    = 8.0
	hGap    = 36.0
	vGap    = 44.0
	maxLine = 11 // instructions shown per block before eliding
)

// CFGSVG renders f's control-flow graph with every instruction listed.
func CFGSVG(f *Func) string {
	an := Analyze(f)
	loops := an.Loops()
	headers := map[*Block]bool{}
	for _, l := range loops {
		headers[l.Header] = true
	}
	boxes := map[*Block]*nodeBox{}
	for _, b := range an.RPO {
		nb := &nodeBox{b: b, isHeader: headers[b]}
		nb.lines = append(nb.lines, fmt.Sprintf("b%d", b.ID))
		for i, v := range b.Instrs {
			if i == maxLine {
				nb.lines = append(nb.lines, fmt.Sprintf("… %d more", len(b.Instrs)-maxLine))
				break
			}
			nb.lines = append(nb.lines, v.Format())
		}
		nb.lines = append(nb.lines, b.FormatTerm())
		wmax := 0
		for _, l := range nb.lines {
			if n := len([]rune(l)); n > wmax {
				wmax = n
			}
		}
		nb.w = float64(wmax)*charW + 2*padX
		nb.h = float64(len(nb.lines))*lineH + 2*padY
		boxes[b] = nb
	}
	// layer = longest path over forward edges
	back := func(from, to *Block) bool { return an.Index[to] <= an.Index[from] }
	for _, b := range an.RPO {
		l := 0
		for _, p := range b.Preds {
			if !back(p, b) && boxes[p].layer+1 > l {
				l = boxes[p].layer + 1
			}
		}
		boxes[b].layer = l
	}
	var layers [][]*nodeBox
	for _, b := range an.RPO {
		nb := boxes[b]
		for len(layers) <= nb.layer {
			layers = append(layers, nil)
		}
		layers[nb.layer] = append(layers[nb.layer], nb)
	}
	width := 0.0
	for _, l := range layers {
		w := 0.0
		for _, nb := range l {
			w += nb.w + hGap
		}
		if w > width {
			width = w
		}
	}
	y := 20.0
	for _, l := range layers {
		rowW := 0.0
		rowH := 0.0
		for _, nb := range l {
			rowW += nb.w + hGap
			if nb.h > rowH {
				rowH = nb.h
			}
		}
		x := (width-rowW)/2 + hGap/2 + 30
		for _, nb := range l {
			nb.x, nb.y = x, y
			x += nb.w + hGap
		}
		y += rowH + vGap
	}
	total := width + 90
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="cfg" viewBox="0 0 %.0f %.0f" width="%.0f" role="img" aria-label="control-flow graph of %s">`, total, y, total, html.EscapeString(f.Name))
	sb.WriteString(`<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>`)
	// edges first
	for _, b := range an.RPO {
		src := boxes[b]
		for i, s := range b.Succs {
			dst := boxes[s]
			label := ""
			if b.Kind == KBr {
				label = []string{"T", "F"}[i]
			}
			x1 := src.x + src.w*(0.5+0.18*float64(i)*float64(len(b.Succs)-1)-0.09*float64(len(b.Succs)-1))
			y1 := src.y + src.h
			x2, y2 := dst.x+dst.w/2, dst.y
			cls := "edge"
			var path string
			if back(b, s) {
				cls = "edge back"
				lx := minf(src.x, dst.x) - 22 - float64(an.Index[b]%4)*5
				path = fmt.Sprintf("M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f", x1, y1, x1, y1+24, lx, y1+24, lx, (y1+y2)/2)
				path += fmt.Sprintf(" S%.1f,%.1f %.1f,%.1f", lx, y2-26, x2, y2)
			} else {
				dy := (y2 - y1) / 2
				if dy < 14 {
					dy = 14
				}
				path = fmt.Sprintf("M%.1f,%.1f C%.1f,%.1f %.1f,%.1f %.1f,%.1f", x1, y1, x1, y1+dy, x2, y2-dy, x2, y2)
			}
			fmt.Fprintf(&sb, `<path d="%s" class="%s" marker-end="url(#arr)"/>`, path, cls)
			if label != "" {
				fmt.Fprintf(&sb, `<text x="%.1f" y="%.1f" class="elabel">%s</text>`, x1+(map[bool]float64{true: -12, false: 6}[i == 0]), y1+13, label)
			}
		}
	}
	for _, b := range an.RPO {
		nb := boxes[b]
		cls := "blk"
		if nb.isHeader {
			cls += " hdr"
		}
		fmt.Fprintf(&sb, `<g class="%s"><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="6"/>`, cls, nb.x, nb.y, nb.w, nb.h)
		for i, l := range nb.lines {
			c := "ins"
			switch {
			case i == 0:
				c = "bname"
			case i == len(nb.lines)-1:
				c = "term"
			case strings.Contains(l, "= phi"):
				c = "ins phi"
			}
			fmt.Fprintf(&sb, `<text x="%.1f" y="%.1f" class="%s">%s</text>`, nb.x+padX, nb.y+padY+float64(i+1)*lineH-4, c, html.EscapeString(l))
		}
		sb.WriteString(`</g>`)
	}
	sb.WriteString(`</svg>`)
	return sb.String()
}

func minf(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

// ---- live-interval chart ----

// IntervalChart draws the linear-scan live intervals of f at K registers.
func IntervalChart(f *Func, k int) (string, AllocStats) {
	mf := Select(f)
	t := NewTarget(k)
	_, st, ivs := linearScan(mf, t)
	lv := computeLiveness(mf)
	_ = lv
	// call positions
	var calls []int
	pos := 0
	for _, b := range mf.Blocks {
		for i := range b.Instrs {
			if b.Instrs[i].Op == MCall {
				calls = append(calls, 2*pos)
			}
			pos++
		}
	}
	sort.Slice(ivs, func(i, j int) bool {
		if ivs[i].Start != ivs[j].Start {
			return ivs[i].Start < ivs[j].Start
		}
		return ivs[i].V < ivs[j].V
	})
	maxPos := 2*pos + 2
	const rowH, left, right = 14.0, 56.0, 20.0
	w := 900.0
	scale := (w - left - right) / float64(maxPos)
	h := float64(len(ivs))*rowH + 46
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="ivl" viewBox="0 0 %.0f %.0f" width="100%%" role="img" aria-label="live intervals of %s with %d registers">`, w, h, html.EscapeString(f.Name), k)
	sb.WriteString(`<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="hatchbg"/><line x1="0" y1="0" x2="0" y2="6" class="hatchln"/></pattern></defs>`)
	for _, c := range calls {
		x := left + float64(c)*scale
		fmt.Fprintf(&sb, `<line x1="%.1f" y1="18" x2="%.1f" y2="%.1f" class="callline"/>`, x, x, h-8)
	}
	if len(calls) > 0 {
		fmt.Fprintf(&sb, `<text x="%.1f" y="12" class="axis">call sites</text>`, left)
	}
	for i, iv := range ivs {
		y := 22 + float64(i)*rowH
		x1 := left + float64(iv.Start)*scale
		x2 := left + float64(iv.End)*scale
		if x2-x1 < 2 {
			x2 = x1 + 2
		}
		fill := "url(#hatch)"
		title := fmt.Sprintf("%%%d  [%d,%d]  spilled to [fp+%d]", iv.V, iv.Start, iv.End, iv.Slot)
		cls := "spill"
		if iv.Reg >= 0 {
			fill = ""
			cls = fmt.Sprintf("r r%d", iv.Reg%12)
			title = fmt.Sprintf("%%%d  [%d,%d]  r%d", iv.V, iv.Start, iv.End, iv.Reg)
		}
		if iv.Crosses {
			title += "  (live across a call)"
		}
		attr := ""
		if fill != "" {
			attr = fmt.Sprintf(` fill="%s"`, fill)
		}
		fmt.Fprintf(&sb, `<g><title>%s</title><rect x="%.1f" y="%.1f" width="%.1f" height="%.0f" rx="3" class="%s"%s/>`, html.EscapeString(title), x1, y, x2-x1, rowH-4, cls, attr)
		fmt.Fprintf(&sb, `<text x="%.1f" y="%.1f" class="axis" text-anchor="end">%%%d</text>`, left-6, y+rowH-6, iv.V)
		if iv.Crosses {
			fmt.Fprintf(&sb, `<circle cx="%.1f" cy="%.1f" r="2.2" class="xmark"/>`, x2+5, y+(rowH-4)/2)
		}
		sb.WriteString(`</g>`)
	}
	sb.WriteString(`</svg>`)
	return sb.String(), st
}

// ---- the report ----

type matrixRow struct {
	K                   int
	Alg                 Alg
	Instrs, Cycles, Mem int64
	Spilled, Static     int
	OK                  bool
}

// Report renders a self-contained HTML page describing every stage of compiling src.
func Report(name, src string, cfg Config) (string, error) {
	ast, err := Parse(src)
	if err != nil {
		return "", err
	}
	comp, err := CompileAST(ast, cfg)
	if err != nil {
		return "", err
	}
	oracle := RunAST(ast, 300_000_000)
	if oracle.Resource() {
		return "", fmt.Errorf("report needs a program that finishes (oracle: %s)", oracle.Trap)
	}
	fuel := oracle.Steps*60 + 10_000_000
	ir0 := RunIR(comp.SSA, fuel)
	ir1 := RunIR(comp.Opt, fuel)
	var rows []matrixRow
	for _, k := range []int{2, 3, 4, 6, 8, 12, 16} {
		for _, alg := range []Alg{LinearScan, GraphColor} {
			c2 := cfg
			c2.Regs, c2.Alg = k, alg
			cm, err := CompileAST(ast, c2)
			if err != nil {
				return "", err
			}
			o, st := RunProgram(cm.Prog, fuel)
			r := matrixRow{K: k, Alg: alg, Instrs: st.Instrs, Cycles: st.Cycles, Mem: st.SpillLoads + st.SpillStores, OK: o.Same(oracle)}
			for _, f := range cm.Prog.Funcs {
				r.Spilled += cm.Prog.Stats[f.Name].Spilled
				r.Static += f.StaticSize()
			}
			rows = append(rows, r)
		}
	}
	var sb strings.Builder
	esc := html.EscapeString
	sb.WriteString(reportHead(name))
	fmt.Fprintf(&sb, `<header><h1>Sable <span>compilation report</span></h1><p class="sub">%s &middot; -O%d &middot; %d registers &middot; %v</p></header><main>`,
		esc(name), cfg.OptLevel, cfg.Regs, cfg.Alg)

	// summary cards
	staticBefore, staticAfter := 0, 0
	for _, f := range comp.SSA.Funcs {
		staticBefore += f.NumInstrs()
	}
	for _, f := range comp.Opt.Funcs {
		staticAfter += f.NumInstrs()
	}
	sb.WriteString(`<section class="cards">`)
	card := func(label, value, note string) {
		fmt.Fprintf(&sb, `<div class="card"><div class="cl">%s</div><div class="cv">%s</div><div class="cn">%s</div></div>`, esc(label), esc(value), esc(note))
	}
	card("program result", oracle.String(), fmt.Sprintf("%d AST steps · oracle", oracle.Steps))
	card("static IR", fmt.Sprintf("%d → %d", staticBefore, staticAfter), "instructions, SSA → optimised")
	card("dynamic IR", fmt.Sprintf("%d → %d", ir0.Steps, ir1.Steps), fmt.Sprintf("%.0f%% of unoptimised work", 100*float64(ir1.Steps)/float64(max64(ir0.Steps, 1))))
	okAll := true
	for _, r := range rows {
		okAll = okAll && r.OK
	}
	verdict := "all 14 configurations agree"
	if !okAll {
		verdict = "MISMATCH — see matrix"
	}
	card("machine code", verdict, "linear-scan & graph-colour × K = 2…16")
	sb.WriteString(`</section>`)

	// source
	sb.WriteString(`<section><h2>Source</h2><pre class="src">`)
	for i, l := range strings.Split(strings.TrimRight(src, "\n"), "\n") {
		fmt.Fprintf(&sb, `<span class="ln">%3d</span> %s`+"\n", i+1, esc(l))
	}
	sb.WriteString(`</pre></section>`)

	// passes
	sb.WriteString(`<section><h2>Optimiser pipeline</h2><p class="note">Every pass is followed by the SSA verifier (dominance, phi arity, single definition).</p><div class="scroll"><table><thead><tr><th>pass</th><th>runs</th><th>changed</th><th>Δ instructions</th></tr></thead><tbody>`)
	type agg struct{ runs, ch, d int }
	order := []string{}
	ag := map[string]*agg{}
	for _, r := range comp.Passes.Rows {
		a := ag[r.Pass]
		if a == nil {
			a = &agg{}
			ag[r.Pass] = a
			order = append(order, r.Pass)
		}
		a.runs++
		if r.Changed {
			a.ch++
		}
		a.d += r.After - r.Before
	}
	for _, n := range order {
		a := ag[n]
		fmt.Fprintf(&sb, `<tr><td><code>%s</code></td><td class="num">%d</td><td class="num">%d</td><td class="num">%+d</td></tr>`, n, a.runs, a.ch, a.d)
	}
	sb.WriteString(`</tbody></table></div></section>`)

	// CFGs
	sb.WriteString(`<section><h2>Control-flow graphs</h2><p class="note">Loop headers are outlined; dashed edges are back edges; phi nodes are highlighted.</p>`)
	for _, f := range comp.SSA.Funcs {
		after := comp.Opt.ByName[f.Name]
		fmt.Fprintf(&sb, `<details><summary><code>%s</code> — SSA before optimisation (%d instrs, %d blocks)</summary><div class="scroll">%s</div></details>`, esc(f.Name), f.NumInstrs(), len(f.Blocks), CFGSVG(f))
		if after != nil {
			fmt.Fprintf(&sb, `<details open><summary><code>%s</code> — after optimisation (%d instrs, %d blocks)</summary><div class="scroll">%s</div></details>`, esc(f.Name), after.NumInstrs(), len(after.Blocks), CFGSVG(after))
		} else {
			fmt.Fprintf(&sb, `<p class="note"><code>%s</code> was inlined into its callers and removed.</p>`, esc(f.Name))
		}
	}
	sb.WriteString(`</section>`)

	// allocation matrix
	sb.WriteString(`<section><h2>Register allocation</h2><p class="note">Dynamic counts from the register VM. “mem” = executed loads + stores (spills and callee-saved traffic). Cycles use a fixed cost model (mul 3, div 12, memory 4, call 5).</p>`)
	sb.WriteString(cyclesChart(rows))
	sb.WriteString(`<div class="scroll"><table><thead><tr><th>K</th><th>allocator</th><th>instrs</th><th>cycles</th><th>mem ops</th><th>spilled values</th><th>static size</th><th>result</th></tr></thead><tbody>`)
	for _, r := range rows {
		res := "✓"
		if !r.OK {
			res = "✗ MISMATCH"
		}
		fmt.Fprintf(&sb, `<tr><td class="num">%d</td><td>%v</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td><td class="num">%d</td><td>%s</td></tr>`,
			r.K, r.Alg, r.Instrs, r.Cycles, r.Mem, r.Spilled, r.Static, res)
	}
	sb.WriteString(`</tbody></table></div></section>`)

	// intervals + machine code
	sb.WriteString(`<section><h2>Live intervals &amp; machine code</h2>`)
	for _, f := range comp.Opt.Funcs {
		chart, st := IntervalChart(f, cfg.Regs)
		fmt.Fprintf(&sb, `<details><summary><code>%s</code> — linear-scan intervals at K=%d (%d spilled)</summary><p class="note">Each bar is one virtual register's live interval; colour = assigned register, hatched = spilled to the stack frame, ● = live across a call (forced into a callee-saved register or spilled).</p><div class="scroll">%s</div></details>`, esc(f.Name), cfg.Regs, st.Spilled, chart)
	}
	for _, f := range comp.Prog.Funcs {
		fmt.Fprintf(&sb, `<details><summary><code>%s</code> — machine code (%v, K=%d, %d instructions)</summary><pre class="asm">%s</pre></details>`, esc(f.Name), cfg.Alg, cfg.Regs, f.StaticSize(), esc(f.String()))
	}
	sb.WriteString(`</section></main><footer>Generated by <code>sable report</code> — SSA construction, SCCP, GVN, LICM, inlining, linear-scan and graph-colouring allocation, all from scratch.</footer></body></html>`)
	return sb.String(), nil
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

func cyclesChart(rows []matrixRow) string {
	const w, h, l, r, t, b = 760.0, 260.0, 64.0, 24.0, 16.0, 44.0
	var ks []int
	seen := map[int]bool{}
	var maxC int64
	for _, row := range rows {
		if !seen[row.K] {
			seen[row.K] = true
			ks = append(ks, row.K)
		}
		if row.Cycles > maxC {
			maxC = row.Cycles
		}
	}
	if maxC == 0 {
		return ""
	}
	gw := (w - l - r) / float64(len(ks))
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="chart" viewBox="0 0 %.0f %.0f" role="img" aria-label="cycles by register count and allocator">`, w, h)
	for i := 0; i <= 4; i++ {
		y := t + (h-t-b)*float64(i)/4
		v := float64(maxC) * float64(4-i) / 4
		fmt.Fprintf(&sb, `<line x1="%.0f" x2="%.0f" y1="%.1f" y2="%.1f" class="grid"/><text x="%.0f" y="%.1f" class="axis" text-anchor="end">%s</text>`, l, w-r, y, y, l-8, y+4, short(v))
	}
	for gi, k := range ks {
		x0 := l + gw*float64(gi)
		for ai, alg := range []Alg{LinearScan, GraphColor} {
			for _, row := range rows {
				if row.K != k || row.Alg != alg {
					continue
				}
				bh := (h - t - b) * float64(row.Cycles) / float64(maxC)
				bx := x0 + gw*0.16 + float64(ai)*gw*0.34
				cls := []string{"bar ls", "bar gc"}[ai]
				fmt.Fprintf(&sb, `<g><title>K=%d %v: %d cycles</title><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" class="%s"/></g>`, k, alg, row.Cycles, bx, h-b-bh, gw*0.32, bh, cls)
			}
		}
		fmt.Fprintf(&sb, `<text x="%.1f" y="%.0f" class="axis" text-anchor="middle">K=%d</text>`, x0+gw/2, h-b+18, k)
	}
	fmt.Fprintf(&sb, `<rect x="%.0f" y="%.0f" width="10" height="10" class="bar ls"/><text x="%.0f" y="%.0f" class="axis">linear scan</text><rect x="%.0f" y="%.0f" width="10" height="10" class="bar gc"/><text x="%.0f" y="%.0f" class="axis">graph colouring</text>`,
		l, h-12, l+14, h-3, l+120, h-12, l+134, h-3)
	sb.WriteString(`</svg>`)
	return sb.String()
}

func short(v float64) string {
	switch {
	case v >= 1e6:
		return fmt.Sprintf("%.1fM", v/1e6)
	case v >= 1e3:
		return fmt.Sprintf("%.0fk", v/1e3)
	}
	return fmt.Sprintf("%.0f", v)
}

func reportHead(name string) string {
	return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sable report — ` + html.EscapeString(name) + `</title><style>` + reportCSS + `</style></head><body>`
}
