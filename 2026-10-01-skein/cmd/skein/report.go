package main

import (
	"flag"
	"fmt"
	"html"
	"math"
	"math/rand"
	"os"
	"sort"
	"strings"
	"time"

	"skein/sketch"
)

// ---- tiny SVG chart renderer ---------------------------------------------

type point struct{ x, y float64 }

type series struct {
	name   string
	pts    []point
	dashed bool
	marks  bool // draw markers
	noLine bool
}

type chart struct {
	title, sub, xlabel, ylabel string
	logx, logy                 bool
	series                     []series
	yPercent                   bool
}

const (
	cw, chh                = 560.0, 340.0
	padL, padR, padT, padB = 62.0, 16.0, 14.0, 46.0
)

func niceLinTicks(lo, hi float64) []float64 {
	if hi <= lo {
		hi = lo + 1
	}
	span := hi - lo
	step := math.Pow(10, math.Floor(math.Log10(span/5)))
	for _, m := range []float64{1, 2, 5, 10} {
		if span/(step*m) <= 6 {
			step *= m
			break
		}
	}
	var t []float64
	for v := math.Ceil(lo/step) * step; v <= hi+step*1e-9; v += step {
		t = append(t, v)
	}
	return t
}

func fmtTick(v float64, pct bool) string {
	if pct {
		v *= 100
		switch {
		case v >= 10 || v == 0:
			return fmt.Sprintf("%.0f%%", v)
		case v >= 1:
			return fmt.Sprintf("%.1f%%", v)
		case v >= 0.1:
			return fmt.Sprintf("%.2f%%", v)
		}
		return fmt.Sprintf("%.3g%%", v)
	}
	switch {
	case v >= 1e6:
		return fmt.Sprintf("%.3gM", v/1e6)
	case v >= 1e3:
		return fmt.Sprintf("%.3gk", v/1e3)
	case v == math.Trunc(v):
		return fmt.Sprintf("%.0f", v)
	}
	return fmt.Sprintf("%.3g", v)
}

