package hdl

import (
	"fmt"
	"math/big"
	"strings"
)

type parser struct {
	file string
	toks []token
	pos  int
}

type parseAbort struct{ err *Error }

func (p *parser) fail(pos Pos, format string, args ...any) {
	panic(parseAbort{&Error{File: p.file, Pos: pos, Msg: fmt.Sprintf(format, args...)}})
}

// Parse parses Verilog-subset source text.
func Parse(filename, src string) (f *File, err error) {
	toks, lerr := lex(src)
	if lerr != nil {
		if e, ok := lerr.(*Error); ok {
			e.File = filename
		}
		return nil, lerr
	}
	p := &parser{file: filename, toks: toks}
	defer func() {
		if r := recover(); r != nil {
			if pa, ok := r.(parseAbort); ok {
				f, err = nil, pa.err
				return
			}
			panic(r)
		}
	}()
	f = &File{Name: filename}
	for p.cur().kind != tEOF {
		if !p.isIdent("module") {
			p.fail(p.cur().pos, "expected 'module', found %s", p.desc())
		}
		mod := p.module()
		mod.File = filename
		f.Modules = append(f.Modules, mod)
	}
	return f, nil
}

func (p *parser) cur() token { return p.toks[p.pos] }
func (p *parser) peek(n int) token {
	if p.pos+n < len(p.toks) {
		return p.toks[p.pos+n]
	}
	return p.toks[len(p.toks)-1]
}
func (p *parser) desc() string {
	t := p.cur()
	if t.kind == tEOF {
		return "end of file"
	}
	return fmt.Sprintf("'%s'", t.text)
}
func (p *parser) isSym(s string) bool   { t := p.cur(); return t.kind == tSym && t.text == s }
func (p *parser) isIdent(s string) bool { t := p.cur(); return t.kind == tIdent && t.text == s }
func (p *parser) accept(s string) bool {
	t := p.cur()
	if (t.kind == tSym || t.kind == tIdent) && t.text == s {
		p.pos++
		return true
	}
	return false
}
func (p *parser) expect(s string) token {
	t := p.cur()
	if (t.kind == tSym || t.kind == tIdent) && t.text == s {
		p.pos++
		return t
	}
	p.fail(t.pos, "expected '%s', found %s", s, p.desc())
	return t
}
func (p *parser) ident() token {
	t := p.cur()
	if t.kind != tIdent || (keywords[t.text]) {
		p.fail(t.pos, "expected identifier, found %s", p.desc())
	}
	p.pos++
	return t
}

// ---------------------------------------------------------------- modules

func (p *parser) module() *Module {
	at := p.expect("module").pos
	m := &Module{At: at, Name: p.ident().text}
	if p.accept("#") {
		p.expect("(")
		for {
			p.accept("parameter")
			m.Params = append(m.Params, p.paramAssign(false))
			if !p.accept(",") {
				break
			}
		}
		p.expect(")")
	}
	nonANSI := map[string]bool{}
	if p.accept("(") {
		if !p.isSym(")") {
			if p.isIdent("input") || p.isIdent("output") || p.isIdent("inout") {
				p.ansiPorts(m)
			} else {
				for {
					n := p.ident().text
					m.PortOrder = append(m.PortOrder, n)
					nonANSI[n] = true
					if !p.accept(",") {
						break
					}
				}
			}
		}
		p.expect(")")
	}
	p.expect(";")
	for !p.isIdent("endmodule") {
		if p.cur().kind == tEOF {
			p.fail(p.cur().pos, "missing 'endmodule' for module %s", m.Name)
		}
		p.item(m, nonANSI)
	}
	p.expect("endmodule")
	for n := range nonANSI {
		found := false
		for _, d := range m.Decls {
			if d.Name == n && d.Dir != DirNone {
				found = true
			}
		}
		if !found {
			p.fail(at, "port '%s' of module %s has no direction declaration", n, m.Name)
		}
	}
	return m
}

func (p *parser) paramAssign(local bool) Param {
	if p.isSym("[") {
		p.rng() // ignore width annotation on parameters
	}
	if p.isIdent("signed") {
		p.fail(p.cur().pos, "signed parameters are not supported")
	}
	t := p.ident()
	p.expect("=")
	return Param{At: t.pos, Name: t.text, Value: p.expr(), Local: local}
}

