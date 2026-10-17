// Package crc implements CRC-32 (IEEE 802.3, reflected, poly 0xEDB88320) from scratch.
package crc

var table = func() (t [8][256]uint32) {
	for i := 0; i < 256; i++ {
		c := uint32(i)
		for k := 0; k < 8; k++ {
			if c&1 == 1 {
				c = c>>1 ^ 0xEDB88320
			} else {
				c >>= 1
			}
		}
		t[0][i] = c
	}
	// slicing-by-8 tables
	for i := 0; i < 256; i++ {
		c := t[0][i]
		for k := 1; k < 8; k++ {
			c = t[0][c&0xff] ^ c>>8
			t[k][i] = c
		}
	}
	return
}()

// Update folds p into a running CRC (start with 0).
func Update(crc uint32, p []byte) uint32 {
	crc = ^crc
	for len(p) >= 8 {
		crc ^= uint32(p[0]) | uint32(p[1])<<8 | uint32(p[2])<<16 | uint32(p[3])<<24
		crc = table[7][crc&0xff] ^ table[6][crc>>8&0xff] ^ table[5][crc>>16&0xff] ^ table[4][crc>>24] ^
			table[3][p[4]] ^ table[2][p[5]] ^ table[1][p[6]] ^ table[0][p[7]]
		p = p[8:]
	}
	for _, b := range p {
		crc = table[0][byte(crc)^b] ^ crc>>8
	}
	return ^crc
}

// Sum returns the CRC-32 of p.
func Sum(p []byte) uint32 { return Update(0, p) }
