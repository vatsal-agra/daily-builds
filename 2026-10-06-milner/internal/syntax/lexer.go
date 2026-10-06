package syntax

import (
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// TokKind enumerates token categories.
type TokKind int

const (
	EOF TokKind = iota
	INT
	STRING
	IDENT  // lower-case identifier
	UIDENT // constructor / capitalised identifier
	TYVAR  // 'a
	KW     // keyword
	SYM    // punctuation / operator
)

// Token is a lexed token.
type Token struct {
	Kind TokKind
	Text string // identifier text, keyword, symbol, or decoded string literal
	Int  int64
	Span Span
}

var keywords = map[string]bool{
	"let": true, "rec": true, "and": true, "in": true, "fun": true, "function": true,
	"if": true, "then": true, "else": true, "match": true, "with": true, "type": true,
	"of": true, "true": true, "false": true, "mod": true, "when": true, "as": true,
	"begin": true, "end": true,
}

// symbols, longest first.
var symbols = []string{
	";;", "->", "::", "<>", "<=", ">=", "&&", "||", ":=", "|>", "..",
	"(", ")", "[", "]", "{", "}", ",", ";", "|", ":", "=", "<", ">", "+", "-", "*", "/",
	"!", ".", "_", "^", "@",
}

type lexer struct {
	src  string
	off  int
	line int
	col  int
}

// Lex converts src to tokens (ending with EOF). Comments `(* ... *)` nest.
func Lex(src string) ([]Token, *Diag) {
	lx := &lexer{src: src, line: 1, col: 1}
	var toks []Token
	for {
		if d := lx.skipSpace(); d != nil {
			return nil, d
		}
		start := lx.pos()
		if lx.off >= len(lx.src) {
			toks = append(toks, Token{Kind: EOF, Span: Span{start, start}})
			return toks, nil
		}
		t, d := lx.next(start)
		if d != nil {
			return nil, d
		}
		toks = append(toks, t)
	}
}

func (lx *lexer) pos() Pos { return Pos{lx.off, lx.line, lx.col} }

func (lx *lexer) peekRune() (rune, int) {
	if lx.off >= len(lx.src) {
		return 0, 0
	}
	return utf8.DecodeRuneInString(lx.src[lx.off:])
}

func (lx *lexer) advance() rune {
	r, n := lx.peekRune()
	lx.off += n
	if r == '\n' {
		lx.line++
		lx.col = 1
	} else {
		lx.col++
	}
	return r
}

func (lx *lexer) skipSpace() *Diag {
	for lx.off < len(lx.src) {
		r, _ := lx.peekRune()
		if unicode.IsSpace(r) {
			lx.advance()
			continue
		}
		if strings.HasPrefix(lx.src[lx.off:], "(*") {
			start := lx.pos()
			depth := 0
			for {
				if lx.off >= len(lx.src) {
					d := Errorf("syntax", Span{start, lx.pos()}, "unterminated comment")
					if strings.HasPrefix(lx.src[start.Off:], "(*)") {
						d.Notes = append(d.Notes, "`(*)` starts a comment; write `( * )` (with spaces) for the multiplication operator")
					}
					return d
				}
				switch {
				case strings.HasPrefix(lx.src[lx.off:], "(*"):
					depth++
					lx.advance()
					lx.advance()
				case strings.HasPrefix(lx.src[lx.off:], "*)"):
					depth--
					lx.advance()
					lx.advance()
				default:
					lx.advance()
				}
				if depth == 0 {
					break
				}
			}
			continue
		}
		break
	}
	return nil
}

func isIdentStart(r rune) bool { return r == '_' || unicode.IsLetter(r) }
func isIdentPart(r rune) bool {
	return r == '_' || r == '\'' || unicode.IsLetter(r) || unicode.IsDigit(r)
}

func (lx *lexer) next(start Pos) (Token, *Diag) {
	r, _ := lx.peekRune()
	switch {
	case r >= '0' && r <= '9':
		for {
			c, _ := lx.peekRune()
			if (c >= '0' && c <= '9') || c == '_' {
				lx.advance()
			} else {
				break
			}
		}
		text := strings.ReplaceAll(lx.src[start.Off:lx.off], "_", "")
		sp := Span{start, lx.pos()}
		n, err := strconv.ParseInt(text, 10, 64)
		if err != nil {
			return Token{}, Errorf("syntax", sp, "integer literal %s is out of range", text)
		}
		return Token{Kind: INT, Int: n, Text: text, Span: sp}, nil
	case r == '"':
		return lx.str(start)
	case r == '\'':
		// type variable 'a
		lx.advance()
		c, _ := lx.peekRune()
		if !isIdentStart(c) || c == '_' && false {
			return Token{}, Errorf("syntax", Span{start, lx.pos()}, "stray apostrophe (type variables look like 'a)")
		}
		for {
			c, _ := lx.peekRune()
			if lx.off < len(lx.src) && isIdentPart(c) && c != '\'' {
				lx.advance()
			} else {
				break
			}
		}
		return Token{Kind: TYVAR, Text: lx.src[start.Off:lx.off], Span: Span{start, lx.pos()}}, nil
	case isIdentStart(r):
		if r == '_' {
			// lone underscore is a symbol; _foo is an identifier
			rest := lx.src[lx.off+1:]
			if rest == "" {
				lx.advance()
				return Token{Kind: SYM, Text: "_", Span: Span{start, lx.pos()}}, nil
			}
			n, _ := utf8.DecodeRuneInString(rest)
			if !isIdentPart(n) {
				lx.advance()
				return Token{Kind: SYM, Text: "_", Span: Span{start, lx.pos()}}, nil
			}
		}
		for {
			c, _ := lx.peekRune()
			if lx.off < len(lx.src) && isIdentPart(c) {
				lx.advance()
			} else {
				break
			}
		}
		text := lx.src[start.Off:lx.off]
		sp := Span{start, lx.pos()}
		if keywords[text] {
			return Token{Kind: KW, Text: text, Span: sp}, nil
		}
		first, _ := utf8.DecodeRuneInString(text)
		if unicode.IsUpper(first) {
			return Token{Kind: UIDENT, Text: text, Span: sp}, nil
		}
		return Token{Kind: IDENT, Text: text, Span: sp}, nil
	}
	rest := lx.src[lx.off:]
	for _, s := range symbols {
		if strings.HasPrefix(rest, s) {
			for range s {
				lx.advance()
			}
			return Token{Kind: SYM, Text: s, Span: Span{start, lx.pos()}}, nil
		}
	}
	lx.advance()
	return Token{}, Errorf("syntax", Span{start, lx.pos()}, "unexpected character %q", string(r))
}

func (lx *lexer) str(start Pos) (Token, *Diag) {
	lx.advance() // opening quote
	var b strings.Builder
	for {
		if lx.off >= len(lx.src) {
			return Token{}, Errorf("syntax", Span{start, lx.pos()}, "unterminated string literal")
		}
		r := lx.advance()
		switch r {
		case '"':
			return Token{Kind: STRING, Text: b.String(), Span: Span{start, lx.pos()}}, nil
		case '\\':
			if lx.off >= len(lx.src) {
				return Token{}, Errorf("syntax", Span{start, lx.pos()}, "unterminated string literal")
			}
			epos := lx.pos()
			e := lx.advance()
			switch e {
			case 'n':
				b.WriteByte('\n')
			case 't':
				b.WriteByte('\t')
			case 'r':
				b.WriteByte('\r')
			case '\\':
				b.WriteByte('\\')
			case '"':
				b.WriteByte('"')
			case '0':
				b.WriteByte(0)
			default:
				return Token{}, Errorf("syntax", Span{epos, lx.pos()}, "unknown escape sequence \\%c", e)
			}
		default:
			b.WriteRune(r)
		}
	}
}
