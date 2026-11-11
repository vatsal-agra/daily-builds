package fem

import (
	"fmt"
	"html"
	"math"
	"sort"
	"strings"
)

// colormap: a perceptually ordered deep-blue → teal → yellow → orange → red ramp.
var ramp = [][3]float64{
	{38, 70, 160}, {40, 130, 190}, {45, 175, 175}, {120, 200, 120}, {235, 215, 80}, {240, 150, 50}, {215, 60, 45}, {140, 20, 60},
}

func rampColor(t float64) string {
	t = math.Max(0, math.Min(1, t))
	if math.IsNaN(t) {
		t = 0
	}
	x := t * float64(len(ramp)-1)
	i := int(x)
	if i >= len(ramp)-1 {
		i = len(ramp) - 2
	}
	f := x - float64(i)
	c := [3]float64{}
	for k := 0; k < 3; k++ {
		c[k] = ramp[i][k]*(1-f) + ramp[i+1][k]*f
	}
	return fmt.Sprintf("#%02x%02x%02x", int(c[0]+.5), int(c[1]+.5), int(c[2]+.5))
}

// ContourOpts controls SVG output.
type ContourOpts struct {
	Width       float64
	DeformScale float64 // 0 = undeformed
	ShowMesh    bool
	Lo, Hi      float64 // colour range; if Lo>=Hi it is taken from the data
	Title       string
	Unit        string
}

// AutoDeformScale chooses a magnification so the max displacement is ~8% of the model size.
func AutoDeformScale(m *Mesh, u []float64) float64 {
	x0, y0, x1, y1 := m.Bounds()
	size := math.Max(x1-x0, y1-y0)
	mx := 0.0
	for i := 0; i < m.NumNodes(); i++ {
		mx = math.Max(mx, math.Hypot(u[2*i], u[2*i+1]))
	}
	if mx == 0 {
		return 0
	}
	s := 0.08 * size / mx
	// round to a 1-2-5 value for a legible caption
	p := math.Pow(10, math.Floor(math.Log10(s)))
	switch f := s / p; {
	case f >= 5:
		return 5 * p
	case f >= 2:
		return 2 * p
	}
	return p
}

// subdivide returns the sub-triangles of an element as reference-coordinate triples.
func subTriangles(t ElemType, n int) [][3][2]float64 {
	var out [][3][2]float64
	switch t {
	case Quad4:
		for i := 0; i < n; i++ {
			for j := 0; j < n; j++ {
				x0, x1 := -1+2*float64(i)/float64(n), -1+2*float64(i+1)/float64(n)
				y0, y1 := -1+2*float64(j)/float64(n), -1+2*float64(j+1)/float64(n)
				out = append(out, [3][2]float64{{x0, y0}, {x1, y0}, {x1, y1}}, [3][2]float64{{x0, y0}, {x1, y1}, {x0, y1}})
			}
		}
	default:
		f := 1 / float64(n)
		for i := 0; i < n; i++ {
			for j := 0; i+j < n; j++ {
				a := [2]float64{float64(i) * f, float64(j) * f}
				b := [2]float64{float64(i+1) * f, float64(j) * f}
				c := [2]float64{float64(i) * f, float64(j+1) * f}
				d := [2]float64{float64(i+1) * f, float64(j+1) * f}
				out = append(out, [3][2]float64{a, b, c})
				if i+j < n-1 {
					out = append(out, [3][2]float64{b, d, c})
				}
			}
		}
	}
	return out
}

