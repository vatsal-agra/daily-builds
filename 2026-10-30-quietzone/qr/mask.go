package qr

func maskBit(mask, x, y int) bool {
	switch mask {
	case 0:
		return (x+y)%2 == 0
	case 1:
		return y%2 == 0
	case 2:
		return x%3 == 0
	case 3:
		return (x+y)%3 == 0
	case 4:
		return (x/3+y/2)%2 == 0
	case 5:
		return x*y%2+x*y%3 == 0
	case 6:
		return (x*y%2+x*y%3)%2 == 0
	default:
		return ((x+y)%2+x*y%3)%2 == 0
	}
}

// applyMask XORs mask over every non-function module.
func applyMask(m *Matrix, l *Layout, mask int) {
	for y := 0; y < m.N; y++ {
		for x := 0; x < m.N; x++ {
			if !l.IsFunction(x, y) && maskBit(mask, x, y) {
				m.Set(x, y, !m.Get(x, y))
			}
		}
	}
}

// Penalty computes the ISO 18004 N1+N2+N3+N4 mask-evaluation score.
func Penalty(m *Matrix) int {
	p := PenaltyParts(m)
	return p[0] + p[1] + p[2] + p[3]
}

// PenaltyParts returns the four rule scores N1..N4 separately.
func PenaltyParts(m *Matrix) (parts [4]int) {
	n := m.N
	// N1: runs of >=5 same-colour modules in rows and columns.
	// N3: 1:1:3:1:1 finder-like pattern bounded by 4 light modules.
	line := make([]bool, n)
	padded := make([]bool, n+8) // the quiet zone counts as light modules around every row and column
	for dir := 0; dir < 2; dir++ {
		for a := 0; a < n; a++ {
			for b := 0; b < n; b++ {
				if dir == 0 {
					line[b] = m.Get(b, a)
				} else {
					line[b] = m.Get(a, b)
				}
			}
			run := 1
			for i := 1; i <= n; i++ {
				if i < n && line[i] == line[i-1] {
					run++
					continue
				}
				if run >= 5 {
					parts[0] += 3 + run - 5
				}
				run = 1
			}
			copy(padded[4:], line)
			// ISO 18004 7.8.3: the 1:1:3:1:1 core "preceded or followed by" four light
			// modules scores once, however many sides are light.
			// Overlapping cores are resolved like the reference implementations: a
			// scored core is consumed whole, an unscored one only up to its first
			// four modules.
			for i := 0; i+7 <= n; {
				if !matchCore(padded[i+4 : i+11]) {
					i++
					continue
				}
				if allLight(padded[i:i+4]) || allLight(padded[i+11:i+15]) {
					parts[2] += 40
					i += 7
				} else {
					i += 4
				}
			}
		}
	}
	// N2: 2x2 blocks of one colour.
	for y := 0; y+1 < n; y++ {
		for x := 0; x+1 < n; x++ {
			c := m.Get(x, y)
			if c == m.Get(x+1, y) && c == m.Get(x, y+1) && c == m.Get(x+1, y+1) {
				parts[1] += 3
			}
		}
	}
	// N4: deviation of dark proportion from 50%, 10 points per started 5%.
	dark := 0
	for _, v := range m.m {
		if v {
			dark++
		}
	}
	all := n * n
	k := (abs(dark*20-all*10)+all-1)/all - 1
	parts[3] = k * 10
	return parts
}

func matchCore(w []bool) bool {
	return w[0] && !w[1] && w[2] && w[3] && w[4] && !w[5] && w[6]
}

func allLight(w []bool) bool {
	for _, v := range w {
		if v {
			return false
		}
	}
	return true
}