func (c chart) svg() string {
	tx := func(v float64) float64 {
		if c.logx {
			return math.Log10(v)
		}
		return v
	}
	ty := func(v float64) float64 {
		if c.logy {
			return math.Log10(v)
		}
		return v
	}
	x0, x1, y0, y1 := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
	for _, s := range c.series {
		for _, p := range s.pts {
			if (c.logx && p.x <= 0) || (c.logy && p.y <= 0) {
				continue
			}
			x0, x1 = math.Min(x0, tx(p.x)), math.Max(x1, tx(p.x))
			y0, y1 = math.Min(y0, ty(p.y)), math.Max(y1, ty(p.y))
		}
	}
	if math.IsInf(x0, 0) {
		return `<p class="empty">no data</p>`
	}
	if c.logy {
		y0, y1 = math.Floor(y0), math.Ceil(y1)
	} else {
		y0 = math.Min(y0, 0)
		y1 += (y1 - y0) * 0.05
	}
	if c.logx {
		x0, x1 = math.Floor(x0), math.Ceil(x1)
	} else if x1 == x0 {
		x1 = x0 + 1
	}
	if y1 == y0 {
		y1 = y0 + 1
	}
	px := func(v float64) float64 { return padL + (tx(v)-x0)/(x1-x0)*(cw-padL-padR) }
	py := func(v float64) float64 { return chh - padB - (ty(v)-y0)/(y1-y0)*(chh-padT-padB) }
	var b strings.Builder
	fmt.Fprintf(&b, `<svg viewBox="0 0 %g %g" role="img" aria-label="%s">`, cw, chh, html.EscapeString(c.title))
	// grid + ticks
	yt := niceLinTicks(y0, y1)
	if c.logy {
		yt = nil
		for e := y0; e <= y1; e++ {
			yt = append(yt, e)
		}
	}
	for _, v := range yt {
		val := v
		if c.logy {
			val = math.Pow(10, v)
		}
		y := chh - padB - (v-y0)/(y1-y0)*(chh-padT-padB)
		fmt.Fprintf(&b, `<line class="grid" x1="%g" x2="%g" y1="%.1f" y2="%.1f"/><text class="tick" x="%g" y="%.1f" text-anchor="end">%s</text>`, padL, cw-padR, y, y, padL-6, y+4, fmtTick(val, c.yPercent))
	}
	xt := niceLinTicks(x0, x1)
	if c.logx {
		xt = nil
		for e := x0; e <= x1; e++ {
			xt = append(xt, e)
		}
	}
	for _, v := range xt {
		val := v
		if c.logx {
			val = math.Pow(10, v)
		}
		x := padL + (v-x0)/(x1-x0)*(cw-padL-padR)
		fmt.Fprintf(&b, `<line class="grid v" x1="%.1f" x2="%.1f" y1="%g" y2="%g"/><text class="tick" x="%.1f" y="%g" text-anchor="middle">%s</text>`, x, x, padT, chh-padB, x, chh-padB+16, fmtTick(val, false))
	}
	fmt.Fprintf(&b, `<line class="axis" x1="%g" x2="%g" y1="%g" y2="%g"/>`, padL, cw-padR, chh-padB, chh-padB)
	fmt.Fprintf(&b, `<text class="lbl" x="%g" y="%g" text-anchor="middle">%s</text>`, (padL+cw-padR)/2, chh-8, html.EscapeString(c.xlabel))
	fmt.Fprintf(&b, `<text class="lbl" transform="translate(14 %g) rotate(-90)" text-anchor="middle">%s</text>`, (padT+chh-padB)/2, html.EscapeString(c.ylabel))
	for i, s := range c.series {
		var pts []point
		for _, p := range s.pts {
			if (c.logx && p.x <= 0) || (c.logy && p.y <= 0) {
				continue
			}
			pts = append(pts, p)
		}
		if len(pts) == 0 {
			continue
		}
		var d strings.Builder
		for j, p := range pts {
			op := "L"
			if j == 0 {
				op = "M"
			}
			fmt.Fprintf(&d, "%s%.1f %.1f ", op, px(p.x), py(p.y))
		}
		if !s.noLine {
			dash := ""
			if s.dashed {
				dash = ` stroke-dasharray="6 4"`
			}
			fmt.Fprintf(&b, `<path class="s s%d" d="%s" fill="none"%s/>`, i, d.String(), dash)
		}
		if s.marks || s.noLine {
			for _, p := range pts {
				fmt.Fprintf(&b, `<circle class="m m%d" cx="%.1f" cy="%.1f" r="3.4"><title>%s: (%s, %s)</title></circle>`, i, px(p.x), py(p.y), html.EscapeString(s.name), fmtTick(p.x, false), fmtTick(p.y, c.yPercent))
			}
		}
	}
	b.WriteString(`</svg>`)
	var leg strings.Builder
	for i, s := range c.series {
		fmt.Fprintf(&leg, `<span class="key"><i class="sw s%d%s"></i>%s</span>`, i, map[bool]string{true: " dash", false: ""}[s.dashed], html.EscapeString(s.name))
	}
	return fmt.Sprintf(`<figure><figcaption><h3>%s</h3><p>%s</p></figcaption>%s<div class="legend">%s</div></figure>`, html.EscapeString(c.title), c.sub, b.String(), leg.String())
}

// ---- experiments ------------------------------------------------------------

type zipfGen func() int

func newZipf(seed int64, s float64, n int) zipfGen {
	z := rand.NewZipf(rand.New(rand.NewSource(seed)), s, 1, uint64(n-1))
	return func() int { return int(z.Uint64()) }
}

func expHLL(trials, n int) chart {
	var meas, theory []point
	for p := 6; p <= 16; p++ {
		var se float64
		for t := 0; t < trials; t++ {
			h, _ := sketch.NewHLL(p)
			base := t * n * 3
			for i := 0; i < n; i++ {
				h.AddString(fmt.Sprintf("k%d", base+i))
			}
			e := (h.Estimate() - float64(n)) / float64(n)
			se += e * e
		}
		h, _ := sketch.NewHLL(p)
		meas = append(meas, point{float64(h.Bytes()), math.Sqrt(se / float64(trials))})
		theory = append(theory, point{float64(h.Bytes()), h.StdError()})
	}
	return chart{title: "HyperLogLog: error vs memory", sub: fmt.Sprintf("RMS relative error of the distinct-count estimate over %d runs of %s distinct keys. Dashed = theoretical 1.04/√m.", trials, human(float64(n))),
		xlabel: "memory (bytes)", ylabel: "relative error", logx: true, logy: true, yPercent: true,
		series: []series{{name: "measured", pts: meas, marks: true}, {name: "theory 1.04/√m", pts: theory, dashed: true}}}
}

