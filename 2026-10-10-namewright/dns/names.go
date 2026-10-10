package dns

import (
	"fmt"
	"strings"
)

// Names are held in presentation format as fully-qualified strings with a
// trailing dot ("www.example.com."). A label may contain any byte; '.' and '\'
// inside a label are escaped as `\.` and `\\`, and non-printable bytes as `\DDD`.

const (
	maxLabel = 63
	maxName  = 255
)

// splitName parses a presentation-format name into raw labels. A name without
// a trailing dot is taken as already absolute; "" and "." are the root.
func splitName(name string) ([][]byte, error) {
	if name == "" || name == "." {
		return nil, nil
	}
	var labels [][]byte
	var cur []byte
	have := false
	for i := 0; i < len(name); i++ {
		c := name[i]
		switch {
		case c == '.':
			if !have {
				return nil, fmt.Errorf("empty label in %q", name)
			}
			labels = append(labels, cur)
			cur, have = nil, false
		case c == '\\':
			i++
			if i >= len(name) {
				return nil, fmt.Errorf("dangling escape in %q", name)
			}
			d := name[i]
			if d >= '0' && d <= '9' {
				if i+2 >= len(name) || !isDigit(name[i+1]) || !isDigit(name[i+2]) {
					return nil, fmt.Errorf("bad \\DDD escape in %q", name)
				}
				v := int(d-'0')*100 + int(name[i+1]-'0')*10 + int(name[i+2]-'0')
				if v > 255 {
					return nil, fmt.Errorf("escape \\%03d out of range in %q", v, name)
				}
				cur = append(cur, byte(v))
				i += 2
			} else {
				cur = append(cur, d)
			}
			have = true
		default:
			cur = append(cur, c)
			have = true
		}
	}
	if have {
		labels = append(labels, cur)
	}
	total := 1
	for _, l := range labels {
		if len(l) == 0 || len(l) > maxLabel {
			return nil, fmt.Errorf("label length %d invalid in %q", len(l), name)
		}
		total += len(l) + 1
	}
	if total > maxName {
		return nil, fmt.Errorf("name %q exceeds 255 octets", name)
	}
	return labels, nil
}

func isDigit(c byte) bool { return c >= '0' && c <= '9' }

// joinLabels renders raw labels as an escaped, fully-qualified name.
func joinLabels(labels [][]byte) string {
	if len(labels) == 0 {
		return "."
	}
	var sb strings.Builder
	for _, l := range labels {
		for _, c := range l {
			switch {
			case c == '.' || c == '\\':
				sb.WriteByte('\\')
				sb.WriteByte(c)
			case c <= ' ' || c >= 0x7f:
				fmt.Fprintf(&sb, "\\%03d", c)
			default:
				sb.WriteByte(c)
			}
		}
		sb.WriteByte('.')
	}
	return sb.String()
}

// CanonName lower-cases ASCII and makes the name absolute. It does not
// validate; use ValidName for that.
func CanonName(s string) string {
	if s == "" {
		return "."
	}
	b := []byte(s)
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			b[i] = c + 32
		}
	}
	s = string(b)
	if !strings.HasSuffix(s, ".") || escapedDot(s) {
		s += "."
	}
	return s
}

// escapedDot reports whether the final '.' of s is itself backslash-escaped
// (an odd number of preceding backslashes).
func escapedDot(s string) bool {
	n := 0
	for i := len(s) - 2; i >= 0 && s[i] == '\\'; i-- {
		n++
	}
	return n%2 == 1
}

// ValidName checks that s parses as a legal domain name.
func ValidName(s string) error {
	_, err := splitName(s)
	return err
}

// Labels returns the labels of an absolute name (without escapes resolved).
func Labels(name string) [][]byte {
	l, _ := splitName(name)
	return l
}

// NumLabels counts labels, not counting the root.
func NumLabels(name string) int { return len(Labels(name)) }

// IsSubdomain reports whether child is equal to or below parent (case-insensitive).
func IsSubdomain(child, parent string) bool {
	cl, pl := Labels(CanonName(child)), Labels(CanonName(parent))
	if len(pl) > len(cl) {
		return false
	}
	off := len(cl) - len(pl)
	for i := range pl {
		if !eqFold(cl[off+i], pl[i]) {
			return false
		}
	}
	return true
}

func eqFold(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		x, y := a[i], b[i]
		if x >= 'A' && x <= 'Z' {
			x += 32
		}
		if y >= 'A' && y <= 'Z' {
			y += 32
		}
		if x != y {
			return false
		}
	}
	return true
}

// Parent strips the leftmost label. Parent of the root is the root.
func Parent(name string) string {
	l := Labels(name)
	if len(l) <= 1 {
		return "."
	}
	return joinLabels(l[1:])
}

// Join appends origin to a relative label sequence.
func Join(rel, origin string) string {
	if rel == "" {
		return origin
	}
	if origin == "." {
		return rel + "."
	}
	return rel + "." + origin
}

// CompareNames orders names in DNSSEC canonical order (RFC 4034 §6.1):
// compare label by label starting from the rightmost, case-insensitively.
func CompareNames(a, b string) int {
	al, bl := Labels(a), Labels(b)
	i, j := len(al)-1, len(bl)-1
	for i >= 0 && j >= 0 {
		x, y := lowerBytes(al[i]), lowerBytes(bl[j])
		if c := compareBytes(x, y); c != 0 {
			return c
		}
		i--
		j--
	}
	switch {
	case i < 0 && j < 0:
		return 0
	case i < 0:
		return -1
	default:
		return 1
	}
}

func lowerBytes(b []byte) []byte {
	o := make([]byte, len(b))
	for i, c := range b {
		if c >= 'A' && c <= 'Z' {
			c += 32
		}
		o[i] = c
	}
	return o
}

func compareBytes(a, b []byte) int {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	for i := 0; i < n; i++ {
		if a[i] != b[i] {
			if a[i] < b[i] {
				return -1
			}
			return 1
		}
	}
	switch {
	case len(a) < len(b):
		return -1
	case len(a) > len(b):
		return 1
	}
	return 0
}
