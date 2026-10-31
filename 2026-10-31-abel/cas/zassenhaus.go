package cas

import (
	"math/big"
	"math/rand"
	"sort"
)

// Factoring of square-free primitive integer polynomials by the Zassenhaus algorithm:
// factor modulo a small prime (distinct-degree + Cantor–Zassenhaus equal-degree splitting),
// Hensel-lift the modular factors to a modulus beyond the Mignotte bound, then recombine subsets
// of lifted factors and keep those that divide the input over Z.

type zp []*big.Int // coefficients low -> high

func zNew(n int) zp {
	z := make(zp, n)
	for i := range z {
		z[i] = new(big.Int)
	}
	return z
}

func zTrim(a zp) zp {
	for len(a) > 0 && a[len(a)-1].Sign() == 0 {
		a = a[:len(a)-1]
	}
	return a
}

func zCopy(a zp) zp {
	out := make(zp, len(a))
	for i, c := range a {
		out[i] = new(big.Int).Set(c)
	}
	return out
}

func zMod(a zp, m *big.Int) zp {
	out := make(zp, len(a))
	for i, c := range a {
		out[i] = new(big.Int).Mod(c, m)
	}
	return zTrim(out)
}

func zAdd(a, b zp, m *big.Int) zp {
	n := len(a)
	if len(b) > n {
		n = len(b)
	}
	out := zNew(n)
	for i := range out {
		if i < len(a) {
			out[i].Add(out[i], a[i])
		}
		if i < len(b) {
			out[i].Add(out[i], b[i])
		}
		out[i].Mod(out[i], m)
	}
	return zTrim(out)
}

func zSub(a, b zp, m *big.Int) zp {
	n := len(a)
	if len(b) > n {
		n = len(b)
	}
	out := zNew(n)
	for i := range out {
		if i < len(a) {
			out[i].Add(out[i], a[i])
		}
		if i < len(b) {
			out[i].Sub(out[i], b[i])
		}
		out[i].Mod(out[i], m)
	}
	return zTrim(out)
}

func zMul(a, b zp, m *big.Int) zp {
	if len(a) == 0 || len(b) == 0 {
		return nil
	}
	out := zNew(len(a) + len(b) - 1)
	t := new(big.Int)
	for i := range a {
		if a[i].Sign() == 0 {
			continue
		}
		for j := range b {
			out[i+j].Add(out[i+j], t.Mul(a[i], b[j]))
		}
	}
	for _, c := range out {
		c.Mod(c, m)
	}
	return zTrim(out)
}

func zScale(a zp, c, m *big.Int) zp {
	out := make(zp, len(a))
	for i := range a {
		out[i] = new(big.Int).Mul(a[i], c)
		out[i].Mod(out[i], m)
	}
	return zTrim(out)
}

// zDivMod divides a by b modulo m (the leading coefficient of b must be invertible mod m).
func zDivMod(a, b zp, m *big.Int) (q, r zp) {
	r = zCopy(a)
	if len(b) == 0 {
		panic(MathError("modular division by zero polynomial"))
	}
	if len(a) < len(b) {
		return nil, zTrim(r)
	}
	inv := new(big.Int).ModInverse(b[len(b)-1], m)
	if inv == nil {
		panic(MathError("non-invertible leading coefficient"))
	}
	q = zNew(len(a) - len(b) + 1)
	t := new(big.Int)
	for len(r) >= len(b) {
		sh := len(r) - len(b)
		f := new(big.Int).Mul(r[len(r)-1], inv)
		f.Mod(f, m)
		q[sh] = f
		for i := range b {
			r[i+sh].Sub(r[i+sh], t.Mul(f, b[i]))
			r[i+sh].Mod(r[i+sh], m)
		}
		r = zTrim(r[:len(r)-1])
	}
	return zTrim(q), r
}

func zMonic(a zp, m *big.Int) zp {
	if len(a) == 0 {
		return a
	}
	inv := new(big.Int).ModInverse(a[len(a)-1], m)
	return zScale(a, inv, m)
}

func zGcd(a, b zp, m *big.Int) zp {
	a, b = zCopy(a), zCopy(b)
	for len(b) > 0 {
		_, r := zDivMod(a, b, m)
		a, b = b, r
	}
	return zMonic(a, m)
}

// zExtGcd returns monic g and s, t with s*a + t*b = g (mod m); m must be prime.
func zExtGcd(a, b zp, m *big.Int) (g, s, t zp) {
	r0, r1 := zCopy(a), zCopy(b)
	s0, s1 := zp{big.NewInt(1)}, zp(nil)
	t0, t1 := zp(nil), zp{big.NewInt(1)}
	for len(r1) > 0 {
		q, r := zDivMod(r0, r1, m)
		r0, r1 = r1, r
		s0, s1 = s1, zSub(s0, zMul(q, s1, m), m)
		t0, t1 = t1, zSub(t0, zMul(q, t1, m), m)
	}
	if len(r0) == 0 {
		return nil, nil, nil
	}
	inv := new(big.Int).ModInverse(r0[len(r0)-1], m)
	return zScale(r0, inv, m), zScale(s0, inv, m), zScale(t0, inv, m)
}

