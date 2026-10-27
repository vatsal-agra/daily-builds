package parse

import (
	"fmt"
	"strings"
)

type kind int

const (
	tEOF kind = iota
	tWord
	tStr
	tPunct
	tNL
)

type token struct {
	k         kind
	s         string
	line, col int
}

// Error is a parse error with a source position.
type Error struct {
	File      string
	Line, Col int
	Msg       string
}

func (e *Error) Error() string {
	f := e.File
	if f == "" {
		f = "input"
	}
	return fmt.Sprintf("%s:%d:%d: %s", f, e.Line, e.Col, e.Msg)
}

// lex splits src into tokens. puncts lists single-character punctuation; wordStop
// additionally ends a word. Newlines are emitted only when keepNL is set.
// Comments run from '#' or '//' to end of line (and /* ... */ when blockComments).
func lex(file, src string, puncts string, keepNL, blockComments bool) ([]token, error) {
	var toks []token
	line, col := 1, 1
	i := 0
	src = strings.TrimPrefix(src, "\ufeff") // byte-order mark from Excel / Windows editors
	adv := func() {
		if src[i] == '\n' {
			line++
			col = 1
		} else {
			col++
		}
		i++
	}
	for i < len(src) {
		c := src[i]
		switch {
		case c == '\n':
			if keepNL {
				toks = append(toks, token{tNL, "\n", line, col})
			}
			adv()
		case c == ' ' || c == '\t' || c == '\r':
			adv()
		case c == '#' || (c == '/' && i+1 < len(src) && src[i+1] == '/'):
			for i < len(src) && src[i] != '\n' {
				adv()
			}
		case blockComments && c == '/' && i+1 < len(src) && src[i+1] == '*':
			sl, sc := line, col
			adv()
			adv()
			for {
				if i+1 >= len(src) {
					return nil, &Error{file, sl, sc, "unterminated /* comment"}
				}
				if src[i] == '*' && src[i+1] == '/' {
					adv()
					adv()
					break
				}
				adv()
			}
		case c == '"':
			sl, sc := line, col
			adv()
			var b strings.Builder
			for {
				if i >= len(src) || src[i] == '\n' {
					return nil, &Error{file, sl, sc, "unterminated string"}
				}
				if src[i] == '"' {
					adv()
					break
				}
				if src[i] == '\\' && i+1 < len(src) {
					adv()
					switch src[i] {
					case 'n':
						b.WriteByte('\n')
					case 't':
						b.WriteByte('\t')
					default: // \\ \" and anything else stand for themselves
						b.WriteByte(src[i])
					}
					adv()
					continue
				}
				b.WriteByte(src[i])
				adv()
			}
			toks = append(toks, token{tStr, b.String(), sl, sc})
		case strings.IndexByte(puncts, c) >= 0:
			toks = append(toks, token{tPunct, string(c), line, col})
			adv()
		default:
			sl, sc := line, col
			start := i
			for i < len(src) {
				d := src[i]
				if d == ' ' || d == '\t' || d == '\r' || d == '\n' || d == '#' || d == '"' || strings.IndexByte(puncts, d) >= 0 ||
					(d == '/' && i+1 < len(src) && (src[i+1] == '/' || (blockComments && src[i+1] == '*'))) {
					break
				}
				adv()
			}
			toks = append(toks, token{tWord, src[start:i], sl, sc})
		}
	}
	toks = append(toks, token{tEOF, "", line, col})
	return toks, nil
}

type parser struct {
	file string
	toks []token
	p    int
}

func (ps *parser) peek() token { return ps.toks[ps.p] }
func (ps *parser) next() token {
	t := ps.toks[ps.p]
	if t.k != tEOF {
		ps.p++
	}
	return t
}
func (ps *parser) errAt(t token, f string, a ...any) error {
	return &Error{ps.file, t.line, t.col, fmt.Sprintf(f, a...)}
}
func (ps *parser) isPunct(s string) bool {
	t := ps.peek()
	return t.k == tPunct && t.s == s
}
func (ps *parser) accept(s string) bool {
	if ps.isPunct(s) {
		ps.p++
		return true
	}
	return false
}
func (ps *parser) expect(s string) error {
	if !ps.accept(s) {
		return ps.errAt(ps.peek(), "expected %q, found %s", s, describe(ps.peek()))
	}
	return nil
}
func (ps *parser) skipNL() {
	for ps.peek().k == tNL {
		ps.p++
	}
}

func describe(t token) string {
	switch t.k {
	case tEOF:
		return "end of input"
	case tNL:
		return "end of line"
	case tStr:
		return fmt.Sprintf("string %q", t.s)
	}
	return fmt.Sprintf("%q", t.s)
}

// name accepts a word or a quoted string.
func (ps *parser) name(what string) (token, error) {
	t := ps.peek()
	if t.k != tWord && t.k != tStr {
		return t, ps.errAt(t, "expected %s, found %s", what, describe(t))
	}
	ps.p++
	return t, nil
}