func (p *parser) rng() *Range {
	p.expect("[")
	hi := p.expr()
	p.expect(":")
	lo := p.expr()
	p.expect("]")
	return &Range{hi, lo}
}

func (p *parser) ansiPorts(m *Module) {
	var dir Dir
	isReg := false
	var rng *Range
	for {
		t := p.cur()
		if p.isIdent("input") || p.isIdent("output") || p.isIdent("inout") {
			switch t.text {
			case "input":
				dir = DirInput
			case "output":
				dir = DirOutput
			default:
				dir = DirInout
			}
			p.pos++
			isReg, rng = false, nil
			if p.accept("reg") {
				isReg = true
			} else {
				p.accept("wire")
			}
			if p.isIdent("signed") {
				p.fail(p.cur().pos, "signed ports are not supported")
			}
			if p.isSym("[") {
				rng = p.rng()
			}
		} else if dir == DirNone {
			p.fail(t.pos, "expected port direction, found %s", p.desc())
		}
		n := p.ident()
		d := &Decl{At: n.pos, Name: n.text, Dir: dir, IsReg: isReg, Rng: rng}
		if p.isSym("=") && isReg {
			p.pos++
			d.Init = p.expr()
		}
		m.Decls = append(m.Decls, d)
		m.PortOrder = append(m.PortOrder, n.text)
		if !p.accept(",") {
			break
		}
	}
}

func (p *parser) item(m *Module, nonANSI map[string]bool) {
	t := p.cur()
	if t.kind != tIdent {
		p.fail(t.pos, "unexpected %s in module body", p.desc())
	}
	switch t.text {
	case "input", "output", "inout":
		p.pos++
		dir := map[string]Dir{"input": DirInput, "output": DirOutput, "inout": DirInout}[t.text]
		isReg := false
		if p.accept("reg") {
			isReg = true
		} else {
			p.accept("wire")
		}
		var rng *Range
		if p.isSym("[") {
			rng = p.rng()
		}
		for {
			n := p.ident()
			if !nonANSI[n.text] {
				p.fail(n.pos, "'%s' is not in the port list of module %s", n.text, m.Name)
			}
			m.Decls = append(m.Decls, &Decl{At: n.pos, Name: n.text, Dir: dir, IsReg: isReg, Rng: rng})
			if !p.accept(",") {
				break
			}
		}
		p.expect(";")
	case "wire", "reg", "integer", "tri", "supply0", "supply1":
		if t.text == "tri" || strings.HasPrefix(t.text, "supply") {
			p.fail(t.pos, "'%s' nets are not supported", t.text)
		}
		p.pos++
		if p.isIdent("signed") {
			p.fail(p.cur().pos, "signed declarations are not supported")
		}
		var rng *Range
		if p.isSym("[") {
			rng = p.rng()
		}
		for {
			n := p.ident()
			d := &Decl{At: n.pos, Name: n.text, IsReg: t.text == "reg", IsInt: t.text == "integer", Rng: rng}
			if p.isSym("[") {
				d.Array = p.rng()
				p.fail(n.pos, "memory arrays (%s[...]) are not supported; declare separate registers", n.text)
			}
			m.Decls = append(m.Decls, d)
			if p.accept("=") {
				rhs := p.expr()
				if t.text == "wire" {
					m.Assigns = append(m.Assigns, &ContAssign{At: n.pos, LHS: &Ident{n.pos, n.text}, RHS: rhs})
				} else {
					d.Init = rhs
				}
			}
			if !p.accept(",") {
				break
			}
		}
		p.expect(";")
	case "parameter", "localparam":
		p.pos++
		for {
			m.Params = append(m.Params, p.paramAssign(t.text == "localparam"))
			if !p.accept(",") {
				break
			}
		}
		p.expect(";")
	case "assign":
		p.pos++
		for {
			lhs := p.lvalue()
			p.expect("=")
			m.Assigns = append(m.Assigns, &ContAssign{At: t.pos, LHS: lhs, RHS: p.expr()})
			if !p.accept(",") {
				break
			}
		}
		p.expect(";")
	case "always":
		p.pos++
		m.Always = append(m.Always, p.always(t.pos))
	case "initial":
		p.pos++
		m.Initials = append(m.Initials, &Initial{At: t.pos, Body: p.stmt()})
	case "assert", "assume":
		m.Props = append(m.Props, p.prop(""))
	case "genvar", "generate", "function", "task":
		p.fail(t.pos, "'%s' is not supported by this Verilog subset", t.text)
	default:
		if keywords[t.text] {
			p.fail(t.pos, "unexpected keyword '%s' in module body", t.text)
		}
		// label: assert property ... | instance
		if p.peek(1).kind == tSym && p.peek(1).text == ":" {
			label := p.ident().text
			p.expect(":")
			if !p.isIdent("assert") && !p.isIdent("assume") {
				p.fail(p.cur().pos, "expected 'assert' or 'assume' after label")
			}
			m.Props = append(m.Props, p.prop(label))
			return
		}
		m.Insts = append(m.Insts, p.instance())
	}
}

