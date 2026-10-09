package render

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"glyph/layout"
	"glyph/raster"
	"glyph/ttf"
)

func fnum(v float64) string {
	s := strconv.FormatFloat(math.Round(v*100)/100, 'f', -1, 64)
	if s == "-0" {
		return "0"
	}
	return s
}

// PathData converts an outline to SVG path data using true quadratic curves
// (no flattening), mapped through m.
func PathData(o ttf.Outline, m raster.Affine) string {
	var sb strings.Builder
	ap := func(x, y float64) (float64, float64) { return m.A*x + m.C*y + m.E, m.B*x + m.D*y + m.F }
	pt := func(p ttf.Point) string { x, y := ap(p.X, p.Y); return fnum(x) + " " + fnum(y) }
	for _, c := range o.Contours {
		n := len(c)
		if n < 2 {
			continue
		}
		pts := append([]ttf.Point(nil), c...)
		var start ttf.Point
		first := 0
		switch {
		case pts[0].On:
			start, first = pts[0], 1
		case pts[n-1].On:
			start = pts[n-1]
			pts = pts[:n-1]
		default:
			start = ttf.Point{X: (pts[0].X + pts[n-1].X) / 2, Y: (pts[0].Y + pts[n-1].Y) / 2, On: true}
		}
		sb.WriteString("M" + pt(start))
		var ctrl ttf.Point
		have := false
		for i := first; i < len(pts); i++ {
			p := pts[i]
			switch {
			case p.On && !have:
				sb.WriteString("L" + pt(p))
			case p.On:
				sb.WriteString("Q" + pt(ctrl) + " " + pt(p))
				have = false
			case have:
				mid := ttf.Point{X: (ctrl.X + p.X) / 2, Y: (ctrl.Y + p.Y) / 2, On: true}
				sb.WriteString("Q" + pt(ctrl) + " " + pt(mid))
				ctrl = p
			default:
				ctrl, have = p, true
			}
		}
		if have {
			sb.WriteString("Q" + pt(ctrl) + " " + pt(start))
		}
		sb.WriteString("Z")
	}
	return sb.String()
}

// SVG renders laid-out text as a standalone SVG document with exact outlines.
// The viewBox is computed from the real outline extents, so nothing is clipped.
func SVG(f *ttf.Font, text string, st Style) (string, error) {
	res, err := layout.Layout(f, text, st.Options)
	if err != nil {
		return "", err
	}
	scale := st.Size / float64(f.UnitsPerEm)
	pad := float64(max(st.Padding, 0))
	minX, minY := 0.0, 0.0
	maxX, maxY := math.Max(res.Width, st.Width), res.Height
	for _, g := range res.Glyphs {
		o, err := f.Glyph(g.GID)
		if err != nil {
			return "", err
		}
		if len(o.Contours) == 0 {
			continue
		}
		m := raster.Scale(scale, g.X, g.Y, st.Slant)
		for _, c := range o.Contours {
			for _, p := range c {
				x, y := m.A*p.X+m.C*p.Y+m.E, m.B*p.X+m.D*p.Y+m.F
				minX, maxX, minY, maxY = math.Min(minX, x), math.Max(maxX, x), math.Min(minY, y), math.Max(maxY, y)
			}
		}
	}
	w, h := math.Ceil(maxX-minX)+2*pad, math.Ceil(maxY-minY)+2*pad
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg xmlns="http://www.w3.org/2000/svg" width="%s" height="%s" viewBox="0 0 %s %s">`+"\n", fnum(w), fnum(h), fnum(w), fnum(h))
	fmt.Fprintf(&sb, `<rect width="100%%" height="100%%" fill="#%02x%02x%02x"/>`+"\n", st.BG.R, st.BG.G, st.BG.B)
	fmt.Fprintf(&sb, `<g fill="#%02x%02x%02x" fill-rule="nonzero">`+"\n", st.FG.R, st.FG.G, st.FG.B)
	for _, g := range res.Glyphs {
		o, _ := f.Glyph(g.GID)
		if len(o.Contours) == 0 {
			continue
		}
		d := PathData(o, raster.Scale(scale, pad-minX+g.X, pad-minY+g.Y, st.Slant))
		fmt.Fprintf(&sb, `<path d="%s"/>`+"\n", d)
	}
	sb.WriteString("</g>\n</svg>\n")
	return sb.String(), nil
}
