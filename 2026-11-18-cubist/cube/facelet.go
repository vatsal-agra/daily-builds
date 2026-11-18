package cube

import (
	"fmt"
	"strings"
)

// Facelet layout: 54 letters, faces in order U R F D L B, each face read row by row
// as seen from outside with U's top toward B and the other faces' tops toward U.
const (
	u1 = 0
	r1 = 9
	f1 = 18
	d1 = 27
	l1 = 36
	b1 = 45
)

var cornerFacelet = [8][3]int{
	{u1 + 8, r1 + 0, f1 + 2}, {u1 + 6, f1 + 0, l1 + 2}, {u1 + 0, l1 + 0, b1 + 2}, {u1 + 2, b1 + 0, r1 + 2},
	{d1 + 2, f1 + 8, r1 + 6}, {d1 + 0, l1 + 8, f1 + 6}, {d1 + 6, b1 + 8, l1 + 6}, {d1 + 8, r1 + 8, b1 + 6},
}

var edgeFacelet = [12][2]int{
	{u1 + 5, r1 + 1}, {u1 + 7, f1 + 1}, {u1 + 3, l1 + 1}, {u1 + 1, b1 + 1},
	{d1 + 5, r1 + 7}, {d1 + 1, f1 + 7}, {d1 + 3, l1 + 7}, {d1 + 7, b1 + 7},
	{f1 + 5, r1 + 3}, {f1 + 3, l1 + 5}, {b1 + 5, l1 + 3}, {b1 + 3, r1 + 5},
}

var cornerColor = [8][3]byte{
	{'U', 'R', 'F'}, {'U', 'F', 'L'}, {'U', 'L', 'B'}, {'U', 'B', 'R'},
	{'D', 'F', 'R'}, {'D', 'L', 'F'}, {'D', 'B', 'L'}, {'D', 'R', 'B'},
}

var edgeColor = [12][2]byte{
	{'U', 'R'}, {'U', 'F'}, {'U', 'L'}, {'U', 'B'}, {'D', 'R'}, {'D', 'F'}, {'D', 'L'}, {'D', 'B'},
	{'F', 'R'}, {'F', 'L'}, {'B', 'L'}, {'B', 'R'},
}

// SolvedFacelets is the facelet string of the solved cube.
const SolvedFacelets = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"

// Facelets renders the cube as a 54-letter string.
func (c Cube) Facelets() string {
	var f [54]byte
	for i := 0; i < 6; i++ {
		for j := 0; j < 9; j++ {
			f[i*9+j] = faceLetters[i]
		}
	}
	for i := 0; i < 8; i++ {
		for n := 0; n < 3; n++ {
			f[cornerFacelet[i][(n+int(c.CO[i]))%3]] = cornerColor[c.CP[i]][n]
		}
	}
	for i := 0; i < 12; i++ {
		for n := 0; n < 2; n++ {
			f[edgeFacelet[i][(n+int(c.EO[i]))%2]] = edgeColor[c.EP[i]][n]
		}
	}
	return string(f[:])
}

