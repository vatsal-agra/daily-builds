package asm

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"
)

// symLookup resolves an identifier; ok=false means undefined.
type symLookup func(name string) (int, bool)

type exprParser struct {
	s      string
	pos    int
	lookup symLookup
	pc     int
	err    error
}

func isIdentStart(r byte) bool {
	return r == '_' || r == '.' || unicode.IsLetter(rune(r))
}
func isIdentChar(r byte) bool {
	return isIdentStart(r) || (r >= '0' && r <= '9')
}

// evalExpr evaluates an expression string. undefined identifiers produce an
// *undefinedError so callers can distinguish forward references.
func evalExpr(s string, pc int, lookup symLookup) (int, error) {
	p := &exprParser{s: s, lookup: lookup, pc: pc}
	v := p.parseOr()
	p.skip()
	if p.err == nil && p.pos < len(p.s) {
		p.err = fmt.Errorf("unexpected %q in expression %q", p.s[p.pos:], s)
	}
	return v, p.err
}

type undefinedError struct{ name string }

func (e *undefinedError) Error() string { return "undefined symbol " + strconv.Quote(e.name) }

func (p *exprParser) skip() {
	for p.pos < len(p.s) && (p.s[p.pos] == ' ' || p.s[p.pos] == '\t') {
		p.pos++
	}
}

func (p *exprParser) fail(format string, a ...any) int {
	if p.err == nil {
		p.err = fmt.Errorf(format, a...)
	}
	return 0
}

func (p *exprParser) peek2(a string) bool {
	p.skip()
	return strings.HasPrefix(p.s[p.pos:], a)
}

func (p *exprParser) parseOr() int {
	v := p.parseXor()
	for p.err == nil {
		p.skip()
		if p.pos < len(p.s) && p.s[p.pos] == '|' {
			p.pos++
			v |= p.parseXor()
		} else {
			break
		}
	}
	return v
}

func (p *exprParser) parseXor() int {
	v := p.parseAnd()
	for p.err == nil {
		p.skip()
		if p.pos < len(p.s) && p.s[p.pos] == '^' {
			p.pos++
			v ^= p.parseAnd()
		} else {
			break
		}
	}
	return v
}

func (p *exprParser) parseAnd() int {
	v := p.parseShift()
	for p.err == nil {
		p.skip()
		if p.pos < len(p.s) && p.s[p.pos] == '&' {
			p.pos++
			v &= p.parseShift()
		} else {
			break
		}
	}
	return v
}

func (p *exprParser) parseShift() int {
	v := p.parseAdd()
	for p.err == nil {
		switch {
		case p.peek2("<<"):
			p.pos += 2
			n := p.parseAdd()
			if n < 0 || n > 31 {
				return p.fail("shift count %d out of range", n)
			}
			v <<= uint(n)
		case p.peek2(">>"):
			p.pos += 2
			n := p.parseAdd()
			if n < 0 || n > 31 {
				return p.fail("shift count %d out of range", n)
			}
			v >>= uint(n)
		default:
			return v
		}
	}
	return v
}

func (p *exprParser) parseAdd() int {
	v := p.parseMul()
	for p.err == nil {
		p.skip()
		if p.pos >= len(p.s) {
			break
		}
		switch p.s[p.pos] {
		case '+':
			p.pos++
			v += p.parseMul()
		case '-':
			p.pos++
			v -= p.parseMul()
		default:
			return v
		}
	}
	return v
}

func (p *exprParser) parseMul() int {
	v := p.parseUnary()
	for p.err == nil {
		p.skip()
		if p.pos >= len(p.s) {
			break
		}
		switch p.s[p.pos] {
		case '*':
			p.pos++
			v *= p.parseUnary()
		case '/':
			p.pos++
			d := p.parseUnary()
			if d == 0 {
				return p.fail("division by zero")
			}
			v /= d
		case '%':
			p.pos++
			d := p.parseUnary()
			if d == 0 {
				return p.fail("modulo by zero")
			}
			v %= d
		default:
			return v
		}
	}
	return v
}

