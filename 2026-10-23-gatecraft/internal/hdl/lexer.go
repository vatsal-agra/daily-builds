// Package hdl is the Verilog-subset front end: lexer, AST and parser.
package hdl

import (
	"fmt"
	"strings"
	"unicode"
)

// Pos is a source position.
type Pos struct{ Line, Col int }

func (p Pos) String() string { return fmt.Sprintf("%d:%d", p.Line, p.Col) }

// Error is a positioned diagnostic.
type Error struct {
	File string
	Pos  Pos
	Msg  string
}

func (e *Error) Error() string {
	if e.File != "" {
		return fmt.Sprintf("%s:%s: %s", e.File, e.Pos, e.Msg)
	}
	return fmt.Sprintf("%s: %s", e.Pos, e.Msg)
}

type tokKind int

const (
	tEOF tokKind = iota
	tIdent
	tNumber
	tSym
)

type token struct {
	kind tokKind
	text string
	pos  Pos
}

var keywords = map[string]bool{
	"module": true, "endmodule": true, "input": true, "output": true, "inout": true,
	"wire": true, "reg": true, "integer": true, "parameter": true, "localparam": true,
	"assign": true, "always": true, "initial": true, "begin": true, "end": true,
	"if": true, "else": true, "case": true, "endcase": true, "default": true,
	"for": true, "posedge": true, "negedge": true, "or": true, "assert": true,
	"assume": true, "property": true, "signed": true, "genvar": true, "generate": true,
	"endgenerate": true, "function": true, "endfunction": true, "task": true, "endtask": true,
	"casez": true, "casex": true, "while": true, "repeat": true, "forever": true,
	"tri": true, "supply0": true, "supply1": true,
}

var syms3 = []string{"<<<", ">>>", "===", "!==", "~&", "~|", "~^", "^~"}
var syms2 = []string{"<=", ">=", "==", "!=", "&&", "||", "<<", ">>", "**", "+:", "-:", "~&", "~|", "~^", "^~"}

func lex(src string) ([]token, error) {
	var toks []token
	line, col := 1, 1
	i := 0
	adv := func(n int) {
		for k := 0; k < n; k++ {
			if src[i] == '\n' {
				line++
				col = 1
			} else {
				col++
			}
			i++
		}
	}
	for i < len(src) {
		c := src[i]
		pos := Pos{line, col}
		switch {
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			adv(1)
		case strings.HasPrefix(src[i:], "//"):
			for i < len(src) && src[i] != '\n' {
				adv(1)
			}
		case strings.HasPrefix(src[i:], "/*"):
			end := strings.Index(src[i+2:], "*/")
			if end < 0 {
				return nil, &Error{Pos: pos, Msg: "unterminated block comment"}
			}
			adv(end + 4)
		case c == '`':
			// compiler directives (`timescale, `default_nettype ...) are ignored to end of line
			for i < len(src) && src[i] != '\n' {
				adv(1)
			}
		case c == '$' || c == '_' || unicode.IsLetter(rune(c)):
			j := i
			for j < len(src) && (src[j] == '_' || src[j] == '$' || unicode.IsLetter(rune(src[j])) || unicode.IsDigit(rune(src[j]))) {
				j++
			}
			toks = append(toks, token{tIdent, src[i:j], pos})
			adv(j - i)
		case unicode.IsDigit(rune(c)) || (c == '\'' && i+1 < len(src) && strings.ContainsRune("bBoOdDhHsS", rune(src[i+1]))):
			j := i
			for j < len(src) && (unicode.IsDigit(rune(src[j])) || src[j] == '_') {
				j++
			}
			if j < len(src) && src[j] == '\'' {
				j++
				if j < len(src) && (src[j] == 's' || src[j] == 'S') {
					j++
				}
				if j < len(src) && strings.ContainsRune("bBoOdDhH", rune(src[j])) {
					j++
				} else {
					return nil, &Error{Pos: pos, Msg: "malformed based number"}
				}
				for j < len(src) && (unicode.IsDigit(rune(src[j])) || unicode.IsLetter(rune(src[j])) || src[j] == '_' || src[j] == '?') {
					j++
				}
			}
			toks = append(toks, token{tNumber, src[i:j], pos})
			adv(j - i)
		case c == '"':
			return nil, &Error{Pos: pos, Msg: "string literals are not supported"}
		default:
			matched := ""
			for _, s := range syms3 {
				if strings.HasPrefix(src[i:], s) {
					matched = s
					break
				}
			}
			if matched == "" {
				for _, s := range syms2 {
					if strings.HasPrefix(src[i:], s) {
						matched = s
						break
					}
				}
			}
			if matched == "" {
				if strings.ContainsRune("()[]{};,:.#@=?~!&|^+-*/%<>", rune(c)) {
					matched = string(c)
				} else {
					return nil, &Error{Pos: pos, Msg: fmt.Sprintf("unexpected character %q", c)}
				}
			}
			toks = append(toks, token{tSym, matched, pos})
			adv(len(matched))
		}
	}
	toks = append(toks, token{tEOF, "", Pos{line, col}})
	return toks, nil
}