func expCMS(events, keys int) chart {
	var meas, bound []point
	exact := map[string]int{}
	type ev struct{ k string }
	next := newZipf(5, 1.15, keys)
	evs := make([]string, events)
	for i := range evs {
		evs[i] = fmt.Sprintf("key%d", next())
		exact[evs[i]]++
	}
	for _, w := range []int{100, 200, 500, 1000, 2000, 5000, 10000} {
		c, _ := sketch.NewCMSDims(w, 4)
		for _, e := range evs {
			c.Add([]byte(e), 1)
		}
		var sum, worst float64
		for k, v := range exact {
			d := float64(c.Estimate([]byte(k))) - float64(v)
			sum += d
			worst = math.Max(worst, d)
		}
		meas = append(meas, point{float64(c.Bytes()), math.Max(sum/float64(len(exact))/float64(events), 1e-9)})
		_ = worst
		bound = append(bound, point{float64(c.Bytes()), c.Epsilon()})
	}
	return chart{title: "Count-Min: overcount vs memory", sub: fmt.Sprintf("Mean overcount per key as a fraction of stream length N=%s (Zipf, %s keys, depth 4). Dashed = ε = e/width bound.", human(float64(events)), human(float64(len(exact)))),
		xlabel: "memory (bytes)", ylabel: "mean overcount / N", logx: true, logy: true, yPercent: true,
		series: []series{{name: "measured (conservative update)", pts: meas, marks: true}, {name: "bound ε·N", pts: bound, dashed: true}}}
}

func expMembership(n int) chart {
	var bm, bt, ck []point
	for bpk := 4; bpk <= 16; bpk += 2 {
		m := uint64(bpk * n)
		k := uint64(math.Max(1, math.Round(float64(bpk)*math.Ln2)))
		b, _ := sketch.NewBloomRaw(m, k)
		for i := 0; i < n; i++ {
			b.Add([]byte(fmt.Sprintf("in%d", i)))
		}
		fp := 0
		const probes = 200000
		for i := 0; i < probes; i++ {
			if b.Contains([]byte(fmt.Sprintf("out%d", i))) {
				fp++
			}
		}
		bm = append(bm, point{float64(bpk), math.Max(float64(fp)/probes, 1e-6)})
		bt = append(bt, point{float64(bpk), math.Pow(0.6185, float64(bpk))})
	}
	// cuckoo at several loads (fixed 16-bit fingerprints)
	for _, load := range []float64{0.5, 0.7, 0.85, 0.95} {
		c, _ := sketch.NewCuckoo(int(float64(n) / load))
		target := int(load * float64(c.Capacity()))
		added := 0
		for i := 0; i < target; i++ {
			if c.Add([]byte(fmt.Sprintf("in%d", i))) != nil {
				break
			}
			added++
		}
		fp := 0
		const probes = 400000
		for i := 0; i < probes; i++ {
			if c.Contains([]byte(fmt.Sprintf("out%d", i))) {
				fp++
			}
		}
		ck = append(ck, point{float64(c.Bytes()*8) / float64(added), math.Max(float64(fp)/probes, 1e-6)})
	}
	sort.Slice(ck, func(i, j int) bool { return ck[i].x < ck[j].x })
	return chart{title: "Bloom vs cuckoo: false positives per bit", sub: fmt.Sprintf("%s items. Bloom at its optimal k; cuckoo (16-bit fingerprints) at loads 50–95%%. Cuckoo spends more bits but supports delete. Floor of the axis is 10⁻⁶ (no false positives observed).", human(float64(n))),
		xlabel: "bits per item", ylabel: "false-positive rate", logy: true, yPercent: true,
		series: []series{{name: "bloom measured", pts: bm, marks: true}, {name: "bloom theory 0.6185^(m/n)", pts: bt, dashed: true}, {name: "cuckoo measured", pts: ck, marks: true}}}
}

func expTDigest(n int) chart {
	r := rand.New(rand.NewSource(21))
	data := make([]float64, n)
	for i := range data {
		data[i] = math.Exp(r.NormFloat64() * 1.2)
	}
	sorted := append([]float64(nil), data...)
	sort.Float64s(sorted)
	qs := []float64{0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999}
	var ss []series
	for _, d := range []float64{20, 100, 500} {
		td, _ := sketch.NewTDigest(d)
		for _, v := range data {
			td.Add(v)
		}
		var pts []point
		for i, q := range qs {
			got, _ := td.Quantile(q)
			rank := float64(sort.SearchFloat64s(sorted, got)) / float64(n)
			pts = append(pts, point{float64(i), math.Max(math.Abs(rank-q), 1e-7)})
		}
		ss = append(ss, series{name: fmt.Sprintf("δ=%g (%d centroids, %s)", d, td.Centroids(), bytesStr(td.Bytes())), pts: pts, marks: true})
	}
	// relabel the categorical x axis by q index
	c := chart{title: "t-digest: rank error by quantile", sub: fmt.Sprintf("|true rank − q| on %s lognormal samples. Error shrinks toward both tails — that is the k₁ scale function at work. x = %s.", human(float64(n)), qLabels(qs)),
		xlabel: "quantile index", ylabel: "rank error", logy: true, yPercent: true, series: ss}
	return c
}