// ParseFacelets converts a 54-letter facelet string into a cubie cube and validates it.
// Errors explain what is wrong with the cube in plain words.
func ParseFacelets(s string) (Cube, error) {
	s = strings.ToUpper(strings.Join(strings.Fields(s), ""))
	if len(s) != 54 {
		return Cube{}, fmt.Errorf("facelet string must have 54 letters (U R F D L B), got %d", len(s))
	}
	counts := map[byte]int{}
	for i := 0; i < 54; i++ {
		if !strings.ContainsRune(faceLetters, rune(s[i])) {
			return Cube{}, fmt.Errorf("invalid letter %q at position %d (use only U R F D L B)", s[i], i+1)
		}
		counts[s[i]]++
	}
	for i := 0; i < 6; i++ {
		if counts[faceLetters[i]] != 9 {
			return Cube{}, fmt.Errorf("each color must appear exactly 9 times, but %c appears %d times", faceLetters[i], counts[faceLetters[i]])
		}
	}
	for i := 0; i < 6; i++ {
		if s[i*9+4] != faceLetters[i] {
			return Cube{}, fmt.Errorf("center of face %c (position %d) is %c; centers are fixed and must read U R F D L B in order", faceLetters[i], i*9+5, s[i*9+4])
		}
	}
	var c Cube
	usedC := [8]bool{}
	for i := 0; i < 8; i++ {
		ori := -1
		for o := 0; o < 3; o++ {
			ch := s[cornerFacelet[i][o]]
			if ch == 'U' || ch == 'D' {
				ori = o
				break
			}
		}
		if ori < 0 {
			return Cube{}, fmt.Errorf("corner at position %s has no U/D sticker: %s", cornerName(i), cornerStickers(s, i))
		}
		c1 := s[cornerFacelet[i][(ori+1)%3]]
		c2 := s[cornerFacelet[i][(ori+2)%3]]
		found := false
		for j := 0; j < 8; j++ {
			if c1 == cornerColor[j][1] && c2 == cornerColor[j][2] {
				if usedC[j] {
					return Cube{}, fmt.Errorf("corner %s appears twice (second time at position %s)", cornerLabel(j), cornerName(i))
				}
				usedC[j] = true
				c.CP[i] = uint8(j)
				c.CO[i] = uint8(ori)
				found = true
				break
			}
		}
		if !found {
			return Cube{}, fmt.Errorf("corner at position %s shows %s, which is not a real corner piece (mirror-image colors or opposite faces together)", cornerName(i), cornerStickers(s, i))
		}
	}
	usedE := [12]bool{}
	for i := 0; i < 12; i++ {
		a, b := s[edgeFacelet[i][0]], s[edgeFacelet[i][1]]
		found := false
		for j := 0; j < 12; j++ {
			for o := 0; o < 2; o++ {
				if a == edgeColor[j][o] && b == edgeColor[j][1-o] {
					if usedE[j] {
						return Cube{}, fmt.Errorf("edge %s appears twice (second time at position %s)", edgeLabel(j), edgeName(i))
					}
					usedE[j] = true
					c.EP[i] = uint8(j)
					c.EO[i] = uint8(o)
					found = true
				}
			}
		}
		if !found {
			return Cube{}, fmt.Errorf("edge at position %s shows %c%c, which is not a real edge piece", edgeName(i), a, b)
		}
	}
	if err := c.Check(); err != nil {
		return Cube{}, err
	}
	return c, nil
}

// Check verifies the three solvability invariants of a cubie cube.
func (c Cube) Check() error {
	var seenC [8]bool
	var seenE [12]bool
	for _, p := range c.CP {
		if p > 7 || seenC[p] {
			return fmt.Errorf("corner permutation is not a permutation")
		}
		seenC[p] = true
	}
	for _, p := range c.EP {
		if p > 11 || seenE[p] {
			return fmt.Errorf("edge permutation is not a permutation")
		}
		seenE[p] = true
	}
	tw, fl := 0, 0
	for _, o := range c.CO {
		tw += int(o)
	}
	for _, o := range c.EO {
		fl += int(o)
	}
	if tw%3 != 0 {
		return fmt.Errorf("unsolvable: a corner is twisted in place (twist sum %d is not a multiple of 3) — one corner would have to be rotated by hand", tw)
	}
	if fl%2 != 0 {
		return fmt.Errorf("unsolvable: a single edge is flipped in place (flip count %d is odd)", fl)
	}
	if parity(c.CP[:]) != parity(c.EP[:]) {
		return fmt.Errorf("unsolvable: parity error — exactly two pieces are swapped (corner and edge permutation parities differ)")
	}
	return nil
}

var posCornerNames = [8]string{"URF", "UFL", "ULB", "UBR", "DFR", "DLF", "DBL", "DRB"}
var posEdgeNames = [12]string{"UR", "UF", "UL", "UB", "DR", "DF", "DL", "DB", "FR", "FL", "BL", "BR"}

func cornerName(i int) string  { return posCornerNames[i] }
func cornerLabel(j int) string { return posCornerNames[j] }
func edgeName(i int) string    { return posEdgeNames[i] }
func edgeLabel(j int) string   { return posEdgeNames[j] }
func cornerStickers(s string, i int) string {
	return fmt.Sprintf("%c%c%c", s[cornerFacelet[i][0]], s[cornerFacelet[i][1]], s[cornerFacelet[i][2]])
}
