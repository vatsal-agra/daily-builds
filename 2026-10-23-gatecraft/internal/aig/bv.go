package aig

// Bit-vector construction helpers. A vector is []Lit with element 0 = LSB.

// Const builds a w-bit constant from the low bits of a uint64 (higher bits zero).
func Const(v uint64, w int) []Lit {
	r := make([]Lit, w)
	for i := range r {
		if i < 64 && v>>uint(i)&1 == 1 {
			r[i] = True
		}
	}
	return r
}

// Ext zero-extends or truncates to width w.
func Ext(a []Lit, w int) []Lit {
	r := make([]Lit, w)
	for i := range r {
		if i < len(a) {
			r[i] = a[i]
		}
	}
	return r
}

func (g *AIG) NotV(a []Lit) []Lit {
	r := make([]Lit, len(a))
	for i, x := range a {
		r[i] = x.Not()
	}
	return r
}

func (g *AIG) BitwiseV(op byte, a, b []Lit) []Lit {
	r := make([]Lit, len(a))
	for i := range r {
		switch op {
		case '&':
			r[i] = g.And(a[i], b[i])
		case '|':
			r[i] = g.Or(a[i], b[i])
		case '^':
			r[i] = g.Xor(a[i], b[i])
		case 'x': // xnor
			r[i] = g.Xnor(a[i], b[i])
		}
	}
	return r
}

func (g *AIG) MuxV(c Lit, t, f []Lit) []Lit {
	r := make([]Lit, len(t))
	for i := range r {
		r[i] = g.Mux(c, t[i], f[i])
	}
	return r
}

// AddC returns a+b+cin (len(a) bits) and the carry out.
func (g *AIG) AddC(a, b []Lit, cin Lit) ([]Lit, Lit) {
	r := make([]Lit, len(a))
	c := cin
	for i := range a {
		x := g.Xor(a[i], b[i])
		r[i] = g.Xor(x, c)
		c = g.Or(g.And(a[i], b[i]), g.And(x, c))
	}
	return r, c
}

func (g *AIG) AddV(a, b []Lit) []Lit { r, _ := g.AddC(a, b, False); return r }

// SubV returns a-b (mod 2^w) and a "no borrow" flag (a >= b).
func (g *AIG) SubV(a, b []Lit) ([]Lit, Lit) { return g.AddC(a, g.NotV(b), True) }

func (g *AIG) NegV(a []Lit) []Lit {
	r, _ := g.AddC(g.NotV(a), Const(0, len(a)), True)
	return r
}

// MulV is a shift-and-add multiplier truncated to len(a) bits.
func (g *AIG) MulV(a, b []Lit) []Lit {
	w := len(a)
	acc := Const(0, w)
	for j := 0; j < w; j++ {
		if b[j] == False {
			continue
		}
		part := make([]Lit, w)
		for i := 0; i < w; i++ {
			if i >= j {
				part[i] = g.And(a[i-j], b[j])
			}
		}
		acc = g.AddV(acc, part)
	}
	return acc
}

// DivModV is a restoring divider. Division by zero yields quotient all-ones and
// remainder = dividend (the RISC-V convention); documented in the README.
func (g *AIG) DivModV(a, b []Lit) (q, r []Lit) {
	w := len(a)
	q = make([]Lit, w)
	rem := Const(0, w+1)
	bb := Ext(b, w+1)
	for i := w - 1; i >= 0; i-- {
		shifted := make([]Lit, w+1)
		shifted[0] = a[i]
		copy(shifted[1:], rem[:w])
		diff, ge := g.SubV(shifted, bb)
		q[i] = ge
		rem = g.MuxV(ge, diff, shifted)
	}
	return q, rem[:w]
}

// EqV is a == b.
func (g *AIG) EqV(a, b []Lit) Lit {
	acc := True
	for i := range a {
		acc = g.And(acc, g.Xnor(a[i], b[i]))
	}
	return acc
}

// LtV is unsigned a < b.
func (g *AIG) LtV(a, b []Lit) Lit {
	_, ge := g.SubV(a, b)
	return ge.Not()
}

func (g *AIG) ReduceAnd(a []Lit) Lit {
	acc := True
	for _, x := range a {
		acc = g.And(acc, x)
	}
	return acc
}
func (g *AIG) ReduceOr(a []Lit) Lit {
	acc := False
	for _, x := range a {
		acc = g.Or(acc, x)
	}
	return acc
}
func (g *AIG) ReduceXor(a []Lit) Lit {
	acc := False
	for _, x := range a {
		acc = g.Xor(acc, x)
	}
	return acc
}

// ShiftV shifts a by the variable amount sh. left selects <<, otherwise logical >>.
func (g *AIG) ShiftV(a, sh []Lit, left bool) []Lit {
	w := len(a)
	cur := append([]Lit(nil), a...)
	overflow := False
	for k, s := range sh {
		amt := 1 << uint(k)
		if k >= 30 || amt >= w {
			overflow = g.Or(overflow, s)
			continue
		}
		next := make([]Lit, w)
		for i := 0; i < w; i++ {
			var shifted Lit
			if left {
				if i-amt >= 0 {
					shifted = cur[i-amt]
				}
			} else if i+amt < w {
				shifted = cur[i+amt]
			}
			next[i] = g.Mux(s, shifted, cur[i])
		}
		cur = next
	}
	for i := range cur {
		cur[i] = g.And(cur[i], overflow.Not())
	}
	return cur
}
