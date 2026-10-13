package tls13

import (
	"crypto/subtle"
	"encoding/binary"
	"errors"
	"math/bits"
)

// ChaCha20-Poly1305 AEAD (RFC 8439), written from the RFC: the standard library does not
// expose it outside crypto/tls internals.

func quarter(a, b, c, d uint32) (uint32, uint32, uint32, uint32) {
	a += b
	d = bits.RotateLeft32(d^a, 16)
	c += d
	b = bits.RotateLeft32(b^c, 12)
	a += b
	d = bits.RotateLeft32(d^a, 8)
	c += d
	b = bits.RotateLeft32(b^c, 7)
	return a, b, c, d
}

func chachaBlock(out *[64]byte, key *[32]byte, counter uint32, nonce *[12]byte) {
	var s [16]uint32
	s[0], s[1], s[2], s[3] = 0x61707865, 0x3320646e, 0x79622d32, 0x6b206574
	for i := 0; i < 8; i++ {
		s[4+i] = binary.LittleEndian.Uint32(key[4*i:])
	}
	s[12] = counter
	for i := 0; i < 3; i++ {
		s[13+i] = binary.LittleEndian.Uint32(nonce[4*i:])
	}
	x := s
	for i := 0; i < 10; i++ {
		x[0], x[4], x[8], x[12] = quarter(x[0], x[4], x[8], x[12])
		x[1], x[5], x[9], x[13] = quarter(x[1], x[5], x[9], x[13])
		x[2], x[6], x[10], x[14] = quarter(x[2], x[6], x[10], x[14])
		x[3], x[7], x[11], x[15] = quarter(x[3], x[7], x[11], x[15])
		x[0], x[5], x[10], x[15] = quarter(x[0], x[5], x[10], x[15])
		x[1], x[6], x[11], x[12] = quarter(x[1], x[6], x[11], x[12])
		x[2], x[7], x[8], x[13] = quarter(x[2], x[7], x[8], x[13])
		x[3], x[4], x[9], x[14] = quarter(x[3], x[4], x[9], x[14])
	}
	for i := range x {
		binary.LittleEndian.PutUint32(out[4*i:], x[i]+s[i])
	}
}

func chachaXOR(dst, src []byte, key *[32]byte, counter uint32, nonce *[12]byte) {
	var blk [64]byte
	for len(src) > 0 {
		chachaBlock(&blk, key, counter, nonce)
		counter++
		n := len(src)
		if n > 64 {
			n = 64
		}
		for i := 0; i < n; i++ {
			dst[i] = src[i] ^ blk[i]
		}
		src, dst = src[n:], dst[n:]
	}
}

