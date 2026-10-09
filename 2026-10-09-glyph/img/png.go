// Package img holds a small RGB canvas with gamma-correct blending and a
// from-scratch PNG encoder (chunk framing, CRC, adaptive scanline filters).
// zlib/crc32 from the standard library are used only as DEFLATE/CRC primitives.
package img

import (
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"io"
)

// EncodePNG writes an 8-bit PNG. channels: 1 = gray, 3 = RGB, 4 = RGBA.
func EncodePNG(w io.Writer, width, height, channels int, pix []byte) error {
	var ct byte
	switch channels {
	case 1:
		ct = 0
	case 3:
		ct = 2
	case 4:
		ct = 6
	default:
		return fmt.Errorf("png: unsupported channel count %d", channels)
	}
	if width <= 0 || height <= 0 {
		return fmt.Errorf("png: invalid size %dx%d", width, height)
	}
	if len(pix) != width*height*channels {
		return fmt.Errorf("png: pixel buffer is %d bytes, want %d", len(pix), width*height*channels)
	}
	if _, err := w.Write([]byte("\x89PNG\r\n\x1a\n")); err != nil {
		return err
	}
	var ihdr [13]byte
	binary.BigEndian.PutUint32(ihdr[0:], uint32(width))
	binary.BigEndian.PutUint32(ihdr[4:], uint32(height))
	ihdr[8], ihdr[9] = 8, ct
	if err := chunk(w, "IHDR", ihdr[:]); err != nil {
		return err
	}
	stride := width * channels
	var raw bytes.Buffer
	prev := make([]byte, stride)
	cands := [5][]byte{}
	for i := range cands {
		cands[i] = make([]byte, stride)
	}
	for y := 0; y < height; y++ {
		cur := pix[y*stride : (y+1)*stride]
		best, bestCost := 0, int(^uint(0)>>1)
		for ft := 0; ft < 5; ft++ {
			applyFilter(ft, cands[ft], cur, prev, channels)
			cost := 0
			for _, v := range cands[ft] { // min-sum-of-absolute-differences heuristic
				if v < 128 {
					cost += int(v)
				} else {
					cost += 256 - int(v)
				}
			}
			if cost < bestCost {
				best, bestCost = ft, cost
			}
		}
		raw.WriteByte(byte(best))
		raw.Write(cands[best])
		prev = cur
	}
	var z bytes.Buffer
	zw, _ := zlib.NewWriterLevel(&z, zlib.BestCompression)
	zw.Write(raw.Bytes())
	zw.Close()
	if err := chunk(w, "IDAT", z.Bytes()); err != nil {
		return err
	}
	return chunk(w, "IEND", nil)
}

func chunk(w io.Writer, typ string, data []byte) error {
	var hdr [8]byte
	binary.BigEndian.PutUint32(hdr[:], uint32(len(data)))
	copy(hdr[4:], typ)
	crc := crc32.NewIEEE()
	crc.Write(hdr[4:])
	crc.Write(data)
	var tail [4]byte
	binary.BigEndian.PutUint32(tail[:], crc.Sum32())
	for _, b := range [][]byte{hdr[:], data, tail[:]} {
		if _, err := w.Write(b); err != nil {
			return err
		}
	}
	return nil
}

func applyFilter(ft int, dst, cur, prev []byte, bpp int) {
	for i := range cur {
		var a, b, c byte
		if i >= bpp {
			a, c = cur[i-bpp], prev[i-bpp]
		}
		b = prev[i]
		switch ft {
		case 0:
			dst[i] = cur[i]
		case 1:
			dst[i] = cur[i] - a
		case 2:
			dst[i] = cur[i] - b
		case 3:
			dst[i] = cur[i] - byte((int(a)+int(b))/2)
		case 4:
			dst[i] = cur[i] - paeth(a, b, c)
		}
	}
}

func paeth(a, b, c byte) byte {
	p := int(a) + int(b) - int(c)
	pa, pb, pc := abs(p-int(a)), abs(p-int(b)), abs(p-int(c))
	switch {
	case pa <= pb && pa <= pc:
		return a
	case pb <= pc:
		return b
	}
	return c
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
