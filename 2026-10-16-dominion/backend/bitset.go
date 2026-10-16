package backend

type bitset []uint64

func newBitset(n int) bitset       { return make(bitset, (n+63)/64) }
func (b bitset) has(i int) bool    { return b[i>>6]>>(uint(i)&63)&1 != 0 }
func (b bitset) set(i int)         { b[i>>6] |= 1 << (uint(i) & 63) }
func (b bitset) clear(i int)       { b[i>>6] &^= 1 << (uint(i) & 63) }
func (b bitset) copyFrom(o bitset) { copy(b, o) }
func (b bitset) or(o bitset) bool {
	ch := false
	for i := range b {
		n := b[i] | o[i]
		if n != b[i] {
			b[i] = n
			ch = true
		}
	}
	return ch
}
func (b bitset) each(f func(i int)) {
	for w, x := range b {
		for x != 0 {
			t := x & -x
			bit := 0
			for y := t; y > 1; y >>= 1 {
				bit++
			}
			f(w*64 + bit)
			x &^= t
		}
	}
}
