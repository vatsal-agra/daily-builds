package cas

import (
	"fmt"
	"math/big"
	"strings"
	"unicode"
)

// ParseError carries the position of a syntax error.
type ParseError struct {
	Msg string
	Pos int
	Src string
}

func (p *ParseError) Error() string {
	return fmt.Sprintf("%s\n  %s\n  %s^", p.Msg, p.Src, strings.Repeat(" ", p.Pos))
}

type tokKind int

const (
	tEOF tokKind = iota
	tNum
	tIdent
	tOp
)

type token struct {
	k   tokKind
	s   string
	pos int
}

// Callable decides whether name( ... ) is a function call rather than implicit multiplication.
// The interpreter extends this with its command names.
var Callable = func(name string) bool { return false }

func lex(src string) ([]token, error) {
	var out []token
	rs := []rune(src)
	for i := 0; i < len(rs); {
		c := rs[i]
		switch {
		case unicode.IsSpace(c):
			i++
		case unicode.IsDigit(c) || (c == '.' && i+1 < len(rs) && unicode.IsDigit(rs[i+1])):
			j := i
			for j < len(rs) && unicode.IsDigit(rs[j]) {
				j++
			}
			if j < len(rs) && rs[j] == '.' {
				j++
				for j < len(rs) && unicode.IsDigit(rs[j]) {
					j++
				}
			}
			if j < len(rs) && (rs[j] == 'E') { // scientific: 1E3
				k := j + 1
				if k < len(rs) && (rs[k] == '+' || rs[k] == '-') {
					k++
				}
				if k < len(rs) && unicode.IsDigit(rs[k]) {
					for k < len(rs) && unicode.IsDigit(rs[k]) {
						k++
					}
					j = k
				}
			}
			out = append(out, token{tNum, string(rs[i:j]), i})
			i = j
		case unicode.IsLetter(c) || c == '_':
			j := i
			for j < len(rs) && (unicode.IsLetter(rs[j]) || unicode.IsDigit(rs[j]) || rs[j] == '_') {
				j++
			}
			out = append(out, token{tIdent, string(rs[i:j]), i})
			i = j
		case c == '*' && i+1 < len(rs) && rs[i+1] == '*':
			out = append(out, token{tOp, "^", i})
			i += 2
		case strings.ContainsRune("+-*/^()[],=", c):
			out = append(out, token{tOp, string(c), i})
			i++
		default:
			return nil, &ParseError{fmt.Sprintf("unexpected character %q", c), i, src}
		}
	}
	out = append(out, token{tEOF, "", len(rs)})
	return out, nil
}

type parser struct {
	toks []token
	p    int
	src  string
}

func (ps *parser) peek() token { return ps.toks[ps.p] }
func (ps *parser) next() token { t := ps.toks[ps.p]; ps.p++; return t }
func (ps *parser) isOp(s string) bool {
	t := ps.peek()
	return t.k == tOp && t.s == s
}
func (ps *parser) errf(pos int, f string, a ...any) *ParseError {
	return &ParseError{fmt.Sprintf(f, a...), pos, ps.src}
}

// Parse parses one expression (or an equation a = b, returned as eq(a, b)).
func Parse(src string) (res E, err error) {
	toks, err := lex(src)
	if err != nil {
		return nil, err
	}
	if len(toks) == 1 {
		return nil, &ParseError{"empty expression", 0, src}
	}
	ps := &parser{toks: toks, src: src}
	defer func() {
		if r := recover(); r != nil {
			switch x := r.(type) {
			case *ParseError:
				err = x
			case MathError:
				err = x
			default:
				panic(r)
			}
		}
	}()
	res = ps.equation()
	if t := ps.peek(); t.k != tEOF {
		return nil, ps.errf(t.pos, "unexpected %q", t.s)
	}
	return res, nil
}

// MustParse is for tests and constants.
func MustParse(src string) E {
	e, err := Parse(src)
	if err != nil {
		panic(err)
	}
	return e
}

func (ps *parser) equation() E {
	l := ps.sum()
	if ps.isOp("=") {
		ps.next()
		r := ps.sum()
		return &Expr{K: KFn, S: "eq", A: []E{l, r}}
	}
	return l
}

func (ps *parser) sum() E {
	terms := []E{ps.term()}
	for {
		switch {
		case ps.isOp("+"):
			ps.next()
			terms = append(terms, ps.term())
		case ps.isOp("-"):
			ps.next()
			terms = append(terms, Neg(ps.term()))
		default:
			return Add(terms...)
		}
	}
}

func (ps *parser) startsPrimary() bool {
	t := ps.peek()
	return t.k == tNum || t.k == tIdent || (t.k == tOp && (t.s == "(" || t.s == "["))
}