func qLabels(qs []float64) string {
	var s []string
	for i, q := range qs {
		s = append(s, fmt.Sprintf("%d=p%s", i, pct(q)))
	}
	return strings.Join(s, ", ")
}

func expSpaceSaving(events, keys int) chart {
	next := newZipf(9, 1.1, keys)
	evs := make([]string, events)
	exact := map[string]int{}
	for i := range evs {
		evs[i] = fmt.Sprintf("w%d", next())
		exact[evs[i]]++
	}
	type kv struct {
		k string
		v int
	}
	var all []kv
	for k, v := range exact {
		all = append(all, kv{k, v})
	}
	sort.Slice(all, func(i, j int) bool { return all[i].v > all[j].v || (all[i].v == all[j].v && all[i].k < all[j].k) })
	var r10, r50 []point
	for _, k := range []int{10, 20, 40, 80, 160, 320, 640} {
		s, _ := sketch.NewSpaceSaving(k)
		for _, e := range evs {
			s.Add(e, 1)
		}
		have := map[string]bool{}
		for _, e := range s.Top(-1) {
			have[e.Key] = true
		}
		rec := func(n int) float64 {
			h := 0
			for i := 0; i < n; i++ {
				if have[all[i].k] {
					h++
				}
			}
			return float64(h) / float64(n)
		}
		r10 = append(r10, point{float64(k), rec(10)})
		if k >= 50 {
			r50 = append(r50, point{float64(k), rec(50)})
		}
	}
	return chart{title: "SpaceSaving: top-K recall vs counters", sub: fmt.Sprintf("Fraction of the true top-10 / top-50 retained, %s events over %s keys (Zipf s=1.1).", human(float64(events)), human(float64(len(exact)))),
		xlabel: "counters k", ylabel: "recall", logx: true, yPercent: true,
		series: []series{{name: "top-10 recall", pts: r10, marks: true}, {name: "top-50 recall", pts: r50, marks: true}}}
}

func expMinHash() chart {
	r := rand.New(rand.NewSource(33))
	var s64, s256, diag []point
	for trial := 0; trial < 40; trial++ {
		ov := r.Intn(201)
		var a, b []string
		for i := 0; i < 200; i++ {
			a = append(a, fmt.Sprintf("a%d-%d", trial, i))
		}
		b = append(b, a[:ov]...)
		for i := ov; i < 200; i++ {
			b = append(b, fmt.Sprintf("b%d-%d", trial, i))
		}
		j := sketch.ExactJaccard(a, b)
		for _, k := range []int{64, 256} {
			ma, _ := sketch.NewMinHash(k)
			mb, _ := sketch.NewMinHash(k)
			for _, x := range a {
				ma.AddString(x)
			}
			for _, x := range b {
				mb.AddString(x)
			}
			e, _ := ma.Jaccard(mb)
			if k == 64 {
				s64 = append(s64, point{j, e})
			} else {
				s256 = append(s256, point{j, e})
			}
		}
	}
	diag = []point{{0, 0}, {1, 1}}
	sort.Slice(diag, func(i, j int) bool { return diag[i].x < diag[j].x })
	return chart{title: "MinHash: estimated vs exact Jaccard", sub: "40 random set pairs of 200 items each; points on the diagonal are perfect. Larger signatures hug the line (σ ≈ √(J(1−J)/k)).",
		xlabel: "exact Jaccard", ylabel: "estimated Jaccard",
		series: []series{{name: "k=64 (512 B)", pts: s64, noLine: true}, {name: "k=256 (2 KiB)", pts: s256, noLine: true}, {name: "y = x", pts: diag, dashed: true}}}
}

// ---- page ----------------------------------------------------------------------

