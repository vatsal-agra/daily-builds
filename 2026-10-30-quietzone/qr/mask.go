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
	n := m.N
	total := 0
	// N1: runs of >=5 same-colour modules in rows and columns.
	// N3: 1:1:3:1:1 finder-like pattern bounded by 4 light modules.
	line := make([]bool, n)
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
					total += 3 + run - 5
				}
				run = 1
			}
			for i := 0; i+11 <= n; i++ {
				if matchFinderLike(line[i:i+11], false) || matchFinderLike(line[i:i+11], true) {
					total += 40
				}
			}
		}
	}
	// N2: 2x2 blocks of one colour.
	for y := 0; y+1 < n; y++ {
		for x := 0; x+1 < n; x++ {
			c := m.Get(x, y)
			if c == m.Get(x+1, y) && c == m.Get(x, y+1) && c == m.Get(x+1, y+1) {
				total += 3
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
	total += k * 10
	return total
}

// 10111010000 or its mirror 00001011101 (dark = true).
func matchFinderLike(w []bool, mirror bool) bool {
	pat := [11]bool{true, false, true, true, true, false, true, false, false, false, false}
	for i := 0; i < 11; i++ {
		p := pat[i]
		if mirror {
			p = pat[10-i]
		}
		if w[i] != p {
			return false
		}
	}
	return true
}