func (p *parser) prop(label string) *PropDecl {
	t := p.cur()
	p.pos++
	p.expect("property")
	p.expect("(")
	x := p.expr()
	p.expect(")")
	p.expect(";")
	return &PropDecl{At: t.pos, Assume: t.text == "assume", X: x, Name: label}
}

func (p *parser) instance() *Instance {
	mod := p.ident()
	in := &Instance{At: mod.pos, Module: mod.text}
	if p.accept("#") {
		p.expect("(")
		for !p.isSym(")") {
			if p.accept(".") {
				n := p.ident().text
				p.expect("(")
				in.Params = append(in.Params, ParamConn{Name: n, X: p.expr()})
				p.expect(")")
			} else {
				in.Params = append(in.Params, ParamConn{X: p.expr()})
			}
			if !p.accept(",") {
				break
			}
		}
		p.expect(")")
	}
	in.Name = p.ident().text
	p.expect("(")
	for !p.isSym(")") {
		if p.accept(".") {
			n := p.ident().text
			p.expect("(")
			var x Expr
			if !p.isSym(")") {
				x = p.expr()
			}
			p.expect(")")
			in.Conns = append(in.Conns, PortConn{Name: n, X: x})
		} else {
			in.Conns = append(in.Conns, PortConn{X: p.expr()})
		}
		if !p.accept(",") {
			break
		}
	}
	p.expect(")")
	p.expect(";")
	return in
}

func (p *parser) always(at Pos) *Always {
	a := &Always{At: at}
	p.expect("@")
	switch {
	case p.accept("*"):
		a.Comb = true
	case p.accept("("):
		switch {
		case p.accept("*"):
			a.Comb = true
		case p.isIdent("posedge") || p.isIdent("negedge"):
			edge := p.cur()
			p.pos++
			if edge.text == "negedge" {
				p.fail(edge.pos, "negedge clocking is not supported (use posedge)")
			}
			a.Clock = p.ident().text
			if p.isIdent("or") || p.isSym(",") {
				p.fail(p.cur().pos, "asynchronous reset / multi-edge sensitivity is not supported; use a synchronous reset inside @(posedge %s)", a.Clock)
			}
		default:
			// explicit level-sensitive list: treated as @(*)
			for {
				p.ident()
				if p.isSym("[") {
					p.rng()
				}
				if !(p.accept("or") || p.accept(",")) {
					break
				}
			}
			a.Comb = true
		}
		p.expect(")")
	default:
		p.fail(p.cur().pos, "expected '@(...)' after 'always'")
	}
	a.Body = p.stmt()
	return a
}

// ---------------------------------------------------------------- statements