// ContourSVG renders a nodal scalar field on the (optionally deformed) mesh.
func ContourSVG(m *Mesh, u []float64, vals []float64, o ContourOpts) string {
	if o.Width == 0 {
		o.Width = 720
	}
	sc := o.DeformScale
	px := func(i int) (float64, float64) {
		x, y := m.X[i], m.Y[i]
		if sc != 0 && u != nil {
			x += sc * u[2*i]
			y += sc * u[2*i+1]
		}
		return x, y
	}
	minX, minY, maxX, maxY := math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)
	for i := range m.X {
		for _, s := range []float64{0, sc} {
			x, y := m.X[i], m.Y[i]
			if s != 0 && u != nil {
				x += s * u[2*i]
				y += s * u[2*i+1]
			}
			minX, maxX = math.Min(minX, x), math.Max(maxX, x)
			minY, maxY = math.Min(minY, y), math.Max(maxY, y)
		}
	}
	lo, hi := o.Lo, o.Hi
	if !(lo < hi) {
		lo, hi = math.Inf(1), math.Inf(-1)
		for _, v := range vals {
			lo, hi = math.Min(lo, v), math.Max(hi, v)
		}
		if !(lo < hi) {
			hi = lo + 1
		}
	}
	pad := 0.04 * math.Max(maxX-minX, maxY-minY)
	minX, minY, maxX, maxY = minX-pad, minY-pad, maxX+pad, maxY+pad
	W, H := maxX-minX, maxY-minY
	scale := o.Width / W
	height := H * scale
	barH := 46.0
	tx := func(x float64) float64 { return (x - minX) * scale }
	ty := func(y float64) float64 { return (maxY - y) * scale }

	sub := 4
	for sub > 1 && m.NumElems()*len(subTriangles(m.Type, sub)) > 60000 {
		sub--
	}
	tris := subTriangles(m.Type, sub)
	var b strings.Builder
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.0f %.0f" role="img" aria-label="%s" class="contour">`, o.Width, height+barH+4, html.EscapeString(o.Title))
	const levels = 64 // colours are quantised so each level is a single <path>
	paths := make([]strings.Builder, levels)
	for _, c := range m.Conn {
		xs, ys := make([]float64, len(c)), make([]float64, len(c))
		vs := make([]float64, len(c))
		for i, n := range c {
			xs[i], ys[i] = px(n)
			vs[i] = vals[n]
		}
		for _, tr := range tris {
			var pts [3][2]float64
			v := 0.0
			for k := 0; k < 3; k++ {
				sh, _ := m.Type.Shape(tr[k][0], tr[k][1])
				var x, y, val float64
				for i := range sh {
					x += sh[i] * xs[i]
					y += sh[i] * ys[i]
					val += sh[i] * vs[i]
				}
				pts[k] = [2]float64{tx(x), ty(y)}
				v += val / 3
			}
			lv := int(math.Round((v - lo) / (hi - lo) * (levels - 1)))
			if lv < 0 {
				lv = 0
			} else if lv >= levels {
				lv = levels - 1
			}
			fmt.Fprintf(&paths[lv], "M%.1f %.1fL%.1f %.1fL%.1f %.1fz", pts[0][0], pts[0][1], pts[1][0], pts[1][1], pts[2][0], pts[2][1])
		}
	}
	for lv := range paths {
		if paths[lv].Len() == 0 {
			continue
		}
		col := rampColor(float64(lv) / (levels - 1))
		fmt.Fprintf(&b, `<path fill="%s" stroke="%s" stroke-width="0.7" stroke-linejoin="round" d="%s"/>`, col, col, paths[lv].String())
	}
	if o.ShowMesh {
		corners := 3
		if m.Type == Quad4 {
			corners = 4
		}
		b.WriteString(`<g class="meshlines" fill="none">`)
		for _, c := range m.Conn {
			var pts []string
			for k := 0; k < corners; k++ {
				x, y := px(c[k])
				pts = append(pts, fmt.Sprintf("%.1f,%.1f", tx(x), ty(y)))
			}
			fmt.Fprintf(&b, `<polygon points="%s"/>`, strings.Join(pts, " "))
		}
		b.WriteString(`</g>`)
	}
	// undeformed outline
	if sc != 0 {
		b.WriteString(`<g class="outline" fill="none">`)
		for _, e := range m.BoundaryEdges() {
			fmt.Fprintf(&b, `<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>`, tx(m.X[e[0]]), ty(m.Y[e[0]]), tx(m.X[e[1]]), ty(m.Y[e[1]]))
		}
		b.WriteString(`</g>`)
	}
	// colour bar
	by := height + 10
	bw := o.Width - 40
	for i := 0; i < 64; i++ {
		fmt.Fprintf(&b, `<rect x="%.1f" y="%.1f" width="%.1f" height="10" fill="%s"/>`, 20+bw*float64(i)/64, by, bw/64+0.5, rampColor(float64(i)/63))
	}
	for i := 0; i <= 4; i++ {
		v := lo + (hi-lo)*float64(i)/4
		anchor := "middle"
		if i == 0 {
			anchor = "start"
		} else if i == 4 {
			anchor = "end"
		}
		fmt.Fprintf(&b, `<text x="%.1f" y="%.1f" text-anchor="%s" class="tick">%s</text>`, 20+bw*float64(i)/4, by+24, anchor, fmtNum(v))
	}
	if o.Unit != "" {
		fmt.Fprintf(&b, `<text x="%.1f" y="%.1f" text-anchor="middle" class="tick">%s</text>`, 20+bw/2, by+38, html.EscapeString(o.Unit))
	}
	b.WriteString(`</svg>`)
	return b.String()
}

func fmtNum(v float64) string {
	a := math.Abs(v)
	switch {
	case a == 0:
		return "0"
	case a >= 1e5 || a < 1e-3:
		return fmt.Sprintf("%.3g", v)
	case a >= 100:
		return fmt.Sprintf("%.0f", v)
	case a >= 10:
		return fmt.Sprintf("%.1f", v)
	}
	return fmt.Sprintf("%.3g", v)
}

