package cube

import "sync"

// Coordinate sizes.
const (
	nTwist = 2187  // 3^7
	nFlip  = 2048  // 2^11
	nSlice = 495   // C(12,4): which positions hold the four E-slice edges
	nPerm8 = 40320 // 8!
	nPerm4 = 24
	nP2    = 10 // phase-2 moves
)

const solvedSlice = 494

// phase2Moves are the moves that preserve the subgroup <U,D,R2,L2,F2,B2>.
var phase2Moves = [nP2]int{0, 1, 2, 9, 10, 11, 4, 7, 13, 16}

var binom [13][5]int

func init() {
	for n := 0; n <= 12; n++ {
		binom[n][0] = 1
		for k := 1; k <= 4; k++ {
			if n == 0 {
				continue
			}
			binom[n][k] = binom[n-1][k-1] + binom[n-1][k]
		}
	}
}

func (c Cube) twist() int {
	t := 0
	for i := 0; i < 7; i++ {
		t = 3*t + int(c.CO[i])
	}
	return t
}

func (c *Cube) setTwist(t int) {
	s := 0
	for i := 6; i >= 0; i-- {
		c.CO[i] = uint8(t % 3)
		s += t % 3
		t /= 3
	}
	c.CO[7] = uint8((3 - s%3) % 3)
}

func (c Cube) flip() int {
	t := 0
	for i := 0; i < 11; i++ {
		t = 2*t + int(c.EO[i])
	}
	return t
}

func (c *Cube) setFlip(t int) {
	s := 0
	for i := 10; i >= 0; i-- {
		c.EO[i] = uint8(t % 2)
		s += t % 2
		t /= 2
	}
	c.EO[11] = uint8(s % 2)
}

// slice rank: combinatorial number system over the sorted positions of edges 8..11.
func (c Cube) slice() int {
	r, k := 0, 0
	for i := 0; i < 12; i++ {
		if c.EP[i] >= 8 {
			k++
			r += binom[i][k]
		}
	}
	return r
}

func (c *Cube) setSlice(r int) {
	var inSlice [12]bool
	for k := 4; k >= 1; k-- {
		p := 11
		for binom[p][k] > r {
			p--
		}
		r -= binom[p][k]
		inSlice[p] = true
	}
	s, o := uint8(8), uint8(0)
	for i := 0; i < 12; i++ {
		if inSlice[i] {
			c.EP[i] = s
			s++
		} else {
			c.EP[i] = o
			o++
		}
	}
}

func permRank(p []uint8) int {
	n := len(p)
	r := 0
	for i := 0; i < n; i++ {
		c := 0
		for j := i + 1; j < n; j++ {
			if p[j] < p[i] {
				c++
			}
		}
		r = r*(n-i) + c
	}
	return r
}

func permUnrank(dst []uint8, r int) {
	n := len(dst)
	var digits [8]int
	for i := n - 1; i >= 0; i-- {
		digits[i] = r % (n - i)
		r /= n - i
	}
	var avail [8]uint8
	for i := 0; i < n; i++ {
		avail[i] = uint8(i)
	}
	m := n
	for i := 0; i < n; i++ {
		d := digits[i]
		dst[i] = avail[d]
		copy(avail[d:m], avail[d+1:m])
		m--
	}
}

func (c Cube) cpRank() int { return permRank(c.CP[:]) }
func (c Cube) udRank() int { return permRank(c.EP[:8]) }
func (c Cube) spRank() int {
	var t [4]uint8
	for i := 0; i < 4; i++ {
		t[i] = c.EP[8+i] - 8
	}
	return permRank(t[:])
}

// Tables hold every move table and pruning table of the two-phase solver.
type Tables struct {
	twistMove [nTwist][18]uint16
	flipMove  [nFlip][18]uint16
	sliceMove [nSlice][18]uint16
	cpMove    [nPerm8][nP2]uint16
	udMove    [nPerm8][nP2]uint16
	spMove    [nPerm4][nP2]uint16
	pruneTS   []uint8 // twist x slice  -> distance to G1
	pruneFS   []uint8 // flip  x slice
	pruneCS   []uint8 // corner perm x slice perm -> distance within G1
	pruneUS   []uint8 // ud-edge perm x slice perm
}