func zPowMod(base zp, e *big.Int, f zp, m *big.Int) zp {
	result := zp{big.NewInt(1)}
	b := zMod(base, m)
	_, b = zDivMod(b, f, m)
	for i := e.BitLen() - 1; i >= 0; i-- {
		result = zMul(result, result, m)
		_, result = zDivMod(result, f, m)
		if e.Bit(i) == 1 {
			result = zMul(result, b, m)
			_, result = zDivMod(result, f, m)
		}
	}
	return result
}

func zDeriv(a zp, m *big.Int) zp {
	if len(a) <= 1 {
		return nil
	}
	out := make(zp, len(a)-1)
	for i := 1; i < len(a); i++ {
		out[i-1] = new(big.Int).Mul(a[i], big.NewInt(int64(i)))
		out[i-1].Mod(out[i-1], m)
	}
	return zTrim(out)
}

func zEqual(a, b zp) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i].Cmp(b[i]) != 0 {
			return false
		}
	}
	return true
}

// ---------- factoring modulo a prime ----------

func zX() zp { return zp{big.NewInt(0), big.NewInt(1)} }

// equalDegree splits a monic square-free f whose irreducible factors all have degree d.
func equalDegree(f zp, d int, p *big.Int, rng *rand.Rand) []zp {
	n := len(f) - 1
	if n == d {
		return []zp{f}
	}
	exp := new(big.Int).Exp(p, big.NewInt(int64(d)), nil)
	exp.Sub(exp, big.NewInt(1))
	exp.Rsh(exp, 1)
	for {
		a := zNew(n)
		for i := range a {
			a[i].Rand(rng, p)
		}
		a = zTrim(a)
		if len(a) < 2 {
			continue
		}
		h := zPowMod(a, exp, f, p)
		h = zSub(h, zp{big.NewInt(1)}, p)
		g := zGcd(f, h, p)
		if len(g) > 1 && len(g) < len(f) {
			q, _ := zDivMod(f, g, p)
			return append(equalDegree(zMonic(g, p), d, p, rng), equalDegree(zMonic(q, p), d, p, rng)...)
		}
	}
}

// factorModP returns the monic irreducible factors of a square-free f modulo the odd prime p.
func factorModP(f zp, p *big.Int) []zp {
	rng := rand.New(rand.NewSource(12345))
	f = zMonic(f, p)
	var out []zp
	h := zX()
	rest := f
	for d := 1; 2*d <= len(rest)-1; d++ {
		h = zPowMod(h, p, rest, p)
		g := zGcd(rest, zSub(h, zX(), p), p)
		if len(g) > 1 {
			out = append(out, equalDegree(g, d, p, rng)...)
			rest, _ = zDivMod(rest, g, p)
			rest = zMonic(rest, p)
			_, h = zDivMod(h, rest, p)
		}
	}
	if len(rest) > 1 {
		out = append(out, rest)
	}
	return out
}

// ---------- Hensel lifting ----------

// henselPair lifts f ≡ g*h (mod p) with g monic and coprime to h to a modulus >= target.
func henselPair(f, g, h zp, p, target *big.Int) (G, H zp, M *big.Int) {
	m := new(big.Int).Set(p)
	_, s, t := zExtGcd(g, h, p)
	for m.Cmp(target) < 0 {
		m2 := new(big.Int).Mul(m, m)
		e := zSub(zMod(f, m2), zMul(g, h, m2), m2)
		q, r := zDivMod(zMul(s, e, m2), h, m2)
		gn := zAdd(zAdd(g, zMul(t, e, m2), m2), zMul(q, g, m2), m2)
		hn := zAdd(h, r, m2)
		b := zSub(zAdd(zMul(s, gn, m2), zMul(t, hn, m2), m2), zp{big.NewInt(1)}, m2)
		c, d := zDivMod(zMul(s, b, m2), hn, m2)
		sn := zSub(s, d, m2)
		tn := zSub(zSub(t, zMul(t, b, m2), m2), zMul(c, gn, m2), m2)
		g, h, s, t, m = gn, hn, sn, tn, m2
	}
	return g, h, m
}

// henselLift lifts a factorisation f ≡ prod(facs) (mod p), facs monic, to modulus >= target.
func henselLift(f zp, facs []zp, p, target *big.Int) ([]zp, *big.Int) {
	if len(facs) == 1 {
		m := new(big.Int).Set(p)
		for m.Cmp(target) < 0 {
			m.Mul(m, m)
		}
		return []zp{zMonic(zMod(f, m), m)}, m
	}
	half := len(facs) / 2
	g, h := zp{big.NewInt(1)}, zp{big.NewInt(1)}
	for _, x := range facs[:half] {
		g = zMul(g, x, p)
	}
	for _, x := range facs[half:] {
		h = zMul(h, x, p)
	}
	// f must be monic mod M for the recursion; callers pass the monic reduction.
	G, H, M := henselPair(f, g, h, p, target)
	left, _ := henselLift(G, facs[:half], p, M)
	right, _ := henselLift(H, facs[half:], p, M)
	return append(left, right...), M
}

