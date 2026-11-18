package cube

import "math/rand"

// RandomState returns a uniformly random *solvable* cube state.
func RandomState(r *rand.Rand) Cube {
	var c Cube
	cp := r.Perm(8)
	ep := r.Perm(12)
	for i, v := range cp {
		c.CP[i] = uint8(v)
	}
	for i, v := range ep {
		c.EP[i] = uint8(v)
	}
	if parity(c.CP[:]) != parity(c.EP[:]) {
		c.EP[0], c.EP[1] = c.EP[1], c.EP[0]
	}
	c.setTwist(r.Intn(nTwist))
	c.setFlip(r.Intn(nFlip))
	return c
}

// RandomMoves returns n random face turns with no two consecutive turns of the same face
// and no redundant opposite-face ordering (like a WCA-style scramble).
func RandomMoves(r *rand.Rand, n int) []Move {
	var out []Move
	last := -1
	for len(out) < n {
		f := r.Intn(6)
		if f == last || (last >= 3 && f == last-3) {
			continue
		}
		// also forbid X Y X for opposite pairs by checking two back
		if len(out) >= 2 && out[len(out)-2].Face() == f && (f+3)%6 == last {
			continue
		}
		out = append(out, Move(f*3+r.Intn(3)))
		last = f
	}
	return out
}
