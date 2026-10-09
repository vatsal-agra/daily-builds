package ttf

// Point is an outline control point in font units.
type Point struct {
	X, Y float64
	On   bool // on-curve; otherwise a quadratic Bézier control point
}

// Contour is a closed loop of points.
type Contour []Point

// Outline is a glyph shape: a set of closed contours (non-zero winding fill).
type Outline struct {
	Contours []Contour
}

// NumPoints counts all points over all contours.
func (o Outline) NumPoints() int {
	n := 0
	for _, c := range o.Contours {
		n += len(c)
	}
	return n
}

// Bounds returns the control-box of the outline (xmin, ymin, xmax, ymax).
func (o Outline) Bounds() (x0, y0, x1, y1 float64, ok bool) {
	for _, c := range o.Contours {
		for _, p := range c {
			if !ok {
				x0, y0, x1, y1, ok = p.X, p.Y, p.X, p.Y, true
				continue
			}
			x0, x1 = min(x0, p.X), max(x1, p.X)
			y0, y1 = min(y0, p.Y), max(y1, p.Y)
		}
	}
	return
}

// Transform returns a copy mapped through x' = a*x + c*y + e, y' = b*x + d*y + f.
func (o Outline) Transform(a, b, c, d, e, f float64) Outline {
	out := Outline{Contours: make([]Contour, len(o.Contours))}
	for i, ct := range o.Contours {
		nc := make(Contour, len(ct))
		for j, p := range ct {
			nc[j] = Point{a*p.X + c*p.Y + e, b*p.X + d*p.Y + f, p.On}
		}
		out.Contours[i] = nc
	}
	return out
}