func symmetric(a zp, m *big.Int) zp {
	half := new(big.Int).Rsh(m, 1)
	out := zCopy(a)
	for _, c := range out {
		c.Mod(c, m)
		if c.Cmp(half) > 0 {
			c.Sub(c, m)
		}
	}
	return zTrim(out)
}

func zToPoly(a zp) Poly {
	out := make(Poly, len(a))
	for i, c := range a {
		out[i] = new(big.Rat).SetInt(c)
	}
	return out
}

func polyToZ(p Poly) zp {
	out := make(zp, len(p))
	for i, c := range p {
		out[i] = new(big.Int).Set(c.Num())
	}
	return out
}

var smallOddPrimes = []int64{3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113}

// zassenhaus factors a square-free primitive integer polynomial (positive leading coefficient) into irreducibles.
func zassenhaus(f Poly) []Poly {
	n := f.Deg()
	if n <= 1 {
		return []Poly{f}
	}
	fz := polyToZ(f)
	lc := new(big.Int).Set(fz[n])
	// choose a prime giving few modular factors
	var bestP *big.Int
	var best []zp
	tried := 0
	for _, pi := range smallOddPrimes {
		p := big.NewInt(pi)
		if new(big.Int).Mod(lc, p).Sign() == 0 {
			continue
		}
		fm := zMod(fz, p)
		if len(fm) != len(fz) {
			continue
		}
		if g := zGcd(fm, zDeriv(fm, p), p); len(g) > 1 {
			continue // not square-free mod p
		}
		facs := factorModP(fm, p)
		if best == nil || len(facs) < len(best) {
			best, bestP = facs, p
		}
		tried++
		if len(best) == 1 || tried >= 6 {
			break
		}
	}
	if best == nil {
		fail("could not find a suitable prime for factoring")
	}
	if len(best) == 1 {
		return []Poly{f}
	}
	// Mignotte-style bound: M > 2 * |lc| * 2^n * ||f||_1
	norm := new(big.Int)
	for _, c := range fz {
		norm.Add(norm, new(big.Int).Abs(c))
	}
	target := new(big.Int).Mul(norm, new(big.Int).Abs(lc))
	target.Lsh(target, uint(n+2))
	// lift the monic reduction lc^-1 * f
	p := bestP
	sort.Slice(best, func(i, j int) bool { return len(best[i]) < len(best[j]) })
	// first lift modulo a modulus M, using f/lc mod M for monic-ness: do it in two steps so M is known
	// (the pair lifts square the modulus, so recompute f's monic form at the final modulus)
	M := new(big.Int).Set(p)
	for M.Cmp(target) < 0 {
		M.Mul(M, M)
	}
	invLc := new(big.Int).ModInverse(lc, M)
	fMonic := zScale(zMod(fz, M), invLc, M)
	lifted, M2 := henselLift(fMonic, best, p, M)
	_ = M2
	return recombine(fz, lifted, M2)
}

func recombine(fz zp, lifted []zp, M *big.Int) []Poly {
	var out []Poly
	cur := fz
	remaining := make([]int, len(lifted))
	for i := range remaining {
		remaining[i] = i
	}
	for s := 1; 2*s <= len(remaining); {
		found := false
		idx := make([]int, s)
		var rec func(start, k int) bool
		rec = func(start, k int) bool {
			if k == s {
				lcCur := cur[len(cur)-1]
				cand := zp{new(big.Int).Set(lcCur)}
				for _, i := range idx {
					cand = zMul(cand, lifted[remaining[i]], M)
				}
				cand = symmetric(cand, M)
				cp := zToPoly(cand)
				_, prim := primitiveInt(cp)
				if len(prim) == 0 {
					return false
				}
				q, r := pDivMod(zToPoly(cur), prim)
				if len(r) != 0 {
					return false
				}
				out = append(out, prim)
				_, qp := primitiveInt(q)
				cur = polyToZ(qp)
				var next []int
				used := map[int]bool{}
				for _, i := range idx {
					used[i] = true
				}
				for i, r := range remaining {
					if !used[i] {
						next = append(next, r)
					}
				}
				remaining = next
				return true
			}
			for i := start; i < len(remaining); i++ {
				idx[k] = i
				if rec(i+1, k+1) {
					return true
				}
			}
			return false
		}
		if rec(0, 0) {
			found = true
		}
		if !found {
			s++
		}
	}
	if len(cur) > 1 {
		_, prim := primitiveInt(zToPoly(cur))
		out = append(out, prim)
	}
	return out
}
