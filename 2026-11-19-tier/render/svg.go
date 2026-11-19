// Package render draws layout results as self-contained SVG / HTML.
package render

import (
	"fmt"
	"html"
	"math"
	"strings"

	"tier/layout"
)

// SVGStyle is embedded inside each SVG so it adapts to light/dark mode.
const SVGStyle = `
.tier{--bg:#fbfaf7;--node:#ffffff;--stroke:#3b4252;--edge:#6b7488;--text:#1d2330;--rev:#d9480f;--band:#f0ede6;--hl:#2563eb;--halo:#fbfaf7}
@media (prefers-color-scheme:dark){.tier{--bg:#161a22;--node:#222836;--stroke:#aab3c5;--edge:#7f8aa3;--text:#e8ecf4;--rev:#ff8a4c;--band:#1c212c;--hl:#6aa3ff;--halo:#161a22}}
.tier .bg{fill:var(--bg)}.tier .band{fill:var(--band)}
.tier .n rect,.tier .n ellipse{fill:var(--node);stroke:var(--stroke);stroke-width:1.3}
.tier .n text{fill:var(--text);font:13px ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;text-anchor:middle}
.tier .e path{fill:none;stroke:var(--edge);stroke-width:1.4}
.tier .e.rev path{stroke:var(--rev);stroke-dasharray:5 3}
.tier .e text{fill:var(--text);font:11px ui-sans-serif,system-ui,sans-serif;text-anchor:middle;paint-order:stroke;stroke:var(--halo);stroke-width:4px}
.tier .arr{fill:var(--edge)}.tier .arr-rev{fill:var(--rev)}
.tier .rk{fill:var(--edge);font:10px ui-monospace,monospace;opacity:.7}
.tier .n{cursor:default}.tier .n:hover rect,.tier .n:hover ellipse,.tier .n.hl rect,.tier .n.hl ellipse{stroke:var(--hl);stroke-width:2.4}
.tier .e.hl path{stroke:var(--hl);stroke-width:2.4}
`

func f(x float64) string {
	s := fmt.Sprintf("%.1f", x)
	return strings.TrimSuffix(s, ".0")
}

// catmull converts a polyline into smooth cubic Béziers through every point.
func catmull(pts []layout.Pt) string {
	if len(pts) == 0 {
		return ""
	}
	var sb strings.Builder
	fmt.Fprintf(&sb, "M%s,%s", f(pts[0].X), f(pts[0].Y))
	if len(pts) == 2 {
		fmt.Fprintf(&sb, "L%s,%s", f(pts[1].X), f(pts[1].Y))
		return sb.String()
	}
	at := func(i int) layout.Pt {
		if i < 0 {
			i = 0
		}
		if i >= len(pts) {
			i = len(pts) - 1
		}
		return pts[i]
	}
	for i := 0; i+1 < len(pts); i++ {
		p0, p1, p2, p3 := at(i-1), at(i), at(i+1), at(i+2)
		c1 := layout.Pt{X: p1.X + (p2.X-p0.X)/6, Y: p1.Y + (p2.Y-p0.Y)/6}
		c2 := layout.Pt{X: p2.X - (p3.X-p1.X)/6, Y: p2.Y - (p3.Y-p1.Y)/6}
		fmt.Fprintf(&sb, "C%s,%s %s,%s %s,%s", f(c1.X), f(c1.Y), f(c2.X), f(c2.Y), f(p2.X), f(p2.Y))
	}
	return sb.String()
}

// EdgePath returns the SVG path data for a routed edge.
func EdgePath(e layout.EdgeRoute, spline bool) string {
	if e.SelfLoop && len(e.Points) == 4 {
		p := e.Points
		return fmt.Sprintf("M%s,%s C%s,%s %s,%s %s,%s", f(p[0].X), f(p[0].Y), f(p[1].X), f(p[1].Y), f(p[2].X), f(p[2].Y), f(p[3].X), f(p[3].Y))
	}
	if spline {
		return catmull(e.Points)
	}
	var sb strings.Builder
	for i, p := range e.Points {
		if i == 0 {
			sb.WriteString("M")
		} else {
			sb.WriteString("L")
		}
		fmt.Fprintf(&sb, "%s,%s", f(p.X), f(p.Y))
	}
	return sb.String()
}

// Options for SVG output.
type Options struct {
	Directed bool
	Polyline bool // straight segments instead of splines
	Bands    bool // faint rank bands with rank numbers
	IDPrefix string
	Inline   bool // omit XML header and <style> (caller supplies SVGStyle)
}

func multi(label string) []string {
	return strings.Split(strings.ReplaceAll(label, `\n`, "\n"), "\n")
}

