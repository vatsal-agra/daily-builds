package qr

import (
	"errors"
	"fmt"
)

// ErrTooManyErrors is returned when a codeword block is beyond repair.
var ErrTooManyErrors = errors.New("qr: too many errors to correct")

var genCache = map[int][]byte{}

// RSEncode returns the `ecc` Reed-Solomon parity bytes for data.
func RSEncode(data []byte, ecc int) []byte {
	g, ok := genCache[ecc]
	if !ok {
		g = generatorPoly(ecc)
		genCache[ecc] = g
	}
	rem := make([]byte, ecc)
	for _, d := range data {
		f := d ^ rem[0]
		copy(rem, rem[1:])
		rem[ecc-1] = 0
		if f != 0 {
			for i := 0; i < ecc; i++ {
				rem[i] ^= GFMul(g[i+1], f)
			}
		}
	}
	return rem
}

// syndromes returns S_j = msg(alpha^j) for j in [0,ecc); all zero means valid.
func syndromes(msg []byte, ecc int) ([]byte, bool) {
	s := make([]byte, ecc)
	clean := true
	for j := 0; j < ecc; j++ {
		s[j] = polyEval(msg, GFPow(j))
		if s[j] != 0 {
			clean = false
		}
	}
	return s, clean
}

// RSDecodeResult describes a correction.
type RSDecodeResult struct {
	Positions []int // corrected byte indices into the block (data then parity)
}

// RSDecode corrects msg (data followed by ecc parity bytes) in place.
// erasures lists byte indices known to be unreliable. It handles
// 2*errors + erasures <= ecc. On success the corrected positions are
// returned; on failure ErrTooManyErrors (msg may be left modified-free).
func RSDecode(msg []byte, ecc int, erasures []int) (RSDecodeResult, error) {
	n := len(msg)
	if ecc <= 0 || n <= ecc || n > 255 {
		return RSDecodeResult{}, fmt.Errorf("qr: bad RS block (len %d, ecc %d)", n, ecc)
	}
	seen := map[int]bool{}
	var er []int
	for _, e := range erasures {
		if e < 0 || e >= n {
			return RSDecodeResult{}, fmt.Errorf("qr: erasure index %d out of range", e)
		}
		if !seen[e] {
			seen[e] = true
			er = append(er, e)
		}
	}
	if len(er) > ecc {
		return RSDecodeResult{}, ErrTooManyErrors
	}
	s, clean := syndromes(msg, ecc)
	if clean {
		return RSDecodeResult{}, nil
	}
	// Locator of known erasures: prod (1 - x*alpha^(n-1-pos)); coefficients lowest-first.
	gamma := []byte{1}
	for _, p := range er {
		gamma = lpMul(gamma, []byte{1, GFPow(n - 1 - p)})
	}
	// Forney syndromes T(x) = S(x)*gamma(x) mod x^ecc  (lowest-first).
	t := lpMul(s, gamma)
	t = t[:ecc]
	// Berlekamp-Massey on the modified syndromes, skipping the first len(er).
	lambda := []byte{1}
	b := []byte{1}
	L, m := 0, 1
	var bb byte = 1
	for k := len(er); k < ecc; k++ {
		var d byte = t[k]
		for i := 1; i <= L && i < len(lambda); i++ {
			d ^= GFMul(lambda[i], t[k-i])
		}
		if d == 0 {
			m++
			continue
		}
		coef := GFDiv(d, bb)
		tmp := append([]byte(nil), lambda...)
		lambda = lpAddShift(lambda, b, coef, m)
		if 2*L <= k-len(er) {
			L = k - len(er) + 1 - L
			b = tmp
			bb = d
			m = 1
		} else {
			m++
		}
	}
	if 2*L+len(er) > ecc {
		return RSDecodeResult{}, ErrTooManyErrors
	}
	// Chien search: position p is an error when lambda(alpha^-(n-1-p)) == 0.
	var errPos []int
	for p := 0; p < n; p++ {
		x := GFPow(-(n - 1 - p))
		var v byte
		for i := len(lambda) - 1; i >= 0; i-- {
			v = GFMul(v, x) ^ lambda[i]
		}
		if v == 0 {
			errPos = append(errPos, p)
		}
	}
	if len(errPos) != L {
		return RSDecodeResult{}, ErrTooManyErrors
	}
	all := append(append([]int(nil), er...), errPos...)
	// Full locator psi = lambda*gamma, evaluator omega = S*psi mod x^ecc.
	psi := lpMul(lambda, gamma)
	omega := lpMul(s, psi)[:ecc]
	// Forney: e = X^(1-0) * omega(X^-1) / psi'(X^-1) with first root alpha^0 => factor X^(1-b), b=0.
	out := append([]byte(nil), msg...)
	for _, p := range all {
		xi := GFPow(n - 1 - p)
		xinv := GFInv(xi)
		var num byte
		for i := len(omega) - 1; i >= 0; i-- {
			num = GFMul(num, xinv) ^ omega[i]
		}
		var den byte // formal derivative: odd-power terms only
		for i := 1; i < len(psi); i += 2 {
			den ^= GFMul(psi[i], gfPowN(xinv, i-1))
		}
		if den == 0 {
			return RSDecodeResult{}, ErrTooManyErrors
		}
		out[p] ^= GFMul(xi, GFDiv(num, den))
	}
	if _, ok := syndromes(out, ecc); !ok {
		return RSDecodeResult{}, ErrTooManyErrors
	}
	copy(msg, out)
	return RSDecodeResult{Positions: dedupeSorted(all)}, nil
}

func gfPowN(x byte, n int) byte {
	if n == 0 {
		return 1
	}
	if x == 0 {
		return 0
	}
	return GFPow(gfLog[x] * n)
}

// lpMul multiplies lowest-first polynomials.
func lpMul(a, b []byte) []byte {
	out := make([]byte, len(a)+len(b)-1)
	for i, x := range a {
		if x == 0 {
			continue
		}
		for j, y := range b {
			out[i+j] ^= GFMul(x, y)
		}
	}
	return out
}

// lpAddShift returns a + coef * x^shift * b (lowest-first).
func lpAddShift(a, b []byte, coef byte, shift int) []byte {
	n := len(a)
	if len(b)+shift > n {
		n = len(b) + shift
	}
	out := make([]byte, n)
	copy(out, a)
	for i, y := range b {
		out[i+shift] ^= GFMul(coef, y)
	}
	for len(out) > 1 && out[len(out)-1] == 0 {
		out = out[:len(out)-1]
	}
	return out
}

func dedupeSorted(a []int) []int {
	m := map[int]bool{}
	for _, v := range a {
		m[v] = true
	}
	out := make([]int, 0, len(m))
	for v := range m {
		out = append(out, v)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
