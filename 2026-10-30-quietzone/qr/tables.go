package qr

// ECC is an error-correction level.
type ECC int

// Levels, in the order of the 2-bit format-info indicator mapping below.
const (
	L ECC = iota
	M
	Q
	H
)

func (e ECC) String() string { return "LMQH"[e : e+1] }

// formatBits is the 2-bit indicator stored in the format information.
func (e ECC) formatBits() int { return [4]int{1, 0, 3, 2}[e] }

func eccFromFormatBits(b int) ECC { return [4]ECC{M, L, H, Q}[b&3] }

// ParseECC parses "L", "M", "Q" or "H" (case-insensitive).
func ParseECC(s string) (ECC, bool) {
	switch s {
	case "L", "l":
		return L, true
	case "M", "m":
		return M, true
	case "Q", "q":
		return Q, true
	case "H", "h":
		return H, true
	}
	return 0, false
}

// Index 0 unused. Values from ISO/IEC 18004 Table 9, per level [L,M,Q,H].
var eccPerBlock = [4][41]int{
	{0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30},
	{0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28},
	{0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30},
	{0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30},
}

var numBlocks = [4][41]int{
	{0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25},
	{0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49},
	{0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68},
	{0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81},
}

// Size returns the symbol side length in modules.
func Size(version int) int { return 17 + 4*version }

// rawModules is the number of modules available for data+ECC+remainder bits.
func rawModules(v int) int {
	r := (16*v+128)*v + 64
	if v >= 2 {
		na := v/7 + 2
		r -= (25*na-10)*na - 55
		if v >= 7 {
			r -= 36
		}
	}
	return r
}

// RawCodewords is the total codeword count (data + ECC) for a version.
func RawCodewords(v int) int { return rawModules(v) / 8 }

// DataCodewords returns the data capacity in bytes of version v at level e.
func DataCodewords(v int, e ECC) int {
	return RawCodewords(v) - eccPerBlock[e][v]*numBlocks[e][v]
}

// blockLayout returns, for each block, its data length; ecc length is fixed per block.
func blockLayout(v int, e ECC) (dataLens []int, eccLen int) {
	nb := numBlocks[e][v]
	eccLen = eccPerBlock[e][v]
	raw := RawCodewords(v)
	short := nb - raw%nb
	shortLen := raw/nb - eccLen
	for i := 0; i < nb; i++ {
		if i < short {
			dataLens = append(dataLens, shortLen)
		} else {
			dataLens = append(dataLens, shortLen+1)
		}
	}
	return
}

// alignPositions returns the alignment-pattern centre coordinates for v.
func alignPositions(v int) []int {
	if v == 1 {
		return nil
	}
	n := v/7 + 2
	step := 26
	if v != 32 {
		step = (v*4 + n*2 + 1) / (n*2 - 2) * 2
	}
	res := make([]int, n)
	res[0] = 6
	for i, pos := n-1, Size(v)-7; i >= 1; i, pos = i-1, pos-step {
		res[i] = pos
	}
	return res
}

// AlignPositions exposes the alignment-pattern centre coordinates of a version
// (used by the image scanner for grid refinement).
func AlignPositions(version int) []int { return alignPositions(version) }