// poly1305 computes the one-time authenticator using 5x26-bit limbs.
func poly1305(key *[32]byte, msg []byte) (tag [16]byte) {
	le := binary.LittleEndian.Uint32
	t0, t1, t2, t3 := le(key[0:]), le(key[4:]), le(key[8:]), le(key[12:])
	r0 := t0 & 0x3ffffff
	r1 := ((t0 >> 26) | (t1 << 6)) & 0x3ffff03
	r2 := ((t1 >> 20) | (t2 << 12)) & 0x3ffc0ff
	r3 := ((t2 >> 14) | (t3 << 18)) & 0x3f03fff
	r4 := (t3 >> 8) & 0x00fffff
	s1, s2, s3, s4 := r1*5, r2*5, r3*5, r4*5
	var h0, h1, h2, h3, h4 uint32

	for len(msg) > 0 {
		var blk [16]byte
		var hibit uint32 = 1 << 24
		if len(msg) >= 16 {
			copy(blk[:], msg[:16])
			msg = msg[16:]
		} else {
			copy(blk[:], msg)
			blk[len(msg)] = 1
			msg = nil
			hibit = 0
		}
		m0, m1, m2, m3 := le(blk[0:]), le(blk[4:]), le(blk[8:]), le(blk[12:])
		h0 += m0 & 0x3ffffff
		h1 += ((m0 >> 26) | (m1 << 6)) & 0x3ffffff
		h2 += ((m1 >> 20) | (m2 << 12)) & 0x3ffffff
		h3 += ((m2 >> 14) | (m3 << 18)) & 0x3ffffff
		h4 += (m3 >> 8) | hibit

		d0 := uint64(h0)*uint64(r0) + uint64(h1)*uint64(s4) + uint64(h2)*uint64(s3) + uint64(h3)*uint64(s2) + uint64(h4)*uint64(s1)
		d1 := uint64(h0)*uint64(r1) + uint64(h1)*uint64(r0) + uint64(h2)*uint64(s4) + uint64(h3)*uint64(s3) + uint64(h4)*uint64(s2)
		d2 := uint64(h0)*uint64(r2) + uint64(h1)*uint64(r1) + uint64(h2)*uint64(r0) + uint64(h3)*uint64(s4) + uint64(h4)*uint64(s3)
		d3 := uint64(h0)*uint64(r3) + uint64(h1)*uint64(r2) + uint64(h2)*uint64(r1) + uint64(h3)*uint64(r0) + uint64(h4)*uint64(s4)
		d4 := uint64(h0)*uint64(r4) + uint64(h1)*uint64(r3) + uint64(h2)*uint64(r2) + uint64(h3)*uint64(r1) + uint64(h4)*uint64(r0)

		c := d0 >> 26
		h0 = uint32(d0) & 0x3ffffff
		d1 += c
		c = d1 >> 26
		h1 = uint32(d1) & 0x3ffffff
		d2 += c
		c = d2 >> 26
		h2 = uint32(d2) & 0x3ffffff
		d3 += c
		c = d3 >> 26
		h3 = uint32(d3) & 0x3ffffff
		d4 += c
		c = d4 >> 26
		h4 = uint32(d4) & 0x3ffffff
		h0 += uint32(c) * 5
		c32 := h0 >> 26
		h0 &= 0x3ffffff
		h1 += c32
	}

	// full carry
	c := h1 >> 26
	h1 &= 0x3ffffff
	h2 += c
	c = h2 >> 26
	h2 &= 0x3ffffff
	h3 += c
	c = h3 >> 26
	h3 &= 0x3ffffff
	h4 += c
	c = h4 >> 26
	h4 &= 0x3ffffff
	h0 += c * 5
	c = h0 >> 26
	h0 &= 0x3ffffff
	h1 += c

	// compute h + -p
	g0 := h0 + 5
	c = g0 >> 26
	g0 &= 0x3ffffff
	g1 := h1 + c
	c = g1 >> 26
	g1 &= 0x3ffffff
	g2 := h2 + c
	c = g2 >> 26
	g2 &= 0x3ffffff
	g3 := h3 + c
	c = g3 >> 26
	g3 &= 0x3ffffff
	g4 := h4 + c - (1 << 26)

	mask := (g4 >> 31) - 1 // all ones if h >= p (g4 did not underflow)
	g0 &= mask
	g1 &= mask
	g2 &= mask
	g3 &= mask
	g4 &= mask
	mask = ^mask
	h0 = (h0 & mask) | g0
	h1 = (h1 & mask) | g1
	h2 = (h2 & mask) | g2
	h3 = (h3 & mask) | g3
	h4 = (h4 & mask) | g4

	// h = h % 2^128
	f0 := uint64(h0|h1<<26) + uint64(le(key[16:]))
	f1 := uint64(h1>>6|h2<<20) + uint64(le(key[20:])) + (f0 >> 32)
	f2 := uint64(h2>>12|h3<<14) + uint64(le(key[24:])) + (f1 >> 32)
	f3 := uint64(h3>>18|h4<<8) + uint64(le(key[28:])) + (f2 >> 32)
	binary.LittleEndian.PutUint32(tag[0:], uint32(f0))
	binary.LittleEndian.PutUint32(tag[4:], uint32(f1))
	binary.LittleEndian.PutUint32(tag[8:], uint32(f2))
	binary.LittleEndian.PutUint32(tag[12:], uint32(f3))
	return
}

type chachaPoly struct{ key [32]byte }

func newChaCha20Poly1305(key []byte) (*chachaPoly, error) {
	if len(key) != 32 {
		return nil, errors.New("chacha20poly1305: bad key length")
	}
	c := &chachaPoly{}
	copy(c.key[:], key)
	return c, nil
}

func (c *chachaPoly) NonceSize() int { return 12 }
func (c *chachaPoly) Overhead() int  { return 16 }

func (c *chachaPoly) tag(nonce *[12]byte, aad, ct []byte) [16]byte {
	var otk [64]byte
	chachaBlock(&otk, &c.key, 0, nonce)
	var pk [32]byte
	copy(pk[:], otk[:32])
	pad := func(n int) int { return (16 - n%16) % 16 }
	mac := make([]byte, 0, len(aad)+len(ct)+32)
	mac = append(mac, aad...)
	mac = append(mac, make([]byte, pad(len(aad)))...)
	mac = append(mac, ct...)
	mac = append(mac, make([]byte, pad(len(ct)))...)
	var l [16]byte
	binary.LittleEndian.PutUint64(l[0:], uint64(len(aad)))
	binary.LittleEndian.PutUint64(l[8:], uint64(len(ct)))
	mac = append(mac, l[:]...)
	return poly1305(&pk, mac)
}

func (c *chachaPoly) Seal(dst, nonce, plaintext, aad []byte) []byte {
	if len(nonce) != 12 {
		panic("chacha20poly1305: bad nonce length")
	}
	var n [12]byte
	copy(n[:], nonce)
	ct := make([]byte, len(plaintext))
	chachaXOR(ct, plaintext, &c.key, 1, &n)
	t := c.tag(&n, aad, ct)
	dst = append(dst, ct...)
	return append(dst, t[:]...)
}

var errOpen = errors.New("tls13: message authentication failed")

func (c *chachaPoly) Open(dst, nonce, ciphertext, aad []byte) ([]byte, error) {
	if len(nonce) != 12 {
		panic("chacha20poly1305: bad nonce length")
	}
	if len(ciphertext) < 16 {
		return nil, errOpen
	}
	var n [12]byte
	copy(n[:], nonce)
	ct, tag := ciphertext[:len(ciphertext)-16], ciphertext[len(ciphertext)-16:]
	want := c.tag(&n, aad, ct)
	if subtle.ConstantTimeCompare(want[:], tag) != 1 {
		return nil, errOpen
	}
	out := make([]byte, len(ct))
	chachaXOR(out, ct, &c.key, 1, &n)
	return append(dst, out...), nil
}