func (p *parser) stmt() Stmt {
	t := p.cur()
	switch {
	case p.accept(";"):
		return &Block{At: t.pos}
	case p.isIdent("begin"):
		p.pos++
		if p.accept(":") {
			p.ident()
		}
		b := &Block{At: t.pos}
		for !p.isIdent("end") {
			if p.cur().kind == tEOF {
				p.fail(t.pos, "'begin' without matching 'end'")
			}
			b.Stmts = append(b.Stmts, p.stmt())
		}
		p.expect("end")
		return b
	case p.isIdent("if"):
		p.pos++
		p.expect("(")
		c := p.expr()
		p.expect(")")
		s := &If{At: t.pos, C: c, Then: p.stmt()}
		if p.accept("else") {
			s.Else = p.stmt()
		}
		return s
	case p.isIdent("case"):
		p.pos++
		p.expect("(")
		cs := &Case{At: t.pos, Sel: p.expr()}
		p.expect(")")
		for !p.isIdent("endcase") {
			if p.cur().kind == tEOF {
				p.fail(t.pos, "'case' without matching 'endcase'")
			}
			var item CaseItem
			if p.accept("default") {
				p.accept(":")
			} else {
				for {
					item.Labels = append(item.Labels, p.expr())
					if !p.accept(",") {
						break
					}
				}
				p.expect(":")
			}
			item.Body = p.stmt()
			cs.Items = append(cs.Items, item)
		}
		p.expect("endcase")
		return cs
	case p.isIdent("casez") || p.isIdent("casex"):
		p.fail(t.pos, "'%s' is not supported (x/z/? patterns); use 'case'", t.text)
	case p.isIdent("for"):
		p.pos++
		p.expect("(")
		init := p.simpleAssign()
		p.expect(";")
		cond := p.expr()
		p.expect(";")
		step := p.simpleAssign()
		p.expect(")")
		return &For{At: t.pos, Init: init, Cond: cond, Step: step, Body: p.stmt()}
	case p.isIdent("while") || p.isIdent("repeat") || p.isIdent("forever"):
		p.fail(t.pos, "'%s' loops are not supported", t.text)
	case t.kind == tIdent && strings.HasPrefix(t.text, "$"):
		p.fail(t.pos, "system task %s is not supported", t.text)
	case t.kind == tSym && t.text == "#":
		p.fail(t.pos, "delays are not supported")
	}
	a := p.simpleAssign()
	p.expect(";")
	return a
}

func (p *parser) simpleAssign() *Assign {
	t := p.cur()
	lhs := p.lvalue()
	nb := false
	if p.accept("<=") {
		nb = true
	} else if !p.accept("=") {
		p.fail(p.cur().pos, "expected '=' or '<=' in assignment, found %s", p.desc())
	}
	return &Assign{At: t.pos, LHS: lhs, RHS: p.expr(), NonBlocking: nb}
}

func (p *parser) lvalue() Expr {
	t := p.cur()
	if p.isSym("{") {
		p.pos++
		c := &Concat{At: t.pos}
		for {
			c.Parts = append(c.Parts, p.lvalue())
			if !p.accept(",") {
				break
			}
		}
		p.expect("}")
		return c
	}
	id := p.ident()
	var e Expr = &Ident{id.pos, id.text}
	return p.postfix(e)
}

// ---------------------------------------------------------------- expressions

func (p *parser) expr() Expr {
	c := p.binary(0)
	if p.isSym("?") {
		at := p.cur().pos
		p.pos++
		t := p.expr()
		p.expect(":")
		f := p.expr()
		return &Ternary{At: at, C: c, T: t, F: f}
	}
	return c
}

var precLevels = [][]string{
	{"||"},
	{"&&"},
	{"|"},
	{"^", "~^", "^~"},
	{"&"},
	{"==", "!=", "===", "!=="},
	{"<", "<=", ">", ">="},
	{"<<", ">>", "<<<", ">>>"},
	{"+", "-"},
	{"*", "/", "%"},
	{"**"},
}

func (p *parser) binary(level int) Expr {
	if level >= len(precLevels) {
		return p.unary()
	}
	l := p.binary(level + 1)
	for {
		t := p.cur()
		if t.kind != tSym {
			return l
		}
		match := false
		for _, op := range precLevels[level] {
			if t.text == op {
				match = true
			}
		}
		if !match {
			return l
		}
		p.pos++
		r := p.binary(level + 1)
		op := t.text
		switch op {
		case "===":
			op = "=="
		case "!==":
			op = "!="
		case "^~":
			op = "~^"
		case "<<<":
			op = "<<"
		}
		l = &Binary{At: t.pos, Op: op, L: l, R: r}
	}
}

