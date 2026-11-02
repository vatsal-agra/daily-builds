// Package report renders a tracker run as a self-contained HTML page with inline SVG.
package report

import (
	"fmt"
	"html"
	"math"
	"sort"
	"strings"

	"kestrel/tracker"
)

var palette = []string{"#2a7de1", "#e1572a", "#1f9d6b", "#a24ad8", "#d9a400", "#0e9fb5", "#d6336c", "#6c757d"}

type view struct{ minX, maxX, minY, maxY, size, pad float64 }

func (v view) x(x float64) float64 { return v.pad + (x-v.minX)/(v.maxX-v.minX)*(v.size-2*v.pad) }
func (v view) y(y float64) float64 {
	return v.size - v.pad - (y-v.minY)/(v.maxY-v.minY)*(v.size-2*v.pad)
}
func (v view) s(d float64) float64 { return d / (v.maxX - v.minX) * (v.size - 2*v.pad) }

// HTML builds the report. If smoothed is true, confirmed tracks are drawn RTS-smoothed where possible.
func HTML(r *tracker.Run, title string, smoothed bool) (string, error) {
	if r == nil || len(r.Frames) == 0 {
		return "", fmt.Errorf("report: empty run")
	}
	// ---- extent
	minX, maxX, minY, maxY := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
	grow := func(x, y float64) {
		minX, maxX = math.Min(minX, x), math.Max(maxX, x)
		minY, maxY = math.Min(minY, y), math.Max(maxY, y)
	}
	for _, f := range r.Frames {
		for _, g := range f.Truth {
			if g.InCoverage {
				grow(g.X, g.Y)
			}
		}
	}
	if math.IsInf(minX, 1) { // no visible targets: fall back to the radar's neighbourhood
		grow(r.Scenario.Radar.X-1000, r.Scenario.Radar.Y-1000)
		grow(r.Scenario.Radar.X+1000, r.Scenario.Radar.Y+1000)
	}
	span := math.Max(maxX-minX, maxY-minY)
	if span < 1 {
		span = 1000
	}
	cx, cy := (minX+maxX)/2, (minY+maxY)/2
	span *= 1.12
	v := view{cx - span/2, cx + span/2, cy - span/2, cy + span/2, 720, 18}

	var b strings.Builder
	w := func(f string, a ...any) { fmt.Fprintf(&b, f, a...) }
	s := r.Score
	w(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202b;--mute:#667385;--line:#dfe4ea;--grid:#e8ecf1;--clutter:#9aa6b4;--truth:#16202b;--accent:#2a7de1}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#10151b;--card:#18202a;--ink:#e6ebf1;--mute:#93a1b3;--line:#2a3441;--grid:#222c38;--clutter:#5d6b7c;--truth:#e6ebf1;--accent:#6aa8ff}}
:root[data-theme=dark]{--bg:#10151b;--card:#18202a;--ink:#e6ebf1;--mute:#93a1b3;--line:#2a3441;--grid:#222c38;--clutter:#5d6b7c;--truth:#e6ebf1;--accent:#6aa8ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--mute);margin:0 0 20px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}.card b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.card span{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:16px}.panel h2{font-size:15px;margin:0 0 8px}
svg{width:100%%;height:auto;display:block}.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;color:var(--mute);font-size:13px}
.legend i{display:inline-block;width:18px;height:3px;vertical-align:middle;margin-right:6px;border-radius:2px}
table{width:100%%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}th{color:var(--mute);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.tablewrap{overflow-x:auto}
</style></head><body><main>
<h1>%s</h1><p class="sub">%s</p>
`, html.EscapeString(title), html.EscapeString(title), html.EscapeString(r.Scenario.Desc))
	w(`<div class="cards">
<div class="card"><span>Mean OSPA</span><b>%.0f m</b></div>
<div class="card"><span>Position RMSE</span><b>%.0f m</b></div>
<div class="card"><span>Coverage</span><b>%.1f%%</b></div>
<div class="card"><span>ID switches</span><b>%d</b></div>
<div class="card"><span>False-track scans</span><b>%d</b></div>
<div class="card"><span>Tracks / targets</span><b>%d / %d</b></div></div>
`, s.MeanOSPA, s.PosRMSE, 100*s.Coverage, s.IDSwitches, s.FalseTrackScans, s.Tracks, len(r.Scenario.Targets))

	// ---- PPI
	w(`<div class="panel"><h2>Plan view — truth, detections and confirmed tracks</h2><svg viewBox="0 0 %.0f %.0f" role="img" aria-label="Plan view of targets and tracks">`, v.size, v.size)
	w(`<rect width="%.0f" height="%.0f" fill="none"/>`, v.size, v.size)
	step := niceStep(span / 5)
	for g := math.Ceil(v.minX/step) * step; g <= v.maxX; g += step {
		w(`<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--grid)"/>`, v.x(g), 0.0, v.x(g), v.size)
	}
	for g := math.Ceil(v.minY/step) * step; g <= v.maxY; g += step {
		w(`<line x1="0" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--grid)"/>`, v.y(g), v.size, v.y(g))
	}
	rad := r.Scenario.Radar
	for _, rr := range []float64{5000, 10000, 15000, 20000} {
		if rr > rad.RMax {
			continue
		}
		w(`<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="var(--grid)" stroke-dasharray="4 6"/>`, v.x(rad.X), v.y(rad.Y), v.s(rr))
	}
	for _, f := range r.Frames {
		for _, d := range f.Dets {
			if d.Source != 0 {
				continue
			}
			px := rad.X + d.Z.D[0]*math.Cos(d.Z.D[1])
			py := rad.Y + d.Z.D[0]*math.Sin(d.Z.D[1])
			if px < v.minX || px > v.maxX || py < v.minY || py > v.maxY {
				continue
			}
			w(`<circle cx="%.1f" cy="%.1f" r="1.6" fill="var(--clutter)" opacity=".55"/>`, v.x(px), v.y(py))
		}
	}
	// truth paths
	paths := map[int][]string{}
	for _, f := range r.Frames {
		for _, g := range f.Truth {
			paths[g.ID] = append(paths[g.ID], fmt.Sprintf("%.1f,%.1f", v.x(g.X), v.y(g.Y)))
		}
	}
	ids := make([]int, 0, len(paths))
	for id := range paths {
		ids = append(ids, id)
	}
	sort.Ints(ids)
	for _, id := range ids {
		w(`<polyline points="%s" fill="none" stroke="var(--truth)" stroke-width="1.2" stroke-dasharray="3 4" opacity=".7"/>`, strings.Join(paths[id], " "))
	}
	// tracks
	all := r.Tracker.AllTracks()
	sort.Slice(all, func(i, j int) bool { return all[i].ID < all[j].ID })
	type row struct {
		id           int
		born, last   float64
		hits         int
		status, note string
		col          string
	}
	var rows []row
	for _, t := range all {
		if t.Hits < 3 || t.ConfirmScore == 0 && t.Status != tracker.Confirmed {
			continue
		}
		pts := t.History
		note := t.DeathReason
		if smoothed {
			if sp, err := t.Smoothed(); err == nil {
				pts = sp
			} else if note == "" {
				note = "unsmoothed"
			}
		}
		if len(pts) == 0 {
			continue
		}
		col := palette[t.ID%len(palette)]
		var sb []string
		for _, p := range pts {
			sb = append(sb, fmt.Sprintf("%.1f,%.1f", v.x(p.X), v.y(p.Y)))
		}
		w(`<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2" stroke-linejoin="round" opacity=".92"/>`, strings.Join(sb, " "), col)
		last := t.History[len(t.History)-1]
		if t.Status == tracker.Confirmed {
			if rx, ry, ang, ok := ellipse(last.PXX, last.PXY, last.PYY, 5.99); ok {
				w(`<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" transform="rotate(%.1f %.1f %.1f)" fill="%s" fill-opacity=".18" stroke="%s"/>`,
					v.x(last.X), v.y(last.Y), math.Max(v.s(rx), 3), math.Max(v.s(ry), 3), -ang, v.x(last.X), v.y(last.Y), col, col)
			}
		}
		w(`<text x="%.1f" y="%.1f" font-size="12" fill="%s" font-weight="600">#%d</text>`, v.x(last.X)+7, v.y(last.Y)-7, col, t.ID)
		rows = append(rows, row{t.ID, t.Born, last.T, t.Hits, t.Status.String(), note, col})
	}
	if rad.X > v.minX && rad.X < v.maxX && rad.Y > v.minY && rad.Y < v.maxY {
		w(`<circle cx="%.1f" cy="%.1f" r="5" fill="var(--accent)"/><text x="%.1f" y="%.1f" font-size="12" fill="var(--mute)">radar</text>`, v.x(rad.X), v.y(rad.Y), v.x(rad.X)+8, v.y(rad.Y)+14)
	}
	w(`</svg><div class="legend"><span><i style="background:var(--truth)"></i>truth (dashed)</span><span><i style="background:var(--clutter);height:6px;width:6px;border-radius:50%%"></i>clutter</span><span><i style="background:#2a7de1"></i>confirmed track%s</span><span>shaded ellipse = 95%% position uncertainty at last scan</span></div></div>`,
		map[bool]string{true: " (RTS-smoothed)", false: ""}[smoothed])

	// ---- OSPA chart
	w(`<div class="panel"><h2>OSPA distance per scan (c = 1000 m)</h2>%s</div>`, lineChart(r.OSPA, r.Frames[0].T, r.Frames[len(r.Frames)-1].T))

	// ---- table
	w(`<div class="panel"><h2>Confirmed tracks</h2><div class="tablewrap"><table><tr><th>Track</th><th>Status</th><th>Born (s)</th><th>Last (s)</th><th>Hits</th><th>Note</th></tr>`)
	for _, rw := range rows {
		w(`<tr><td><span style="color:%s;font-weight:700">#%d</span></td><td>%s</td><td>%.0f</td><td>%.0f</td><td>%d</td><td>%s</td></tr>`, rw.col, rw.id, rw.status, rw.born, rw.last, rw.hits, html.EscapeString(rw.note))
	}
	w(`</table></div></div></main></body></html>`)
	return b.String(), nil
}