var (
	tables     *Tables
	tablesOnce sync.Once
)

// GetTables builds (once) and returns the shared tables. Takes roughly a second.
func GetTables() *Tables {
	tablesOnce.Do(func() { tables = buildTables() })
	return tables
}

func buildTables() *Tables {
	t := &Tables{}
	for i := 0; i < nTwist; i++ {
		c := Solved()
		c.setTwist(i)
		for m := 0; m < 18; m++ {
			d := c.Mul(MoveCube[m])
			t.twistMove[i][m] = uint16(d.twist())
		}
	}
	for i := 0; i < nFlip; i++ {
		c := Solved()
		c.setFlip(i)
		for m := 0; m < 18; m++ {
			d := c.Mul(MoveCube[m])
			t.flipMove[i][m] = uint16(d.flip())
		}
	}
	for i := 0; i < nSlice; i++ {
		c := Solved()
		c.setSlice(i)
		for m := 0; m < 18; m++ {
			d := c.Mul(MoveCube[m])
			t.sliceMove[i][m] = uint16(d.slice())
		}
	}
	for i := 0; i < nPerm8; i++ {
		c := Solved()
		permUnrank(c.CP[:], i)
		e := Solved()
		permUnrank(e.EP[:8], i)
		for j, m := range phase2Moves {
			t.cpMove[i][j] = uint16(c.Mul(MoveCube[m]).cpRank())
			t.udMove[i][j] = uint16(e.Mul(MoveCube[m]).udRank())
		}
	}
	for i := 0; i < nPerm4; i++ {
		c := Solved()
		var s [4]uint8
		permUnrank(s[:], i)
		for k := 0; k < 4; k++ {
			c.EP[8+k] = 8 + s[k]
		}
		for j, m := range phase2Moves {
			t.spMove[i][j] = uint16(c.Mul(MoveCube[m]).spRank())
		}
	}
	t.pruneTS = bfsPrune(nTwist, nSlice, 18, 0*nSlice+solvedSlice,
		func(a, m int) int { return int(t.twistMove[a][m]) }, func(b, m int) int { return int(t.sliceMove[b][m]) })
	t.pruneFS = bfsPrune(nFlip, nSlice, 18, 0*nSlice+solvedSlice,
		func(a, m int) int { return int(t.flipMove[a][m]) }, func(b, m int) int { return int(t.sliceMove[b][m]) })
	t.pruneCS = bfsPrune(nPerm8, nPerm4, nP2, 0,
		func(a, m int) int { return int(t.cpMove[a][m]) }, func(b, m int) int { return int(t.spMove[b][m]) })
	t.pruneUS = bfsPrune(nPerm8, nPerm4, nP2, 0,
		func(a, m int) int { return int(t.udMove[a][m]) }, func(b, m int) int { return int(t.spMove[b][m]) })
	return t
}

// bfsPrune computes exact distances in the product of two coordinates from the start state.
func bfsPrune(n1, n2, nm, start int, mv1, mv2 func(int, int) int) []uint8 {
	tab := make([]uint8, n1*n2)
	for i := range tab {
		tab[i] = 255
	}
	tab[start] = 0
	filled := 1
	for depth := uint8(0); filled < n1*n2; depth++ {
		for idx := 0; idx < n1*n2; idx++ {
			if tab[idx] != depth {
				continue
			}
			a, b := idx/n2, idx%n2
			for m := 0; m < nm; m++ {
				ni := mv1(a, m)*n2 + mv2(b, m)
				if tab[ni] == 255 {
					tab[ni] = depth + 1
					filled++
				}
			}
		}
	}
	return tab
}
