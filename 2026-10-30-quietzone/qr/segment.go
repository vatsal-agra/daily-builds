package qr

import (
	"errors"
	"fmt"
	"strings"
)

// Mode is a QR data mode.
type Mode int

// Supported modes.
const (
	ModeNumeric Mode = iota
	ModeAlnum
	ModeByte
	ModeECI
	ModeStructured // structured-append header (sequence index, total, parity)
)

func (m Mode) String() string {
	return [...]string{"numeric", "alphanumeric", "byte", "eci", "structured-append"}[m]
}

func (m Mode) indicator() int { return [...]int{0x1, 0x2, 0x4, 0x7, 0x3}[m] }

const alnumChars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"

// Segment is one run of data in a single mode.
type Segment struct {
	Mode  Mode
	Chars int    // character count (bytes for byte mode)
	Data  []byte // numeric/alnum: the ASCII text; byte: raw bytes
	ECI   int    // for ModeECI
	// Structured append (ModeStructured): position Index of Total, and the parity byte.
	Index, Total int
	Parity       byte
}

func ccBits(m Mode, version int) int {
	k := 0
	if version >= 27 {
		k = 2
	} else if version >= 10 {
		k = 1
	}
	return [...][3]int{{10, 12, 14}, {9, 11, 13}, {8, 16, 16}}[m][k]
}

