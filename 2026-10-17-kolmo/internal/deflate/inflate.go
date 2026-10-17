package deflate

import (
	"errors"
	"fmt"

	"kolmo/internal/bitio"
	"kolmo/internal/huff"
)

// ErrCorrupt wraps all malformed-stream errors.
var ErrCorrupt = errors.New("deflate: corrupt stream")

func corrupt(format string, a ...any) error {
	return fmt.Errorf("%w: %s", ErrCorrupt, fmt.Sprintf(format, a...))
}

// Inflate decodes a raw DEFLATE stream. maxOut bounds the output (<=0 means 1 GiB).
// It returns the output and the number of input bytes consumed.
func Inflate(data []byte, maxOut int) ([]byte, int, error) {
	if maxOut <= 0 {
		maxOut = 1 << 30
	}
	r := bitio.NewReader(data)
	out := make([]byte, 0, len(data)*3)
	fixL, _ := huff.NewDecoder(fixedLitLens())
	fixD, _ := huff.NewDecoder(fixedDistLens())
	for {
		hdr, err := r.ReadBits(3)
		if err != nil {
			return nil, 0, corrupt("missing block header")
		}
		final := hdr&1 == 1
		switch hdr >> 1 {
		case 0:
			r.Align()
			v, err := r.ReadBits(32)
			if err != nil {
				return nil, 0, corrupt("truncated stored header")
			}
			n, nn := int(v&0xffff), int(v>>16)
			if n != ^nn&0xffff {
				return nil, 0, corrupt("stored block length check failed")
			}
			if len(out)+n > maxOut {
				return nil, 0, corrupt("output exceeds limit")
			}
			b, err := r.ReadBytes(n)
			if err != nil {
				return nil, 0, corrupt("truncated stored block")
			}
			out = append(out, b...)
		case 1:
			if out, err = inflateBlock(r, out, fixL, fixD, maxOut); err != nil {
				return nil, 0, err
			}
		case 2:
			lit, dist, err := readDynamic(r)
			if err != nil {
				return nil, 0, err
			}
			if out, err = inflateBlock(r, out, lit, dist, maxOut); err != nil {
				return nil, 0, err
			}
		default:
			return nil, 0, corrupt("reserved block type")
		}
		if final {
			break
		}
	}
	r.Align()
	return out, r.BytePos(), nil
}

func readDynamic(r *bitio.Reader) (*huff.Decoder, *huff.Decoder, error) {
	v, err := r.ReadBits(14)
	if err != nil {
		return nil, nil, corrupt("truncated dynamic header")
	}
	hlit, hdist, hclen := int(v&31)+257, int(v>>5&31)+1, int(v>>10)+4
	if hlit > 286 || hdist > 30 {
		return nil, nil, corrupt("too many length/distance codes")
	}
	clLens := make([]uint8, 19)
	for i := 0; i < hclen; i++ {
		b, err := r.ReadBits(3)
		if err != nil {
			return nil, nil, corrupt("truncated code length lengths")
		}
		clLens[clOrder[i]] = uint8(b)
	}
	cl, err := huff.NewDecoder(clLens)
	if err != nil {
		return nil, nil, corrupt("bad code length code")
	}
	lens := make([]uint8, 0, hlit+hdist)
	for len(lens) < hlit+hdist {
		s, err := cl.Decode(r)
		if err != nil {
			return nil, nil, corrupt("bad code length symbol")
		}
		var rep int
		var val uint8
		switch {
		case s < 16:
			lens = append(lens, uint8(s))
			continue
		case s == 16:
			if len(lens) == 0 {
				return nil, nil, corrupt("repeat with no previous length")
			}
			b, e := r.ReadBits(2)
			if e != nil {
				return nil, nil, corrupt("truncated repeat")
			}
			rep, val = int(b)+3, lens[len(lens)-1]
		case s == 17:
			b, e := r.ReadBits(3)
			if e != nil {
				return nil, nil, corrupt("truncated repeat")
			}
			rep = int(b) + 3
		default:
			b, e := r.ReadBits(7)
			if e != nil {
				return nil, nil, corrupt("truncated repeat")
			}
			rep = int(b) + 11
		}
		if len(lens)+rep > hlit+hdist {
			return nil, nil, corrupt("code length repeat overflows")
		}
		for ; rep > 0; rep-- {
			lens = append(lens, val)
		}
	}
	if lens[256] == 0 {
		return nil, nil, corrupt("no end-of-block code")
	}
	lit, err := huff.NewDecoder(lens[:hlit])
	if err != nil {
		return nil, nil, corrupt("bad literal/length code")
	}
	dist, err := huff.NewDecoder(lens[hlit:])
	if err != nil {
		return nil, nil, corrupt("bad distance code")
	}
	return lit, dist, nil
}

func inflateBlock(r *bitio.Reader, out []byte, lit, dist *huff.Decoder, maxOut int) ([]byte, error) {
	for {
		s, err := lit.Decode(r)
		if err != nil {
			return nil, corrupt("bad literal/length symbol")
		}
		if s < 256 {
			if len(out) >= maxOut {
				return nil, corrupt("output exceeds limit")
			}
			out = append(out, byte(s))
			continue
		}
		if s == 256 {
			return out, nil
		}
		s -= 257
		if s >= 29 {
			return nil, corrupt("invalid length symbol")
		}
		eb, err := r.ReadBits(uint(lenExtra[s]))
		if err != nil {
			return nil, corrupt("truncated length")
		}
		length := int(lenBase[s]) + int(eb)
		ds, err := dist.Decode(r)
		if err != nil || ds >= 30 {
			return nil, corrupt("bad distance symbol")
		}
		eb, err = r.ReadBits(uint(distExtra[ds]))
		if err != nil {
			return nil, corrupt("truncated distance")
		}
		d := int(distBase[ds]) + int(eb)
		if d > len(out) {
			return nil, corrupt("distance %d reaches before start of output", d)
		}
		if len(out)+length > maxOut {
			return nil, corrupt("output exceeds limit")
		}
		start := len(out) - d
		for k := 0; k < length; k++ { // byte-wise: matches may overlap their own output
			out = append(out, out[start+k])
		}
	}
}