const pageCSS = `
:root{--bg:#f7f6f2;--card:#fff;--ink:#1c1b19;--mute:#6b675f;--line:#e4e1d8;--grid:#ece9e0;
--c0:#2a6fdb;--c1:#d9602b;--c2:#1f9d7a;--c3:#8a5cd6}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1d1c1a;--ink:#ece9e1;--mute:#9a958a;--line:#322f2a;--grid:#2a2824;
--c0:#6ea2ff;--c1:#ff9561;--c2:#4fd1a8;--c3:#b99aff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:40px 20px 64px}
h1{font-size:34px;letter-spacing:-.02em;margin:0 0 4px}h1 span{color:var(--c0)}
.lede{color:var(--mute);max-width:70ch;margin:0 0 28px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:28px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile b{display:block;font-size:26px;letter-spacing:-.02em}.tile small{color:var(--mute)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px 12px}
figcaption h3{margin:0;font-size:17px}figcaption p{margin:2px 0 10px;color:var(--mute);font-size:13px}
svg{width:100%;height:auto;display:block}
.grid{}svg .grid{stroke:var(--grid);stroke-width:1}svg .axis{stroke:var(--mute)}
.tick{fill:var(--mute);font-size:11px}.lbl{fill:var(--mute);font-size:12px}
.s{stroke-width:2.2}.s0{stroke:var(--c0)}.s1{stroke:var(--c1)}.s2{stroke:var(--c2)}.s3{stroke:var(--c3)}
.m0{fill:var(--c0)}.m1{fill:var(--c1)}.m2{fill:var(--c2)}.m3{fill:var(--c3)}
.m{fill-opacity:.85;stroke:var(--card);stroke-width:1}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--mute);margin-top:6px}
.key{display:inline-flex;align-items:center;gap:6px}.sw{width:16px;height:0;border-top:3px solid;display:inline-block}
.sw.s0{border-color:var(--c0)}.sw.s1{border-color:var(--c1)}.sw.s2{border-color:var(--c2)}.sw.s3{border-color:var(--c3)}.sw.dash{border-top-style:dashed}
footer{margin-top:28px;color:var(--mute);font-size:12.5px}
`

func cmdReport(args []string) error {
	fs := flag.NewFlagSet("report", flag.ContinueOnError)
	out := fs.String("o", "skein-report.html", "output HTML file")
	quick := fs.Bool("quick", false, "smaller workloads (≈1s) for a rough picture")
	if err := parseFlags(fs, args); err != nil {
		return err
	}
	trials, hn, ev, keys, bn, tn := 12, 30000, 300000, 40000, 40000, 300000
	if *quick {
		trials, hn, ev, keys, bn, tn = 4, 8000, 60000, 10000, 10000, 60000
	}
	start := time.Now()
	charts := []chart{expHLL(trials, hn), expCMS(ev, keys), expMembership(bn), expTDigest(tn), expSpaceSaving(ev, keys), expMinHash()}
	var b strings.Builder
	b.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Skein Accuracy Report</title><style>` + pageCSS + `</style></head><body><main>`)
	b.WriteString(`<h1>Skein <span>accuracy report</span></h1><p class="lede">Every curve below was measured just now against exact ground truth, by running the real sketches in this repository. Dashed lines are the published theoretical bounds or ideal curves — measured results should track them (single-run noise aside).</p>`)
	h14, _ := sketch.NewHLL(14)
	tiles := [][2]string{
		{bytesStr(h14.Bytes()), "HyperLogLog p=14 counts billions of distinct keys at ±" + fmt.Sprintf("%.2f%%", 100*h14.StdError())},
		{"~10 bits/key", "Bloom filter for a 1% false-positive rate"},
		{"~1 KiB", "t-digest (δ=100) summarising any number of values"},
		{"merge = free", "HLL / Bloom / t-digest / SpaceSaving shards combine without re-reading data"},
	}
	b.WriteString(`<div class="tiles">`)
	for _, t := range tiles {
		fmt.Fprintf(&b, `<div class="tile"><b>%s</b><small>%s</small></div>`, html.EscapeString(t[0]), html.EscapeString(t[1]))
	}
	b.WriteString(`</div><div class="grid">`)
	for _, c := range charts {
		b.WriteString(c.svg())
	}
	fmt.Fprintf(&b, `</div><footer>Generated by <code>skein report</code>%s in %.1fs. Deterministic seeds; rerun for identical numbers.</footer></main></body></html>`, map[bool]string{true: " (quick mode)", false: ""}[*quick], time.Since(start).Seconds())
	if err := os.WriteFile(*out, []byte(b.String()), 0o644); err != nil {
		return err
	}
	fmt.Printf("wrote %s (%d charts, %.1fs)\n", *out, len(charts), time.Since(start).Seconds())
	return nil
}
