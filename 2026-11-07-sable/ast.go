package sable

import "fmt"

// ---- Tokens & lexer ----

type TokKind int

const (
	TEOF TokKind = iota
	TInt
	TIdent
	TKeyword
	TOp
)

type Pos struct{ Line, Col int }

func (p Pos) String() string { return fmt.Sprintf("%d:%d", p.Line, p.Col) }

type Token struct {
	Kind TokKind
	Text string
	Val  int64
	Pos  Pos
}

// Error is a positioned compile error.
type Error struct {
	Pos Pos
	Msg string
}

func (e *Error) Error() string { return fmt.Sprintf("%s: %s", e.Pos, e.Msg) }

var keywords = map[string]bool{
	"func": true, "var": true, "if": true, "else": true, "while": true, "for": true,
	"return": true, "break": true, "continue": true, "print": true,
}

func isDigit(c byte) bool { return c >= '0' && c <= '9' }
func isAlpha(c byte) bool { return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') }
func isAlnum(c byte) bool { return isAlpha(c) || isDigit(c) }
func isHex(c byte) bool   { return isDigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F') }
func hexVal(c byte) uint64 {
	switch {
	case isDigit(c):
		return uint64(c - '0')
	case c >= 'a' && c <= 'f':
		return uint64(c-'a') + 10
	}
	return uint64(c-'A') + 10
}

var ops3 = []string{"<<", ">>", "<=", ">=", "==", "!=", "&&", "||"}

// Lex turns source text into tokens.
func Lex(src string) ([]Token, error) {
	var toks []Token
	line, col := 1, 1
	i := 0
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
		pos := Pos{line, col}
		switch {
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			adv()
		case c == '/' && i+1 < len(src) && src[i+1] == '/':
			for i < len(src) && src[i] != '\n' {
				adv()
			}
		case c == '/' && i+1 < len(src) && src[i+1] == '*':
			adv()
			adv()
			closed := false
			for i < len(src) {
				if src[i] == '*' && i+1 < len(src) && src[i+1] == '/' {
					adv()
					adv()
					closed = true
					break
				}
				adv()
			}
			if !closed {
				return nil, &Error{pos, "unterminated block comment"}
			}
		case isDigit(c):
			start := i
			var v uint64
			over := false
			add := func(base, d uint64) {
				if v > (1<<63-1-d)/base {
					over = true
				}
				v = v*base + d
			}
			if c == '0' && i+1 < len(src) && (src[i+1] == 'x' || src[i+1] == 'X') {
				adv()
				adv()
				if i >= len(src) || !isHex(src[i]) {
					return nil, &Error{pos, "malformed hex literal"}
				}
				for i < len(src) && isHex(src[i]) {
					add(16, hexVal(src[i]))
					adv()
				}
			} else {
				for i < len(src) && isDigit(src[i]) {
					add(10, uint64(src[i]-'0'))
					adv()
				}
			}
			if i < len(src) && isAlpha(src[i]) {
				return nil, &Error{pos, "malformed number " + src[start:i+1]}
			}
			if over {
				return nil, &Error{pos, "integer literal " + src[start:i] + " overflows int64 (write -9223372036854775807 - 1 for the minimum)"}
			}
			toks = append(toks, Token{TInt, src[start:i], int64(v), pos})
		case isAlpha(c):
			start := i
			for i < len(src) && isAlnum(src[i]) {
				adv()
			}
			w := src[start:i]
			k := TIdent
			if keywords[w] {
				k = TKeyword
			}
			toks = append(toks, Token{Kind: k, Text: w, Pos: pos})
		default:
			if i+1 < len(src) {
				two := src[i : i+2]
				found := false
				for _, o := range ops3 {
					if o == two {
						found = true
					}
				}
				if found {
					adv()
					adv()
					toks = append(toks, Token{Kind: TOp, Text: two, Pos: pos})
					continue
				}
			}
			switch c {
			case '+', '-', '*', '/', '%', '&', '|', '^', '~', '!', '<', '>', '=', '(', ')', '{', '}', ',', ';':
				adv()
				toks = append(toks, Token{Kind: TOp, Text: string(c), Pos: pos})
			default:
				return nil, &Error{pos, fmt.Sprintf("unexpected character %q", c)}
			}
		}
	}
	toks = append(toks, Token{Kind: TEOF, Pos: Pos{line, col}})
	return toks, nil
}

// ---- AST ----

type Expr interface{ exprPos() Pos }
type Stmt interface{ stmtPos() Pos }

type (
	IntLit struct {
		P Pos
		V int64
	}
	VarRef struct {
		P    Pos
		Name string
		Slot int // resolved by checker
	}
	Unary struct {
		P  Pos
		Op string // - ! ~
		X  Expr
		d  int // tree depth, bounded by the parser
	}
	Binary struct {
		P    Pos
		Op   string
		L, R Expr
		d    int
	}
	Call struct {
		P    Pos
		Name string
		Args []Expr
		d    int
	}
)

func (e *IntLit) exprPos() Pos { return e.P }
func (e *VarRef) exprPos() Pos { return e.P }
func (e *Unary) exprPos() Pos  { return e.P }
func (e *Binary) exprPos() Pos { return e.P }
func (e *Call) exprPos() Pos   { return e.P }

type (
	VarDecl struct {
		P    Pos
		Name string
		Init Expr
		Slot int
	}
	Assign struct {
		P    Pos
		Name string
		X    Expr
		Slot int
	}
	If struct {
		P    Pos
		Cond Expr
		Then *BlockStmt
		Else Stmt // *BlockStmt, *If or nil
	}
	While struct {
		P    Pos
		Cond Expr
		Body *BlockStmt
	}
	For struct {
		P    Pos
		Init Stmt // may be nil
		Cond Expr // may be nil (=true)
		Post Stmt // may be nil
		Body *BlockStmt
	}
	Return struct {
		P Pos
		X Expr // may be nil
	}
	Break    struct{ P Pos }
	Continue struct{ P Pos }
	Print    struct {
		P Pos
		X Expr
	}
	ExprStmt struct {
		P Pos
		X Expr
	}
	BlockStmt struct {
		P     Pos
		Stmts []Stmt
	}
)

func (s *VarDecl) stmtPos() Pos   { return s.P }
func (s *Assign) stmtPos() Pos    { return s.P }
func (s *If) stmtPos() Pos        { return s.P }
func (s *While) stmtPos() Pos     { return s.P }
func (s *For) stmtPos() Pos       { return s.P }
func (s *Return) stmtPos() Pos    { return s.P }
func (s *Break) stmtPos() Pos     { return s.P }
func (s *Continue) stmtPos() Pos  { return s.P }
func (s *Print) stmtPos() Pos     { return s.P }
func (s *ExprStmt) stmtPos() Pos  { return s.P }
func (s *BlockStmt) stmtPos() Pos { return s.P }

type FuncDecl struct {
	P      Pos
	Name   string
	Params []string
	Body   *BlockStmt
	NSlots int // total variable slots (params first), set by checker
}

type Program struct {
	Funcs  []*FuncDecl
	ByName map[string]*FuncDecl
}

// Nesting limits keep every recursive pass (checker, lowering, interpreter) far
// away from the Go stack limit on hostile input.
const (
	maxExprDepth = 2000
	maxStmtNest  = 300
)

func exprDepth(e Expr) int {
	switch e := e.(type) {
	case *Unary:
		return e.d
	case *Binary:
		return e.d
	case *Call:
		return e.d
	}
	return 1
}
