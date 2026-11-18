package cube

// Physical is an independent model of the cube: 54 stickers living in 3-D space
// (x right, y up, z toward the viewer). Moves are real 90° rotations of every
// sticker whose cubie lies in the turned layer. It shares no code or tables with the
// cubie model, so agreement between the two is meaningful evidence of correctness.
type Physical struct {
	stickers [54]sticker
}

type sticker struct {
	pos, normal [3]int
	color       byte
}

func faceletIndex(pos, n [3]int) int {
	x, y, z := pos[0], pos[1], pos[2]
	switch {
	case n[1] == 1:
		return 0*9 + (z+1)*3 + (x + 1)
	case n[0] == 1:
		return 1*9 + (1-y)*3 + (1 - z)
	case n[2] == 1:
		return 2*9 + (1-y)*3 + (x + 1)
	case n[1] == -1:
		return 3*9 + (1-z)*3 + (x + 1)
	case n[0] == -1:
		return 4*9 + (1-y)*3 + (z + 1)
	default:
		return 5*9 + (1-y)*3 + (1 - x)
	}
}

var faceNormals = [6][3]int{{0, 1, 0}, {1, 0, 0}, {0, 0, 1}, {0, -1, 0}, {-1, 0, 0}, {0, 0, -1}}

// NewPhysical builds a solved physical cube.
func NewPhysical() *Physical {
	p := &Physical{}
	for f := 0; f < 6; f++ {
		n := faceNormals[f]
		for x := -1; x <= 1; x++ {
			for y := -1; y <= 1; y++ {
				for z := -1; z <= 1; z++ {
					pos := [3]int{x, y, z}
					if pos[0]*n[0]+pos[1]*n[1]+pos[2]*n[2] != 1 {
						continue
					}
					p.stickers[faceletIndex(pos, n)] = sticker{pos, n, faceLetters[f]}
				}
			}
		}
	}
	return p
}

// rotate90 rotates v by q quarter turns (right-hand rule, +x/+y/+z axis).
func rotate90(v [3]int, axis, q int) [3]int {
	q = ((q % 4) + 4) % 4
	for ; q > 0; q-- {
		switch axis {
		case 0:
			v = [3]int{v[0], -v[2], v[1]}
		case 1:
			v = [3]int{v[2], v[1], -v[0]}
		default:
			v = [3]int{-v[1], v[0], v[2]}
		}
	}
	return v
}

// face -> (axis, layer coordinate, quarter turns per clockwise turn in right-hand sense)
var faceAxis = [6]struct{ axis, layer, sign int }{
	U: {1, 1, -1}, R: {0, 1, -1}, F: {2, 1, -1}, D: {1, -1, 1}, L: {0, -1, 1}, B: {2, -1, 1},
}

// Apply performs move m physically.
func (p *Physical) Apply(m Move) {
	fa := faceAxis[m.Face()]
	q := fa.sign * m.Turns()
	for i := range p.stickers {
		s := &p.stickers[i]
		if s.pos[fa.axis] == fa.layer {
			s.pos = rotate90(s.pos, fa.axis, q)
			s.normal = rotate90(s.normal, fa.axis, q)
		}
	}
}

// Facelets reads the sticker colors back into a facelet string.
func (p *Physical) Facelets() string {
	var out [54]byte
	for _, s := range p.stickers {
		out[faceletIndex(s.pos, s.normal)] = s.color
	}
	return string(out[:])
}

// PhysicalFacelets simulates ms on a solved cube physically and returns the facelets.
func PhysicalFacelets(ms []Move) string {
	p := NewPhysical()
	for _, m := range ms {
		p.Apply(m)
	}
	return p.Facelets()
}

// PhysicalFaceletsFrom applies ms to an arbitrary facelet-string start state, physically.
func PhysicalFaceletsFrom(start string, ms []Move) string {
	p := NewPhysical()
	for i := range p.stickers {
		s := &p.stickers[i]
		s.color = start[faceletIndex(s.pos, s.normal)]
	}
	for _, m := range ms {
		p.Apply(m)
	}
	return p.Facelets()
}