func (p *parser) unary() Expr {
	t := p.cur()
	if t.kind == tSym {
		switch t.text {
		case "~", "!", "-", "+", "&", "|", "^", "~&", "~|", "~^", "^~":
			p.pos++
			op := t.text
			if op == "^~" {
				op = "~^"
			}
			return &Unary{At: t.pos, Op: op, X: p.unary()}
		}
	}
	return p.postfix(p.primary())
}

func (p *parser) postfix(e Expr) Expr {
	for p.isSym("[") {
		at := p.cur().pos
		p.pos++
		hi := p.expr()
		ix := &Index{At: at, X: e, Hi: hi}
		switch {
		case p.accept(":"):
			ix.Part = ':'
			ix.Lo = p.expr()
		case p.accept("+:"):
			ix.Part = '+'
			ix.Lo = p.expr()
		case p.accept("-:"):
			ix.Part = '-'
			ix.Lo = p.expr()
		}
		p.expect("]")
		e = ix
	}
	return e
}

func (p *parser) primary() Expr {
	t := p.cur()
	switch {
	case t.kind == tNumber:
		p.pos++
		w, v, err := parseNumber(t.text)
		if err != "" {
			p.fail(t.pos, "%s", err)
		}
		return &Number{At: t.pos, Width: w, Val: v}
	case t.kind == tIdent && strings.HasPrefix(t.text, "$"):
		p.pos++
		c := &Call{At: t.pos, Name: t.text}
		p.expect("(")
		for !p.isSym(")") {
			c.Args = append(c.Args, p.expr())
			if !p.accept(",") {
				break
			}
		}
		p.expect(")")
		return c
	case t.kind == tIdent && !keywords[t.text]:
		p.pos++
		return &Ident{t.pos, t.text}
	case p.isSym("("):
		p.pos++
		e := p.expr()
		p.expect(")")
		return e
	case p.isSym("{"):
		p.pos++
		first := p.expr()
		if p.isSym("{") {
			p.pos++
			c := &Concat{At: t.pos}
			for {
				c.Parts = append(c.Parts, p.expr())
				if !p.accept(",") {
					break
				}
			}
			p.expect("}")
			p.expect("}")
			return &Repl{At: t.pos, Count: first, X: c}
		}
		c := &Concat{At: t.pos, Parts: []Expr{first}}
		for p.accept(",") {
			c.Parts = append(c.Parts, p.expr())
		}
		p.expect("}")
		return c
	}
	p.fail(t.pos, "expected expression, found %s", p.desc())
	return nil
}

// parseNumber decodes Verilog literals; returns an error message on failure.
func parseNumber(s string) (width int, val *big.Int, errMsg string) {
	s = strings.ReplaceAll(s, "_", "")
	q := strings.IndexByte(s, '\'')
	if q < 0 {
		v, ok := new(big.Int).SetString(s, 10)
		if !ok {
			return 0, nil, "malformed number " + s
		}
		return 0, v, ""
	}
	if q > 0 {
		w, ok := new(big.Int).SetString(s[:q], 10)
		if !ok || w.Sign() <= 0 || w.BitLen() > 20 {
			return 0, nil, "invalid literal width in " + s
		}
		width = int(w.Int64())
	}
	rest := s[q+1:]
	if len(rest) > 0 && (rest[0] == 's' || rest[0] == 'S') {
		return 0, nil, "signed literals are not supported"
	}
	if len(rest) < 2 {
		return 0, nil, "malformed number " + s
	}
	base := map[byte]int{'b': 2, 'B': 2, 'o': 8, 'O': 8, 'd': 10, 'D': 10, 'h': 16, 'H': 16}[rest[0]]
	digits := rest[1:]
	if strings.ContainsAny(digits, "xXzZ?") {
		return 0, nil, "x/z/? digits are not supported in literal " + s
	}
	v, ok := new(big.Int).SetString(digits, base)
	if !ok {
		return 0, nil, "malformed number " + s
	}
	if width > 0 {
		mask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(width)), big.NewInt(1))
		v.And(v, mask)
	}
	return width, v, ""
}
