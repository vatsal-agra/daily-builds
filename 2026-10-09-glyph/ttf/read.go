package ttf

import (
	"errors"
	"fmt"
)

// ErrMalformed wraps every parse failure caused by bad font data.
var ErrMalformed = errors.New("malformed font")

type parseError struct{ msg string }

func (e parseError) Error() string { return e.msg }

func fail(format string, a ...any) { panic(parseError{fmt.Sprintf(format, a...)}) }

// catch converts internal bounds panics into ordinary errors.
func catch(err *error) {
	if r := recover(); r != nil {
		if pe, ok := r.(parseError); ok {
			*err = fmt.Errorf("%w: %s", ErrMalformed, pe.msg)
			return
		}
		panic(r)
	}
}

// Bounds-checked big-endian accessors. They panic with parseError, which the
// public entry points recover, so parsing code stays linear and readable.

func u8(b []byte, off int) int {
	if off < 0 || off+1 > len(b) {
		fail("read u8 at %d beyond %d bytes", off, len(b))
	}
	return int(b[off])
}

func u16(b []byte, off int) int {
	if off < 0 || off+2 > len(b) {
		fail("read u16 at %d beyond %d bytes", off, len(b))
	}
	return int(b[off])<<8 | int(b[off+1])
}

func i16(b []byte, off int) int { return int(int16(u16(b, off))) }

func u32(b []byte, off int) uint32 {
	if off < 0 || off+4 > len(b) {
		fail("read u32 at %d beyond %d bytes", off, len(b))
	}
	return uint32(b[off])<<24 | uint32(b[off+1])<<16 | uint32(b[off+2])<<8 | uint32(b[off+3])
}

func sub(b []byte, off, n int) []byte {
	if off < 0 || n < 0 || off+n > len(b) {
		fail("slice [%d:+%d] beyond %d bytes", off, n, len(b))
	}
	return b[off : off+n]
}