// IsNumeric reports whether every byte is 0-9.
func IsNumeric(b []byte) bool {
	for _, c := range b {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// IsAlnum reports whether every byte is in the 45-char QR alphanumeric set.
func IsAlnum(b []byte) bool {
	for _, c := range b {
		if strings.IndexByte(alnumChars, c) < 0 {
			return false
		}
	}
	return true
}

// bitWriter accumulates a big-endian bit stream.
type bitWriter struct {
	bits []byte // one entry per bit (0/1); simple and fast enough for <=23,648 bits
}

func (w *bitWriter) put(val, n int) {
	for i := n - 1; i >= 0; i-- {
		w.bits = append(w.bits, byte(val>>i)&1)
	}
}

func (w *bitWriter) len() int { return len(w.bits) }

func (w *bitWriter) bytes() []byte {
	out := make([]byte, (len(w.bits)+7)/8)
	for i, b := range w.bits {
		out[i/8] |= b << (7 - i%8)
	}
	return out
}

// segBits returns the exact bit length of seg at the given version, or -1 if the
// count does not fit in the character-count field.
func segBits(s Segment, version int) int {
	if s.Mode == ModeStructured {
		return 4 + 16
	}
	if s.Mode == ModeECI {
		switch {
		case s.ECI < 128:
			return 4 + 8
		case s.ECI < 16384:
			return 4 + 16
		default:
			return 4 + 24
		}
	}
	cc := ccBits(s.Mode, version)
	if s.Chars >= 1<<cc {
		return -1
	}
	n := 4 + cc
	switch s.Mode {
	case ModeNumeric:
		n += s.Chars/3*10 + [3]int{0, 4, 7}[s.Chars%3]
	case ModeAlnum:
		n += s.Chars/2*11 + s.Chars%2*6
	case ModeByte:
		n += 8 * s.Chars
	}
	return n
}

func (w *bitWriter) writeSegment(s Segment, version int) error {
	if s.Mode == ModeStructured {
		if s.Total < 2 || s.Total > 16 || s.Index < 0 || s.Index >= s.Total {
			return fmt.Errorf("structured append %d of %d is invalid (total must be 2..16)", s.Index+1, s.Total)
		}
		w.put(ModeStructured.indicator(), 4)
		w.put(s.Index, 4)
		w.put(s.Total-1, 4)
		w.put(int(s.Parity), 8)
		return nil
	}
	if s.Mode == ModeECI {
		w.put(ModeECI.indicator(), 4)
		switch {
		case s.ECI < 0 || s.ECI > 999999:
			return fmt.Errorf("ECI %d out of range", s.ECI)
		case s.ECI < 128:
			w.put(s.ECI, 8)
		case s.ECI < 16384:
			w.put(0x8000|s.ECI, 16)
		default:
			w.put(0xC00000|s.ECI, 24)
		}
		return nil
	}
	if segBits(s, version) < 0 {
		return errors.New("segment too long for version")
	}
	w.put(s.Mode.indicator(), 4)
	w.put(s.Chars, ccBits(s.Mode, version))
	switch s.Mode {
	case ModeNumeric:
		for i := 0; i < len(s.Data); i += 3 {
			j := min(i+3, len(s.Data))
			v := 0
			for _, c := range s.Data[i:j] {
				v = v*10 + int(c-'0')
			}
			w.put(v, [4]int{0, 4, 7, 10}[j-i])
		}
	case ModeAlnum:
		for i := 0; i < len(s.Data); i += 2 {
			a := strings.IndexByte(alnumChars, s.Data[i])
			if i+1 < len(s.Data) {
				w.put(a*45+strings.IndexByte(alnumChars, s.Data[i+1]), 11)
			} else {
				w.put(a, 6)
			}
		}
	case ModeByte:
		for _, c := range s.Data {
			w.put(int(c), 8)
		}
	}
	return nil
}

// MakeSegment builds a single-mode segment, validating the data against the mode.
func MakeSegment(m Mode, data []byte) (Segment, error) {
	switch m {
	case ModeNumeric:
		if !IsNumeric(data) {
			return Segment{}, errors.New("non-digit in numeric segment")
		}
	case ModeAlnum:
		if !IsAlnum(data) {
			return Segment{}, errors.New("character outside alphanumeric set")
		}
	case ModeByte:
	default:
		return Segment{}, errors.New("cannot make segment of this mode")
	}
	return Segment{Mode: m, Chars: len(data), Data: append([]byte(nil), data...)}, nil
}

// ECISegment returns an ECI designator segment.
func ECISegment(n int) Segment { return Segment{Mode: ModeECI, ECI: n} }

// totalBits sums segment sizes; -1 if any segment overflows its count field.
func totalBits(segs []Segment, version int) int {
	t := 0
	for _, s := range segs {
		b := segBits(s, version)
		if b < 0 {
			return -1
		}
		t += b
	}
	return t
}

// OptimalSegments splits data into the mode runs that minimise the encoded size
// for the given version, by dynamic programming over (position, mode). Costs are
// scaled by 6 so numeric (10/3 bits) and alphanumeric (11/2 bits) are integral.
func OptimalSegments(data []byte, version int) []Segment {
	n := len(data)
	if n == 0 {
		return nil
	}
	const inf = int(^uint(0) >> 2)
	modes := []Mode{ModeNumeric, ModeAlnum, ModeByte}
	ok := func(m Mode, c byte) bool {
		switch m {
		case ModeNumeric:
			return c >= '0' && c <= '9'
		case ModeAlnum:
			return strings.IndexByte(alnumChars, c) >= 0
		}
		return true
	}
	charCost := [3]int{20, 33, 48}
	head := func(m Mode) int { return (4 + ccBits(m, version)) * 6 }
	cost := make([][3]int, n)
	from := make([][3]int, n)
	for i := 0; i < n; i++ {
		for mi, m := range modes {
			cost[i][mi] = inf
			if !ok(m, data[i]) {
				continue
			}
			if i == 0 {
				cost[i][mi] = head(m) + charCost[mi]
				from[i][mi] = -1
				continue
			}
			best, bf := inf, -1
			for pj := range modes {
				c := cost[i-1][pj]
				if c >= inf {
					continue
				}
				c += charCost[mi]
				if pj != mi {
					c += head(m)
				}
				if c < best {
					best, bf = c, pj
				}
			}
			cost[i][mi], from[i][mi] = best, bf
		}
	}
	bm, bc := 0, inf
	for mi := range modes {
		if cost[n-1][mi] < bc {
			bm, bc = mi, cost[n-1][mi]
		}
	}
	runs := make([]int, n)
	for i, m := n-1, bm; i >= 0; i-- {
		runs[i] = m
		m = from[i][m]
	}
	var segs []Segment
	for i := 0; i < n; {
		j := i
		for j < n && runs[j] == runs[i] {
			j++
		}
		segs = append(segs, Segment{Mode: modes[runs[i]], Chars: j - i, Data: append([]byte(nil), data[i:j]...)})
		i = j
	}
	return segs
}