func (ps *parser) term() E {
	acc := ps.unary()
	for {
		switch {
		case ps.isOp("*"):
			ps.next()
			acc = Mul(acc, ps.unary())
		case ps.isOp("/"):
			ps.next()
			acc = Div(acc, ps.unary())
		case ps.startsPrimary():
			acc = Mul(acc, ps.unary()) // implicit multiplication
		default:
			return acc
		}
	}
}

func (ps *parser) unary() E {
	if ps.isOp("-") {
		ps.next()
		return Neg(ps.unary())
	}
	if ps.isOp("+") {
		ps.next()
		return ps.unary()
	}
	return ps.power()
}

func (ps *parser) power() E {
	base := ps.primary()
	if ps.isOp("^") {
		ps.next()
		return Pow(base, ps.unary())
	}
	return base
}

func parseDecimal(s string) (*big.Rat, bool) {
	r, ok := new(big.Rat).SetString(s)
	return r, ok
}

func (ps *parser) primary() E {
	t := ps.next()
	switch t.k {
	case tNum:
		r, ok := parseDecimal(t.s)
		if !ok {
			panic(ps.errf(t.pos, "bad number %q", t.s))
		}
		return Num(r)
	case tIdent:
		if ps.isOp("(") && (IsKnownFn(t.s) || specialFn(t.s) || Callable(t.s)) {
			ps.next()
			var args []E
			if !ps.isOp(")") {
				for {
					args = append(args, ps.equation())
					if ps.isOp(",") {
						ps.next()
						continue
					}
					break
				}
			}
			if !ps.isOp(")") {
				panic(ps.errf(ps.peek().pos, "expected ')'"))
			}
			ps.next()
			return buildCall(ps, t, args)
		}
		return Sym(t.s)
	case tOp:
		switch t.s {
		case "(":
			e := ps.equation()
			if !ps.isOp(")") {
				panic(ps.errf(ps.peek().pos, "expected ')'"))
			}
			ps.next()
			return e
		case "[":
			return ps.list()
		}
	}
	if t.k == tEOF {
		panic(ps.errf(t.pos, "unexpected end of input"))
	}
	panic(ps.errf(t.pos, "unexpected %q", t.s))
}

// list parses [a, b, c] or [[..],[..]] into a matrix (a flat list is a row vector).
func (ps *parser) list() E {
	var items []E
	if !ps.isOp("]") {
		for {
			items = append(items, ps.equation())
			if ps.isOp(",") {
				ps.next()
				continue
			}
			break
		}
	}
	if !ps.isOp("]") {
		panic(ps.errf(ps.peek().pos, "expected ']'"))
	}
	ps.next()
	if len(items) == 0 {
		panic(ps.errf(ps.peek().pos, "empty matrix"))
	}
	if items[0].K == KMat && items[0].R == 1 && listLike(items) {
		c := items[0].C
		var cells []E
		for _, it := range items {
			if it.K != KMat || it.R != 1 || it.C != c {
				panic(ps.errf(ps.peek().pos, "ragged matrix rows"))
			}
			cells = append(cells, it.A...)
		}
		return &Expr{K: KMat, A: cells, R: len(items), C: c}
	}
	return &Expr{K: KMat, A: items, R: 1, C: len(items)}
}

func listLike(items []E) bool {
	for _, it := range items {
		if it.K != KMat {
			return false
		}
	}
	return true
}

func specialFn(name string) bool {
	switch name {
	case "sqrt", "log", "sec", "csc", "cot", "abs":
		return true
	}
	return false
}

func buildCall(ps *parser, t token, args []E) E {
	need := func(n int) {
		if len(args) != n {
			panic(ps.errf(t.pos, "%s expects %d argument(s), got %d", t.s, n, len(args)))
		}
	}
	switch t.s {
	case "sqrt":
		need(1)
		return Sqrt(args[0])
	case "log":
		if len(args) == 2 { // log(base, x)
			return Div(Ln(args[1]), Ln(args[0]))
		}
		need(1)
		return Ln(args[0])
	case "sec":
		need(1)
		return Pow(Fn("cos", args[0]), MinusOne)
	case "csc":
		need(1)
		return Pow(Fn("sin", args[0]), MinusOne)
	case "cot":
		need(1)
		return Div(Fn("cos", args[0]), Fn("sin", args[0]))
	case "abs":
		need(1)
		if args[0].K == KNum {
			return Num(new(big.Rat).Abs(args[0].N))
		}
		return &Expr{K: KFn, S: "abs", A: args}
	}
	if IsKnownFn(t.s) {
		need(1)
	}
	return Fn(t.s, args...)
}
