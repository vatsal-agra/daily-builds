package codec

// Plane is an 8-bit image plane with a replicated border so motion
// compensation never needs bounds checks.
type Plane struct {
	W, H   int // visible (padded-to-macroblock) size
	Stride int
	Border int
	Pix    []uint8
	off    int // index of (0,0)
}

func newPlane(w, h, border int) *Plane {
	stride := w + 2*border
	p := &Plane{W: w, H: h, Stride: stride, Border: border}
	p.Pix = make([]uint8, stride*(h+2*border))
	p.off = border*stride + border
	return p
}

func (p *Plane) idx(x, y int) int { return p.off + y*p.Stride + x }

// Row returns the slice starting at (x,y) running to the end of the row region.
func (p *Plane) Row(x, y int) []uint8 { i := p.idx(x, y); return p.Pix[i : i+p.W-x] }

// extend replicates edge pixels into the border.
func (p *Plane) extend() {
	for y := 0; y < p.H; y++ {
		r := p.idx(0, y)
		l, rr := p.Pix[r], p.Pix[r+p.W-1]
		for x := 1; x <= p.Border; x++ {
			p.Pix[r-x] = l
			p.Pix[r+p.W-1+x] = rr
		}
	}
	top := p.idx(-p.Border, 0)
	bot := p.idx(-p.Border, p.H-1)
	for y := 1; y <= p.Border; y++ {
		copy(p.Pix[top-y*p.Stride:top-y*p.Stride+p.Stride], p.Pix[top:top+p.Stride])
		copy(p.Pix[bot+y*p.Stride:bot+y*p.Stride+p.Stride], p.Pix[bot:bot+p.Stride])
	}
}

func (p *Plane) clone() *Plane {
	q := *p
	q.Pix = append([]uint8(nil), p.Pix...)
	return &q
}

const (
	lumaBorder   = 64
	chromaBorder = 32
)

// Frame is a YUV 4:2:0 picture. Planes are padded to a multiple of 16 luma
// pixels; Width/Height are the visible dimensions.
type Frame struct {
	Width, Height int
	Y, U, V       *Plane
	// Disp is the display index (set by the codec).
	Disp int
}

func padTo16(n int) int { return (n + 15) &^ 15 }

// NewFrame allocates a blank frame (black luma=0 would be invalid video; use mid-grey).
func NewFrame(w, h int) *Frame {
	pw, ph := padTo16(w), padTo16(h)
	f := &Frame{Width: w, Height: h,
		Y: newPlane(pw, ph, lumaBorder),
		U: newPlane(pw/2, ph/2, chromaBorder),
		V: newPlane(pw/2, ph/2, chromaBorder)}
	return f
}

func (f *Frame) extend() { f.Y.extend(); f.U.extend(); f.V.extend() }

func (f *Frame) planes() [3]*Plane { return [3]*Plane{f.Y, f.U, f.V} }

// Clone deep-copies the frame.
func (f *Frame) Clone() *Frame {
	g := *f
	g.Y, g.U, g.V = f.Y.clone(), f.U.clone(), f.V.clone()
	return &g
}

// visible dimensions of plane i.
func (f *Frame) visW(i int) int {
	if i == 0 {
		return f.Width
	}
	return (f.Width + 1) / 2
}
func (f *Frame) visH(i int) int {
	if i == 0 {
		return f.Height
	}
	return (f.Height + 1) / 2
}

// FromPlanar builds a padded frame from tightly-packed I420 data
// (Y w*h, U cw*ch, V cw*ch), replicating edges into the padding.
func FromPlanar(w, h int, data []byte) *Frame {
	f := NewFrame(w, h)
	cw, ch := (w+1)/2, (h+1)/2
	src := [3][]byte{data[:w*h], data[w*h : w*h+cw*ch], data[w*h+cw*ch : w*h+2*cw*ch]}
	for i, p := range f.planes() {
		vw, vh := f.visW(i), f.visH(i)
		for y := 0; y < p.H; y++ {
			sy := y
			if sy >= vh {
				sy = vh - 1
			}
			for x := 0; x < p.W; x++ {
				sx := x
				if sx >= vw {
					sx = vw - 1
				}
				p.Pix[p.idx(x, y)] = src[i][sy*vw+sx]
			}
		}
	}
	f.extend()
	return f
}

// Planar returns tightly-packed I420 of the visible area.
func (f *Frame) Planar() []byte {
	cw, ch := (f.Width+1)/2, (f.Height+1)/2
	out := make([]byte, 0, f.Width*f.Height+2*cw*ch)
	for i, p := range f.planes() {
		vw, vh := f.visW(i), f.visH(i)
		for y := 0; y < vh; y++ {
			out = append(out, p.Pix[p.idx(0, y):p.idx(0, y)+vw]...)
		}
	}
	return out
}

func clip255(v int) uint8 {
	if v < 0 {
		return 0
	}
	if v > 255 {
		return 255
	}
	return uint8(v)
}

func iabs(a int) int {
	if a < 0 {
		return -a
	}
	return a
}
func imin(a, b int) int {
	if a < b {
		return a
	}
	return b
}
func imax(a, b int) int {
	if a > b {
		return a
	}
	return b
}
func clampi(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
