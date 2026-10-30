package qr

import (
	"errors"
	"fmt"
	"unicode/utf8"
)

// Options controls encoding.
type Options struct {
	ECC        ECC
	MinVersion int  // 0 = 1
	MaxVersion int  // 0 = 40
	Mask       int  // -1 = choose lowest penalty; 0..7 forces
	BoostECC   bool // raise the level while the version does not grow
	NoECI      bool // do not emit an ECI header for non-ASCII text
}

// DefaultOptions returns medium ECC with automatic version and mask.
func DefaultOptions() Options { return Options{ECC: M, Mask: -1, BoostECC: true} }

// Code is an encoded symbol.
type Code struct {
	Version  int
	ECC      ECC
	Mask     int
	Matrix   *Matrix
	Segments []Segment
	// Codewords is the final interleaved data+ECC codeword stream.
	Codewords []byte
	Penalty   int
}

// ErrTooLong is returned when the payload does not fit any allowed version.
var ErrTooLong = errors.New("qr: data too long for the requested version/ECC range")

// Encode encodes text/bytes choosing segmentation, version and mask automatically.
func Encode(data []byte, opt Options) (*Code, error) {
	lo, hi := opt.MinVersion, opt.MaxVersion
	if lo == 0 {
		lo = 1
	}
	if hi == 0 {
		hi = 40
	}
	if lo < 1 || hi > 40 || lo > hi {
		return nil, fmt.Errorf("qr: bad version range %d..%d", lo, hi)
	}
	if opt.Mask < -1 || opt.Mask > 7 {
		return nil, fmt.Errorf("qr: mask %d out of range", opt.Mask)
	}
	var prefix []Segment
	if !opt.NoECI && !isASCII(data) && utf8.Valid(data) {
		prefix = []Segment{ECISegment(26)}
	}
	for v := lo; v <= hi; v++ {
		segs := append(append([]Segment(nil), prefix...), OptimalSegments(data, v)...)
		bits := totalBits(segs, v)
		if bits >= 0 && bits <= DataCodewords(v, opt.ECC)*8 {
			return EncodeSegments(segs, v, opt)
		}
	}
	return nil, ErrTooLong
}

// EncodeText is Encode for a string.
func EncodeText(s string, opt Options) (*Code, error) { return Encode([]byte(s), opt) }

func isASCII(b []byte) bool {
	for _, c := range b {
		if c >= 0x80 {
			return false
		}
	}
	return true
}

// EncodeSegments encodes pre-built segments at a fixed version. If opt.BoostECC
// is set, the level is raised as far as the segments still fit.
func EncodeSegments(segs []Segment, version int, opt Options) (*Code, error) {
	if version < 1 || version > 40 {
		return nil, fmt.Errorf("qr: version %d out of range", version)
	}
	bits := totalBits(segs, version)
	if bits < 0 {
		return nil, errors.New("qr: segment too long for version")
	}
	ecc := opt.ECC
	if bits > DataCodewords(version, ecc)*8 {
		return nil, ErrTooLong
	}
	if opt.BoostECC {
		for _, e := range []ECC{M, Q, H} {
			if e > ecc && bits <= DataCodewords(version, e)*8 {
				ecc = e
			}
		}
	}
	capBits := DataCodewords(version, ecc) * 8
	w := &bitWriter{}
	for _, s := range segs {
		if err := w.writeSegment(s, version); err != nil {
			return nil, err
		}
	}
	w.put(0, min(4, capBits-w.len()))
	w.put(0, (8-w.len()%8)%8)
	for pad := 0xEC; w.len() < capBits; pad ^= 0xEC ^ 0x11 {
		w.put(pad, 8)
	}
	data := w.bytes()
	cw := interleave(data, version, ecc)

	l := NewLayout(version)
	base := NewMatrix(l.N)
	drawFunctionPatterns(base, l)
	order := l.DataOrder()
	for i, p := range order {
		bit := false
		if i < len(cw)*8 {
			bit = cw[i/8]>>(7-uint(i%8))&1 == 1
		} // remainder bits stay light
		base.Set(p[0], p[1], bit)
	}
	mask, best := opt.Mask, -1
	pen := 0
	if mask < 0 {
		for mk := 0; mk < 8; mk++ {
			t := base.Clone()
			applyMask(t, l, mk)
			drawFormat(t, ecc, mk)
			if p := Penalty(t); best < 0 || p < best {
				best, mask = p, mk
			}
		}
		pen = best
	}
	applyMask(base, l, mask)
	drawFormat(base, ecc, mask)
	if pen == 0 {
		pen = Penalty(base)
	}
	return &Code{Version: version, ECC: ecc, Mask: mask, Matrix: base, Segments: segs, Codewords: cw, Penalty: pen}, nil
}

// interleave splits data into blocks, appends RS parity and interleaves.
func interleave(data []byte, version int, e ECC) []byte {
	lens, eccLen := blockLayout(version, e)
	var blocks, parity [][]byte
	pos := 0
	for _, n := range lens {
		d := data[pos : pos+n]
		pos += n
		blocks = append(blocks, d)
		parity = append(parity, RSEncode(d, eccLen))
	}
	out := make([]byte, 0, RawCodewords(version))
	maxLen := lens[len(lens)-1]
	for i := 0; i < maxLen; i++ {
		for _, b := range blocks {
			if i < len(b) {
				out = append(out, b[i])
			}
		}
	}
	for i := 0; i < eccLen; i++ {
		for _, p := range parity {
			out = append(out, p[i])
		}
	}
	return out
}

func drawFunctionPatterns(m *Matrix, l *Layout) {
	n := l.N
	for i := 0; i < n; i++ {
		m.Set(6, i, i%2 == 0)
		m.Set(i, 6, i%2 == 0)
	}
	for _, c := range [][2]int{{3, 3}, {n - 4, 3}, {3, n - 4}} {
		for dy := -4; dy <= 4; dy++ {
			for dx := -4; dx <= 4; dx++ {
				x, y := c[0]+dx, c[1]+dy
				if x < 0 || y < 0 || x >= n || y >= n {
					continue
				}
				d := max(abs(dx), abs(dy))
				m.Set(x, y, d != 2 && d != 4)
			}
		}
	}
	ap := alignPositions(l.Version)
	for i, cy := range ap {
		for j, cx := range ap {
			if (i == 0 && j == 0) || (i == 0 && j == len(ap)-1) || (i == len(ap)-1 && j == 0) {
				continue
			}
			for dy := -2; dy <= 2; dy++ {
				for dx := -2; dx <= 2; dx++ {
					m.Set(cx+dx, cy+dy, max(abs(dx), abs(dy)) != 1)
				}
			}
		}
	}
	m.Set(8, n-8, true)
	if l.Version >= 7 {
		code := versionCode(l.Version)
		for i := 0; i < 18; i++ {
			b := code>>uint(i)&1 == 1
			a, c := n-11+i%3, i/3
			m.Set(a, c, b)
			m.Set(c, a, b)
		}
	}
}

func drawFormat(m *Matrix, e ECC, mask int) {
	code := formatCode(e, mask)
	for i := 0; i < 15; i++ {
		b := code>>uint(i)&1 == 1
		x, y := formatPos1(i)
		m.Set(x, y, b)
		x, y = formatPos2(i, m.N)
		m.Set(x, y, b)
	}
}