func (p *exprParser) parseUnary() int {
	p.skip()
	if p.pos >= len(p.s) {
		return p.fail("unexpected end of expression")
	}
	switch p.s[p.pos] {
	case '-':
		p.pos++
		return -p.parseUnary()
	case '+':
		p.pos++
		return p.parseUnary()
	case '~':
		p.pos++
		return ^p.parseUnary()
	}
	return p.parsePrimary()
}

func (p *exprParser) parsePrimary() int {
	p.skip()
	c := p.s[p.pos]
	switch {
	case c == '(':
		p.pos++
		v := p.parseOr()
		p.skip()
		if p.pos >= len(p.s) || p.s[p.pos] != ')' {
			return p.fail("missing ')'")
		}
		p.pos++
		return v
	case c == '$':
		p.pos++
		start := p.pos
		for p.pos < len(p.s) && strings.IndexByte("0123456789abcdefABCDEF", p.s[p.pos]) >= 0 {
			p.pos++
		}
		if start == p.pos {
			return p.pc // lone $ is the current address
		}
		n, err := strconv.ParseInt(p.s[start:p.pos], 16, 64)
		if err != nil {
			return p.fail("bad hex literal")
		}
		return int(n)
	case c == '%':
		p.pos++
		start := p.pos
		for p.pos < len(p.s) && (p.s[p.pos] == '0' || p.s[p.pos] == '1' || p.s[p.pos] == '_') {
			p.pos++
		}
		if start == p.pos {
			return p.fail("bad binary literal")
		}
		n, _ := strconv.ParseInt(strings.ReplaceAll(p.s[start:p.pos], "_", ""), 2, 64)
		return int(n)
	case c == '\'':
		if p.pos+2 < len(p.s) && p.s[p.pos+2] == '\'' {
			v := int(p.s[p.pos+1])
			p.pos += 3
			return v
		}
		return p.fail("bad character literal")
	case c >= '0' && c <= '9':
		start := p.pos
		for p.pos < len(p.s) && (isIdentChar(p.s[p.pos])) {
			p.pos++
		}
		lit := strings.ReplaceAll(p.s[start:p.pos], "_", "")
		var n int64
		var err error
		switch {
		case strings.HasPrefix(lit, "0x") || strings.HasPrefix(lit, "0X"):
			n, err = strconv.ParseInt(lit[2:], 16, 64)
		case strings.HasPrefix(lit, "0b") || strings.HasPrefix(lit, "0B"):
			n, err = strconv.ParseInt(lit[2:], 2, 64)
		case strings.HasSuffix(lit, "h") || strings.HasSuffix(lit, "H"):
			n, err = strconv.ParseInt(lit[:len(lit)-1], 16, 64)
		default:
			n, err = strconv.ParseInt(lit, 10, 64)
		}
		if err != nil {
			return p.fail("bad number %q", lit)
		}
		return int(n)
	case isIdentStart(c):
		start := p.pos
		for p.pos < len(p.s) && isIdentChar(p.s[p.pos]) {
			p.pos++
		}
		name := p.s[start:p.pos]
		lname := strings.ToLower(name)
		if lname == "low" || lname == "high" {
			p.skip()
			if p.pos < len(p.s) && p.s[p.pos] == '(' {
				p.pos++
				v := p.parseOr()
				p.skip()
				if p.pos >= len(p.s) || p.s[p.pos] != ')' {
					return p.fail("missing ')'")
				}
				p.pos++
				if lname == "low" {
					return v & 0xFF
				}
				return (v >> 8) & 0xFF
			}
		}
		if v, ok := p.lookup(name); ok {
			return v
		}
		if p.err == nil {
			p.err = &undefinedError{name}
		}
		return 0
	}
	return p.fail("unexpected %q in expression", string(c))
}