func niceStep(x float64) float64 {
	p := math.Pow(10, math.Floor(math.Log10(x)))
	for _, m := range []float64{1, 2, 5, 10} {
		if m*p >= x {
			return m * p
		}
	}
	return 10 * p
}

// ellipse returns the semi-axes and rotation (degrees, CCW) of the covariance ellipse with chi² level k.
func ellipse(a, b, c, k float64) (rx, ry, deg float64, ok bool) {
	tr, det := a+c, a*c-b*b
	disc := math.Sqrt(math.Max(tr*tr/4-det, 0))
	l1, l2 := tr/2+disc, tr/2-disc
	if l1 <= 0 || l2 < 0 || math.IsNaN(l1) {
		return 0, 0, 0, false
	}
	return math.Sqrt(k * l1), math.Sqrt(k * l2), 0.5 * math.Atan2(2*b, a-c) * 180 / math.Pi, true
}

func lineChart(vals []float64, t0, t1 float64) string {
	const W, H, l, r, t, bt = 720.0, 220.0, 44.0, 10.0, 10.0, 26.0
	maxV := 1.0
	for _, v := range vals {
		maxV = math.Max(maxV, v)
	}
	maxV = niceStep(maxV)
	var b strings.Builder
	fmt.Fprintf(&b, `<svg viewBox="0 0 %.0f %.0f" role="img" aria-label="OSPA over time">`, W, H)
	for i := 0; i <= 4; i++ {
		y := t + (H-t-bt)*float64(i)/4
		fmt.Fprintf(&b, `<line x1="%.0f" x2="%.0f" y1="%.1f" y2="%.1f" stroke="var(--grid)"/><text x="%.0f" y="%.1f" font-size="11" fill="var(--mute)" text-anchor="end">%.0f</text>`, l, W-r, y, y, l-6, y+4, maxV*(1-float64(i)/4))
	}
	var pts []string
	for i, v := range vals {
		x := l + (W-l-r)*float64(i)/math.Max(float64(len(vals)-1), 1)
		y := t + (H-t-bt)*(1-v/maxV)
		pts = append(pts, fmt.Sprintf("%.1f,%.1f", x, y))
	}
	fmt.Fprintf(&b, `<polyline points="%s" fill="none" stroke="var(--accent)" stroke-width="2"/>`, strings.Join(pts, " "))
	fmt.Fprintf(&b, `<text x="%.0f" y="%.0f" font-size="11" fill="var(--mute)">%.0f s</text><text x="%.0f" y="%.0f" font-size="11" fill="var(--mute)" text-anchor="end">%.0f s</text></svg>`, l, H-6, t0, W-r, H-6, t1)
	return b.String()
}
