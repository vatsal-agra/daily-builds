package sketch

import (
	"encoding/binary"
	"math/bits"
)

// xxHash64, implemented from the public specification.
const (
	p1 uint64 = 11400714785074694791
	p2 uint64 = 14029467366897019727
	p3 uint64 = 1609587929392839161
	p4 uint64 = 9650029242287828579
	p5 uint64 = 2870177450012600261
)

func xxRound(acc, in uint64) uint64 {
	acc += in * p2
	return bits.RotateLeft64(acc, 31) * p1
}

func xxMerge(acc, v uint64) uint64 {
	acc ^= xxRound(0, v)
	return acc*p1 + p4
}

// Hash64 returns the xxHash64 of b with the given seed.
func Hash64(b []byte, seed uint64) uint64 {
	n := len(b)
	var h uint64
	i := 0
	if n >= 32 {
		v1 := seed + p1 + p2
		v2 := seed + p2
		v3 := seed
		v4 := seed - p1
		for ; i+32 <= n; i += 32 {
			v1 = xxRound(v1, binary.LittleEndian.Uint64(b[i:]))
			v2 = xxRound(v2, binary.LittleEndian.Uint64(b[i+8:]))
			v3 = xxRound(v3, binary.LittleEndian.Uint64(b[i+16:]))
			v4 = xxRound(v4, binary.LittleEndian.Uint64(b[i+24:]))
		}
		h = bits.RotateLeft64(v1, 1) + bits.RotateLeft64(v2, 7) + bits.RotateLeft64(v3, 12) + bits.RotateLeft64(v4, 18)
		h = xxMerge(h, v1)
		h = xxMerge(h, v2)
		h = xxMerge(h, v3)
		h = xxMerge(h, v4)
	} else {
		h = seed + p5
	}
	h += uint64(n)
	for ; i+8 <= n; i += 8 {
		h ^= xxRound(0, binary.LittleEndian.Uint64(b[i:]))
		h = bits.RotateLeft64(h, 27)*p1 + p4
	}
	if i+4 <= n {
		h ^= uint64(binary.LittleEndian.Uint32(b[i:])) * p1
		h = bits.RotateLeft64(h, 23)*p2 + p3
		i += 4
	}
	for ; i < n; i++ {
		h ^= uint64(b[i]) * p5
		h = bits.RotateLeft64(h, 11) * p1
	}
	h ^= h >> 33
	h *= p2
	h ^= h >> 29
	h *= p3
	h ^= h >> 32
	return h
}

// Mix64 is the splitmix64 finaliser: a cheap bijective bit mixer.
func Mix64(x uint64) uint64 {
	x += 0x9e3779b97f4a7c15
	x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9
	x = (x ^ (x >> 27)) * 0x94d049bb133111eb
	return x ^ (x >> 31)
}

// pair derives two independent-ish 64-bit hashes for double hashing
// (Kirsch–Mitzenmacher): g_i(x) = h1 + i*h2.
func pair(b []byte) (uint64, uint64) {
	h := Hash64(b, 0)
	return h, Mix64(h) | 1
}
