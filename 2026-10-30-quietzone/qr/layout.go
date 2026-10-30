package qr

// Matrix is a square grid of modules; true = dark.
type Matrix struct {
	N int
	m []bool
}

// NewMatrix returns an all-light n x n matrix.
func NewMatrix(n int) *Matrix { return &Matrix{N: n, m: make([]bool, n*n)} }

// Get returns the module at column x, row y.
func (m *Matrix) Get(x, y int) bool { return m.m[y*m.N+x] }

// Set sets the module at column x, row y.
func (m *Matrix) Set(x, y int, v bool) { m.m[y*m.N+x] = v }

// Clone returns a deep copy.
func (m *Matrix) Clone() *Matrix {
	c := NewMatrix(m.N)
	copy(c.m, m.m)
	return c
}

// Kind classifies a module's role, used by the explainer and decoder.
type Kind uint8

// Module roles.
const (
	KData Kind = iota
	KFinder
	KSeparator
	KTiming
	KAlign
	KFormat
	KVersion
	KDark // the always-dark module
)

// Layout classifies every module of a given version.
type Layout struct {
	Version int
	N       int
	kind    []Kind
	fn      []bool
}

// NewLayout builds the function-pattern map for a version.
func NewLayout(version int) *Layout {
	n := Size(version)
	l := &Layout{Version: version, N: n, kind: make([]Kind, n*n), fn: make([]bool, n*n)}
	mark := func(x, y int, k Kind) {
		if x >= 0 && y >= 0 && x < n && y < n {
			l.kind[y*n+x] = k
			l.fn[y*n+x] = true
		}
	}
	for i := 0; i < n; i++ {
		mark(6, i, KTiming)
		mark(i, 6, KTiming)
	}
	for _, c := range [][2]int{{3, 3}, {n - 4, 3}, {3, n - 4}} {
		for dy := -4; dy <= 4; dy++ {
			for dx := -4; dx <= 4; dx++ {
				d := max(abs(dx), abs(dy))
				if d == 4 {
					mark(c[0]+dx, c[1]+dy, KSeparator)
				} else {
					mark(c[0]+dx, c[1]+dy, KFinder)
				}
			}
		}
	}
	ap := alignPositions(version)
	for i, cy := range ap {
		for j, cx := range ap {
			if (i == 0 && j == 0) || (i == 0 && j == len(ap)-1) || (i == len(ap)-1 && j == 0) {
				continue
			}
			for dy := -2; dy <= 2; dy++ {
				for dx := -2; dx <= 2; dx++ {
					mark(cx+dx, cy+dy, KAlign)
				}
			}
		}
	}
	// format info: two copies of 15 bits
	for i := 0; i < 15; i++ {
		x, y := formatPos1(i)
		mark(x, y, KFormat)
		x, y = formatPos2(i, n)
		mark(x, y, KFormat)
	}
	mark(8, n-8, KDark)
	if version >= 7 {
		for i := 0; i < 18; i++ {
			a, b := n-11+i%3, i/3
			mark(a, b, KVersion)
			mark(b, a, KVersion)
		}
	}
	return l
}

// IsFunction reports whether (x,y) is part of a function pattern.
func (l *Layout) IsFunction(x, y int) bool { return l.fn[y*l.N+x] }

// KindAt returns the module's role.
func (l *Layout) KindAt(x, y int) Kind { return l.kind[y*l.N+x] }

// formatPos1 gives the i-th (0 = LSB) format bit position in the copy around the top-left finder.
func formatPos1(i int) (int, int) {
	if i < 6 {
		return 8, i
	}
	if i == 6 {
		return 8, 7
	}
	if i == 7 {
		return 8, 8
	}
	if i == 8 {
		return 7, 8
	}
	return 14 - i, 8
}

// formatPos2 gives the i-th format bit in the split copy (top-right / bottom-left).
func formatPos2(i, n int) (int, int) {
	if i < 8 {
		return n - 1 - i, 8
	}
	return 8, n - 15 + i
}

// DataOrder returns the zig-zag order of all non-function modules (data+remainder).
func (l *Layout) DataOrder() [][2]int {
	n := l.N
	out := make([][2]int, 0, rawModules(l.Version))
	for right := n - 1; right >= 1; right -= 2 {
		if right == 6 {
			right = 5
		}
		up := (right+1)&2 == 0 // column pairs alternate direction, first pair upward
		for v := 0; v < n; v++ {
			y := v
			if up {
				y = n - 1 - v
			}
			for j := 0; j < 2; j++ {
				x := right - j
				if !l.fn[y*n+x] {
					out = append(out, [2]int{x, y})
				}
			}
		}
	}
	return out
}

func abs(a int) int {
	if a < 0 {
		return -a
	}
	return a
}

// ---- BCH codes -------------------------------------------------------

// formatCode returns the masked 15-bit format word for (level, mask).
func formatCode(e ECC, mask int) int {
	data := e.formatBits()<<3 | mask
	rem := data
	for i := 0; i < 10; i++ {
		rem = (rem << 1) ^ ((rem >> 9) * 0x537)
	}
	return (data<<10 | rem) ^ 0x5412
}

// versionCode returns the 18-bit version information word (version >= 7).
func versionCode(v int) int {
	rem := v
	for i := 0; i < 12; i++ {
		rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
	}
	return v<<12 | rem
}

func popcount(x int) int {
	c := 0
	for ; x != 0; x &= x - 1 {
		c++
	}
	return c
}