// FrameSVG draws a frame: undeformed (grey), deformed (accent) and bending-moment fill.
func FrameSVG(f *Frame, sol *FrameSolution, defScale float64, width float64, showMoment bool) string {
	if width == 0 {
		width = 720
	}
	minX, minY, maxX, maxY := math.Inf(1), math.Inf(1), math.Inf(-1), math.Inf(-1)
	var defl [][][2]float64
	for i := range f.Members {
		d := f.Deflected(sol, i, defScale, 20)
		defl = append(defl, d)
		for _, p := range d {
			minX, maxX = math.Min(minX, p[0]), math.Max(maxX, p[0])
			minY, maxY = math.Min(minY, p[1]), math.Max(maxY, p[1])
		}
	}
	for i := range f.X {
		minX, maxX = math.Min(minX, f.X[i]), math.Max(maxX, f.X[i])
		minY, maxY = math.Min(minY, f.Y[i]), math.Max(maxY, f.Y[i])
	}
	size := math.Max(maxX-minX, maxY-minY)
	if size == 0 {
		size = 1
	}
	// moment diagram scale: biggest moment drawn at 12% of size
	mmax := 0.0
	if showMoment {
		for i, m := range f.Members {
			if m.Truss {
				continue
			}
			L := f.length(m)
			for k := 0; k <= 20; k++ {
				mmax = math.Max(mmax, math.Abs(f.MomentAt(sol, i, L*float64(k)/20)))
			}
		}
	}
	mscale := 0.0
	if mmax > 0 {
		mscale = 0.12 * size / mmax
	}
	pad := 0.14 * size
	minX, minY, maxX, maxY = minX-pad, minY-pad, maxX+pad, maxY+pad
	sc := width / (maxX - minX)
	tx := func(x float64) float64 { return (x - minX) * sc }
	ty := func(y float64) float64 { return (maxY - y) * sc }
	var b strings.Builder
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.0f %.0f" role="img" aria-label="frame result" class="contour">`, width, (maxY-minY)*sc)
	if showMoment && mscale > 0 {
		for i, m := range f.Members {
			if m.Truss {
				continue
			}
			c, s, L := f.axis(m)
			var top, bot []string
			for k := 0; k <= 20; k++ {
				x := L * float64(k) / 20
				mo := f.MomentAt(sol, i, x)
				// draw on the tension side: sagging (+) is plotted toward local -y
				px := f.X[m.N1] + x*c
				py := f.Y[m.N1] + x*s
				qx := px + s*mo*mscale
				qy := py - c*mo*mscale
				top = append(top, fmt.Sprintf("%.1f,%.1f", tx(px), ty(py)))
				bot = append(bot, fmt.Sprintf("%.1f,%.1f", tx(qx), ty(qy)))
			}
			for l, r := 0, len(bot)-1; l < r; l, r = l+1, r-1 {
				top[l], top[r] = top[r], top[l]
			}
			fmt.Fprintf(&b, `<polygon class="moment" points="%s %s"/>`, strings.Join(bot, " "), strings.Join(top, " "))
		}
	}
	for _, m := range f.Members {
		fmt.Fprintf(&b, `<line class="undef" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>`, tx(f.X[m.N1]), ty(f.Y[m.N1]), tx(f.X[m.N2]), ty(f.Y[m.N2]))
	}
	// colour the deformed shape by axial force
	var axmax float64
	for i := range f.Members {
		axmax = math.Max(axmax, math.Abs(f.AxialForce(sol, i)))
	}
	for i, d := range defl {
		var pts []string
		for _, p := range d {
			pts = append(pts, fmt.Sprintf("%.1f,%.1f", tx(p[0]), ty(p[1])))
		}
		col := "var(--accent)"
		if axmax > 0 {
			col = rampColor(0.5 + 0.5*f.AxialForce(sol, i)/axmax)
		}
		fmt.Fprintf(&b, `<polyline class="def" stroke="%s" points="%s"/>`, col, strings.Join(pts, " "))
	}
	for i := range f.X {
		fmt.Fprintf(&b, `<circle class="node" cx="%.1f" cy="%.1f" r="3.2"/>`, tx(f.X[i]), ty(f.Y[i]))
	}
	supported := map[int]bool{}
	for d := range f.Fixed {
		supported[d/3] = true
	}
	var sn []int
	for n := range supported {
		sn = append(sn, n)
	}
	sort.Ints(sn)
	for _, n := range sn {
		fmt.Fprintf(&b, `<path class="support" d="M%.1f %.1f l-7 12 h14 z"/>`, tx(f.X[n]), ty(f.Y[n])+3)
	}
	b.WriteString(`</svg>`)
	return b.String()
}

// DensitySVG renders a topology-optimisation density field on an nx x ny grid (row 0 = bottom).
func DensitySVG(rho []float64, nx, ny int, width float64) string {
	cell := width / float64(nx)
	var b strings.Builder
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.0f %.1f" role="img" aria-label="optimised topology" class="topo">`, width, cell*float64(ny))
	fmt.Fprintf(&b, `<rect width="%.0f" height="%.1f" class="topobg"/>`, width, cell*float64(ny))
	for j := 0; j < ny; j++ {
		for i := 0; i < nx; i++ {
			d := rho[j*nx+i]
			if d < 0.02 {
				continue
			}
			fmt.Fprintf(&b, `<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" class="solid" fill-opacity="%.3f"/>`,
				float64(i)*cell, float64(ny-1-j)*cell, cell+0.35, cell+0.35, math.Min(1, d))
		}
	}
	b.WriteString(`</svg>`)
	return b.String()
}
