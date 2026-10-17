package deflate

import (
	"encoding/binary"

	"kolmo/internal/crc"
)

// Gzip wraps a DEFLATE stream in an RFC 1952 member.
func Gzip(src []byte, level int) []byte {
	xfl := byte(0)
	switch level {
	case 9:
		xfl = 2
	case 1:
		xfl = 4
	}
	out := []byte{0x1f, 0x8b, 8, 0, 0, 0, 0, 0, xfl, 255}
	out = append(out, Compress(src, level)...)
	out = binary.LittleEndian.AppendUint32(out, crc.Sum(src))
	return binary.LittleEndian.AppendUint32(out, uint32(len(src)))
}

// Gunzip decodes one or more concatenated gzip members.
func Gunzip(data []byte, maxOut int) ([]byte, error) {
	var all []byte
	if len(data) == 0 {
		return nil, corrupt("empty gzip input")
	}
	for len(data) > 0 {
		if len(data) < 18 || data[0] != 0x1f || data[1] != 0x8b {
			return nil, corrupt("bad gzip magic or truncated member")
		}
		if data[2] != 8 {
			return nil, corrupt("unknown compression method %d", data[2])
		}
		flg := data[3]
		p := 10
		if flg&4 != 0 { // FEXTRA
			if len(data) < p+2 {
				return nil, corrupt("truncated extra field")
			}
			p += 2 + int(binary.LittleEndian.Uint16(data[p:]))
		}
		for _, bit := range []byte{8, 16} { // FNAME, FCOMMENT: zero-terminated
			if flg&bit != 0 {
				for p < len(data) && data[p] != 0 {
					p++
				}
				p++
			}
		}
		if flg&2 != 0 { // FHCRC
			p += 2
		}
		if p >= len(data) {
			return nil, corrupt("truncated header")
		}
		rem := maxOut
		if maxOut > 0 {
			rem = maxOut - len(all)
		}
		out, used, err := Inflate(data[p:], rem)
		if err != nil {
			return nil, err
		}
		p += used
		if len(data) < p+8 {
			return nil, corrupt("truncated trailer")
		}
		if binary.LittleEndian.Uint32(data[p:]) != crc.Sum(out) {
			return nil, corrupt("CRC-32 mismatch")
		}
		if binary.LittleEndian.Uint32(data[p+4:]) != uint32(len(out)) {
			return nil, corrupt("ISIZE mismatch")
		}
		all = append(all, out...)
		data = data[p+8:]
	}
	return all, nil
}
