package main

import (
	"fmt"
	"strings"
)

// Combo is one concrete two-card holding (a < b).
type Combo struct{ A, B int }

func mkCombo(a, b int) Combo {
	if a > b {
		a, b = b, a
	}
	return Combo{a, b}
}

func (c Combo) String() string { return CardString(c.B) + CardString(c.A) }
func (c Combo) mask() uint64   { return 1<<uint(c.A) | 1<<uint(c.B) }

func rankIdx(ch byte) int { return strings.IndexByte(rankChars, byte(strings.ToUpper(string(ch))[0])) }

func classCombos(hi, lo int, suited, offsuit bool) []Combo {
	var out []Combo
	if hi == lo {
		for s1 := 0; s1 < 4; s1++ {
			for s2 := s1 + 1; s2 < 4; s2++ {
				out = append(out, mkCombo(mkCard(hi, s1), mkCard(lo, s2)))
			}
		}
		return out
	}
	for s1 := 0; s1 < 4; s1++ {
		for s2 := 0; s2 < 4; s2++ {
			if (s1 == s2 && suited) || (s1 != s2 && offsuit) {
				out = append(out, mkCombo(mkCard(hi, s1), mkCard(lo, s2)))
			}
		}
	}
	return out
}

// ParseRange parses a hold'em range such as "QQ+, AKs, AJo+, A5s-A2s, 77-55, T9s-54s, AhKd, random".
func ParseRange(spec string) ([]Combo, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return nil, fmt.Errorf("empty range")
	}
	seen := map[Combo]bool{}
	var out []Combo
	add := func(cs []Combo) {
		for _, c := range cs {
			if !seen[c] {
				seen[c] = true
				out = append(out, c)
			}
		}
	}
	toks := strings.FieldsFunc(spec, func(r rune) bool { return r == ',' || r == ' ' || r == ';' })
	for _, tok := range toks {
		cs, err := parseRangeToken(tok)
		if err != nil {
			return nil, fmt.Errorf("range %q: %w", tok, err)
		}
		add(cs)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("empty range")
	}
	return out, nil
}

type classTok struct {
	hi, lo          int
	suited, offsuit bool
}

func parseClass(t string) (classTok, error) {
	if len(t) < 2 || len(t) > 3 {
		return classTok{}, fmt.Errorf("unrecognised hand class")
	}
	a, b := rankIdx(t[0]), rankIdx(t[1])
	if a < 0 || b < 0 {
		return classTok{}, fmt.Errorf("unrecognised hand class")
	}
	c := classTok{hi: max(a, b), lo: min(a, b), suited: true, offsuit: true}
	if len(t) == 3 {
		switch strings.ToLower(t[2:]) {
		case "s":
			c.offsuit = false
		case "o":
			c.suited = false
		default:
			return classTok{}, fmt.Errorf("unrecognised suit suffix %q", t[2:])
		}
	}
	if c.hi == c.lo && len(t) == 3 {
		return classTok{}, fmt.Errorf("pairs cannot be suited/offsuit")
	}
	return c, nil
}

func parseRangeToken(tok string) ([]Combo, error) {
	low := strings.ToLower(tok)
	if low == "random" || low == "any" || low == "*" {
		var out []Combo
		for a := 0; a < 52; a++ {
			for b := a + 1; b < 52; b++ {
				out = append(out, Combo{a, b})
			}
		}
		return out, nil
	}
	// specific combo e.g. AhKd
	if len(tok) == 4 {
		if a, err := ParseCard(tok[:2]); err == nil {
			b, err := ParseCard(tok[2:])
			if err != nil {
				return nil, err
			}
			if a == b {
				return nil, fmt.Errorf("duplicate card")
			}
			return []Combo{mkCombo(a, b)}, nil
		}
	}
	if i := strings.IndexByte(tok, '-'); i > 0 {
		x, err := parseClass(tok[:i])
		if err != nil {
			return nil, err
		}
		y, err := parseClass(tok[i+1:])
		if err != nil {
			return nil, err
		}
		if x.suited != y.suited || x.offsuit != y.offsuit {
			return nil, fmt.Errorf("mismatched suit modifiers in range")
		}
		var out []Combo
		switch {
		case x.hi == x.lo && y.hi == y.lo:
			for r := min(x.hi, y.hi); r <= max(x.hi, y.hi); r++ {
				out = append(out, classCombos(r, r, true, true)...)
			}
		case x.hi == x.lo || y.hi == y.lo:
			return nil, fmt.Errorf("cannot mix pairs and non-pairs")
		case x.hi == y.hi:
			for l := min(x.lo, y.lo); l <= max(x.lo, y.lo); l++ {
				out = append(out, classCombos(x.hi, l, x.suited, x.offsuit)...)
			}
		case x.hi-x.lo == y.hi-y.lo:
			gap := x.hi - x.lo
			for h := min(x.hi, y.hi); h <= max(x.hi, y.hi); h++ {
				out = append(out, classCombos(h, h-gap, x.suited, x.offsuit)...)
			}
		default:
			return nil, fmt.Errorf("dash range needs a shared high card or equal gap")
		}
		return out, nil
	}
	plus := strings.HasSuffix(tok, "+")
	body := strings.TrimSuffix(tok, "+")
	c, err := parseClass(body)
	if err != nil {
		return nil, err
	}
	if !plus {
		return classCombos(c.hi, c.lo, c.suited, c.offsuit), nil
	}
	var out []Combo
	if c.hi == c.lo {
		for r := c.hi; r <= 12; r++ {
			out = append(out, classCombos(r, r, true, true)...)
		}
		return out, nil
	}
	for l := c.lo; l < c.hi; l++ {
		out = append(out, classCombos(c.hi, l, c.suited, c.offsuit)...)
	}
	return out, nil
}