// SVG renders a layout.
func SVG(r *layout.Result, o Options) string {
	var sb strings.Builder
	w, h := math.Max(r.Width, 80), math.Max(r.Height, 60)
	if !o.Inline {
		sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>` + "\n")
	}
	fmt.Fprintf(&sb, `<svg xmlns="http://www.w3.org/2000/svg" class="tier" viewBox="0 0 %s %s" width="%s" height="%s" role="img" aria-label="layered graph drawing">`+"\n", f(w), f(h), f(w), f(h))
	if !o.Inline {
		sb.WriteString("<style>" + SVGStyle + "</style>\n")
	}
	p := o.IDPrefix
	fmt.Fprintf(&sb, `<defs><marker id="%sa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path class="arr" d="M0,1 L10,5 L0,9 z"/></marker><marker id="%sar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path class="arr-rev" d="M0,1 L10,5 L0,9 z"/></marker></defs>`+"\n", p, p)
	fmt.Fprintf(&sb, `<rect class="bg" width="%s" height="%s"/>`+"\n", f(w), f(h))
	if o.Bands && r.Rows == 1 && len(r.Nodes) > 0 {
		type band struct{ lo, hi float64 }
		bands := map[int]*band{}
		maxRank := 0
		for _, n := range r.Nodes {
			c, half := n.Y, n.H/2
			if r.Opts.RankDir == "LR" {
				c, half = n.X, n.W/2
			}
			if n.Rank > maxRank {
				maxRank = n.Rank
			}
			if b := bands[n.Rank]; b == nil {
				bands[n.Rank] = &band{c - half, c + half}
			} else {
				b.lo, b.hi = math.Min(b.lo, c-half), math.Max(b.hi, c+half)
			}
		}
		for rk := 0; rk <= maxRank; rk++ {
			b, ok := bands[rk]
			if !ok {
				continue
			}
			if r.Opts.RankDir == "LR" {
				fmt.Fprintf(&sb, `<rect class="band" x="%s" y="0" width="%s" height="%s"/><text class="rk" x="%s" y="12" text-anchor="middle">%d</text>`, f(b.lo-8), f(b.hi-b.lo+16), f(h), f((b.lo+b.hi)/2), rk)
			} else {
				fmt.Fprintf(&sb, `<rect class="band" x="0" y="%s" width="%s" height="%s"/><text class="rk" x="6" y="%s">%d</text>`, f(b.lo-8), f(w), f(b.hi-b.lo+16), f((b.lo+b.hi)/2+3), rk)
			}
		}
		sb.WriteString("\n")
	}
	for _, e := range r.Edges {
		if len(e.Points) < 2 {
			continue
		}
		cls, mk := "e", p+"a"
		if e.Reversed {
			cls, mk = "e rev", p+"ar"
		}
		from, to := r.Nodes[e.From].ID, r.Nodes[e.To].ID
		marker := ""
		if o.Directed {
			marker = fmt.Sprintf(` marker-end="url(#%s)"`, mk)
		}
		fmt.Fprintf(&sb, `<g class="%s" data-from="%s" data-to="%s"><path d="%s"%s/>`, cls, html.EscapeString(from), html.EscapeString(to), EdgePath(e, !o.Polyline), marker)
		if e.HasLabel {
			fmt.Fprintf(&sb, `<text x="%s" y="%s">%s</text>`, f(e.LabelPos.X), f(e.LabelPos.Y+4), html.EscapeString(e.Label))
		}
		sb.WriteString("</g>\n")
	}
	for _, n := range r.Nodes {
		fmt.Fprintf(&sb, `<g class="n" data-id="%s"><title>%s (rank %d)</title>`, html.EscapeString(n.ID), html.EscapeString(n.ID), n.Rank)
		if n.Shape == "ellipse" {
			fmt.Fprintf(&sb, `<ellipse cx="%s" cy="%s" rx="%s" ry="%s"/>`, f(n.X), f(n.Y), f(n.W/2), f(n.H/2))
		} else {
			fmt.Fprintf(&sb, `<rect x="%s" y="%s" width="%s" height="%s" rx="5"/>`, f(n.X-n.W/2), f(n.Y-n.H/2), f(n.W), f(n.H))
		}
		lines := multi(n.Label)
		y0 := n.Y - float64(len(lines)-1)*8.5 + 4.5
		for i, ln := range lines {
			fmt.Fprintf(&sb, `<text x="%s" y="%s">%s</text>`, f(n.X), f(y0+float64(i)*17), html.EscapeString(ln))
		}
		sb.WriteString("</g>\n")
	}
	sb.WriteString("</svg>\n")
	return sb.String()
}
