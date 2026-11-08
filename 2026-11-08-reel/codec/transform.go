package codec

// 4x4 integer core transform and quantiser, in the style of H.264/AVC.
// qstep doubles every 6 QP: qstep(qp) = 2^((qp-4)/6).

const (
	MinQP = 0
	MaxQP = 51
)

var mfTab = [6][3]int32{
	{13107, 5243, 8066}, {11916, 4660, 7490}, {10082, 4194, 6554},
	{9362, 3647, 5825}, {8192, 3355, 5243}, {7282, 2893, 4559},
}
var vTab = [6][3]int32{
	{10, 16, 13}, {11, 18, 14}, {13, 20, 16}, {14, 23, 18}, {16, 25, 20}, {18, 29, 23},
}

// posClass: 0 for (even,even), 1 for (odd,odd), 2 otherwise.
var posClass [16]int

// zigzag maps scan position -> raster index (4x4).
var zigzag = [16]int{0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15}

func init() {
	for i := 0; i < 16; i++ {
		x, y := i&3, i>>2
		switch {
		case x&1 == 0 && y&1 == 0:
			posClass[i] = 0
		case x&1 == 1 && y&1 == 1:
			posClass[i] = 1
		default:
			posClass[i] = 2
		}
	}
}

// fdct4 is the forward core transform: W = Cf * X * Cf^T.
func fdct4(in *[16]int32, out *[16]int32) {
	var t [16]int32
	for r := 0; r < 4; r++ { // rows
		a, b, c, d := in[r*4], in[r*4+1], in[r*4+2], in[r*4+3]
		s0, s1, d0, d1 := a+d, b+c, a-d, b-c
		t[r*4+0] = s0 + s1
		t[r*4+1] = 2*d0 + d1
		t[r*4+2] = s0 - s1
		t[r*4+3] = d0 - 2*d1
	}
	for c := 0; c < 4; c++ { // columns
		a, b, cc, d := t[c], t[4+c], t[8+c], t[12+c]
		s0, s1, d0, d1 := a+d, b+cc, a-d, b-cc
		out[c] = s0 + s1
		out[4+c] = 2*d0 + d1
		out[8+c] = s0 - s1
		out[12+c] = d0 - 2*d1
	}
}

// idct4 is the inverse core transform of already-dequantised coefficients,
// returning residual samples (includes the final (x+32)>>6 rounding).
func idct4(in *[16]int32, out *[16]int32) {
	var t [16]int32
	for r := 0; r < 4; r++ {
		d0, d1, d2, d3 := in[r*4], in[r*4+1], in[r*4+2], in[r*4+3]
		e0, e1 := d0+d2, d0-d2
		e2, e3 := (d1>>1)-d3, d1+(d3>>1)
		t[r*4+0], t[r*4+1], t[r*4+2], t[r*4+3] = e0+e3, e1+e2, e1-e2, e0-e3
	}
	for c := 0; c < 4; c++ {
		d0, d1, d2, d3 := t[c], t[4+c], t[8+c], t[12+c]
		e0, e1 := d0+d2, d0-d2
		e2, e3 := (d1>>1)-d3, d1+(d3>>1)
		out[c] = (e0 + e3 + 32) >> 6
		out[4+c] = (e1 + e2 + 32) >> 6
		out[8+c] = (e1 - e2 + 32) >> 6
		out[12+c] = (e0 - e3 + 32) >> 6
	}
}

// quant quantises transform coefficients (raster order) into levels (raster
// order). intra selects the dead-zone rounding offset. Returns the number of
// non-zero levels.
func quant(w *[16]int32, lev *[16]int32, qp int, intra bool) int {
	qbits := uint(15 + qp/6)
	var f int64 = (1 << qbits) / 6
	if intra {
		f = (1 << qbits) / 3
	}
	n := 0
	for i := 0; i < 16; i++ {
		mf := int64(mfTab[qp%6][posClass[i]])
		a := int64(w[i])
		neg := a < 0
		if neg {
			a = -a
		}
		l := int32((a*mf + f) >> qbits)
		if neg {
			l = -l
		}
		lev[i] = l
		if l != 0 {
			n++
		}
	}
	return n
}

// dequant scales levels back to transform-domain coefficients.
func dequant(lev *[16]int32, out *[16]int32, qp int) {
	sh := uint(qp / 6)
	for i := 0; i < 16; i++ {
		out[i] = (lev[i] * vTab[qp%6][posClass[i]]) << sh
	}
}

// Qstep returns the nominal quantiser step for a QP.
func Qstep(qp int) float64 {
	return pow2(float64(qp-4) / 6)
}
