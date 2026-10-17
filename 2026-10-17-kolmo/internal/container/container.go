// Package container defines the KOL1 file format and the method registry that ties the
// codecs together:
//
//	"KOL1" | method u8 | uvarint original length | CRC-32 (LE) of original | payload
package container

import (
	"encoding/binary"
	"errors"
	"fmt"
	"sort"
	"sync"
	"time"

	"kolmo/internal/bwt"
	"kolmo/internal/cm"
	"kolmo/internal/crc"
	"kolmo/internal/deflate"
	"kolmo/internal/rans"
)

// Magic starts every Kolmo file.
const Magic = "KOL1"

// MaxOriginal bounds the declared decompressed size we are willing to allocate for.
const MaxOriginal = 1 << 30

// Method identifies a codec in the container.
type Method struct {
	ID     byte
	Name   string
	Desc   string
	encode func(src []byte, level int) []byte
	decode func(payload []byte, n int) ([]byte, error)
}

var methods = []*Method{
	{0, "store", "no compression", func(s []byte, _ int) []byte { return s },
		func(p []byte, n int) ([]byte, error) {
			if len(p) != n {
				return nil, errors.New("stored payload has wrong length")
			}
			return p, nil
		}},
	{1, "deflate", "LZ77 + Huffman (RFC 1951)",
		func(s []byte, lv int) []byte { return deflate.Compress(s, lv) },
		func(p []byte, n int) ([]byte, error) {
			out, used, err := deflate.Inflate(p, n)
			if err == nil && (used != len(p) || len(out) != n) {
				err = errors.New("deflate stream length mismatch")
			}
			return out, err
		}},
	{2, "bwt", "Burrows-Wheeler + MTF + RLE + Huffman",
		func(s []byte, _ int) []byte { return bwt.Encode(s) },
		func(p []byte, n int) ([]byte, error) { return bwt.Decode(p, n) }},
	{3, "cm", "context mixing + arithmetic coding",
		func(s []byte, _ int) []byte { return cm.Encode(s) },
		func(p []byte, n int) ([]byte, error) { return cm.Decode(p, n) }},
	{4, "rans0", "order-0 static rANS",
		func(s []byte, _ int) []byte { return rans.Encode(s, 0) },
		func(p []byte, n int) ([]byte, error) { return rans.Decode(p, n, 0) }},
	{5, "rans1", "order-1 static rANS",
		func(s []byte, _ int) []byte { return rans.Encode(s, 1) },
		func(p []byte, n int) ([]byte, error) { return rans.Decode(p, n, 1) }},
}

// Methods lists the registered codecs.
func Methods() []*Method { return methods }

// Lookup finds a method by name.
func Lookup(name string) *Method {
	for _, m := range methods {
		if m.Name == name {
			return m
		}
	}
	return nil
}

func byID(id byte) *Method {
	for _, m := range methods {
		if m.ID == id {
			return m
		}
	}
	return nil
}

// Encode packs src using m. level only matters to deflate (1-9).
func (m *Method) Encode(src []byte, level int) []byte {
	payload := m.encode(src, level)
	out := append([]byte(Magic), m.ID)
	out = binary.AppendUvarint(out, uint64(len(src)))
	out = binary.LittleEndian.AppendUint32(out, crc.Sum(src))
	return append(out, payload...)
}

// Result is one candidate produced by a method.
type Result struct {
	Method  *Method
	Data    []byte
	Elapsed time.Duration
}

// Try runs every method in parallel on src and returns the results sorted smallest-first.
// Methods named in skip are not run.
func Try(src []byte, level int, skip map[string]bool) []Result {
	var wg sync.WaitGroup
	var mu sync.Mutex
	var res []Result
	for _, m := range methods {
		if skip[m.Name] {
			continue
		}
		wg.Add(1)
		go func(m *Method) {
			defer wg.Done()
			t0 := time.Now()
			data := m.Encode(src, level)
			mu.Lock()
			res = append(res, Result{m, data, time.Since(t0)})
			mu.Unlock()
		}(m)
	}
	wg.Wait()
	sort.Slice(res, func(i, j int) bool {
		if len(res[i].Data) != len(res[j].Data) {
			return len(res[i].Data) < len(res[j].Data)
		}
		return res[i].Method.ID < res[j].Method.ID
	})
	return res
}

// Auto picks the smallest encoding. Inputs larger than slowLimit skip the slow cm model
// unless force is set.
func Auto(src []byte, level int) ([]byte, *Method) {
	res := Try(src, level, nil)
	return res[0].Data, res[0].Method
}

// Info describes a parsed container header.
type Info struct {
	Method       *Method
	Original     int
	CRC          uint32
	PayloadBytes int
}

// ErrFormat reports a malformed or unsupported container.
var ErrFormat = errors.New("kolmo: not a valid KOL1 file")

// Inspect parses the header only.
func Inspect(data []byte) (*Info, []byte, error) {
	if len(data) < 4+1+1+4 || string(data[:4]) != Magic {
		return nil, nil, ErrFormat
	}
	m := byID(data[4])
	if m == nil {
		return nil, nil, fmt.Errorf("%w: unknown method %d", ErrFormat, data[4])
	}
	n, k := binary.Uvarint(data[5:])
	if k <= 0 || n > MaxOriginal {
		return nil, nil, fmt.Errorf("%w: bad length field", ErrFormat)
	}
	rest := data[5+k:]
	if len(rest) < 4 {
		return nil, nil, fmt.Errorf("%w: truncated header", ErrFormat)
	}
	info := &Info{Method: m, Original: int(n), CRC: binary.LittleEndian.Uint32(rest), PayloadBytes: len(rest) - 4}
	return info, rest[4:], nil
}

// ErrChecksum is returned when decoded bytes do not match the stored CRC-32.
var ErrChecksum = errors.New("kolmo: CRC-32 mismatch — data is corrupt")

// Decode unpacks a KOL1 container, verifying the checksum. Plain gzip input is also accepted.
func Decode(data []byte) ([]byte, *Info, error) {
	if len(data) >= 2 && data[0] == 0x1f && data[1] == 0x8b {
		out, err := deflate.Gunzip(data, MaxOriginal)
		return out, &Info{Method: byID(1), Original: len(out), CRC: crc.Sum(out), PayloadBytes: len(data)}, err
	}
	info, payload, err := Inspect(data)
	if err != nil {
		return nil, nil, err
	}
	out, err := info.Method.decode(payload, info.Original)
	if err != nil {
		return nil, info, fmt.Errorf("kolmo: %s payload: %w", info.Method.Name, err)
	}
	if len(out) != info.Original || crc.Sum(out) != info.CRC {
		return nil, info, ErrChecksum
	}
	return out, info, nil
}
