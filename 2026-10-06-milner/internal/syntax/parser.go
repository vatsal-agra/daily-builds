package syntax

import "fmt"

type parser struct {
	toks []Token
	i    int
	// layout rule: a token at column 1 on a new line, right after a token that can end an expression,
	// starts a new top-level declaration (so `let f x = x` + newline + `f 1` needs no `;;`).
	// openAt is the token index at which that rule is suspended (the declaration being started).
	layout bool
	openAt int
}

var syntheticSep = Token{Kind: SYM, Text: ";;"}

// declBoundary reports whether token i begins a new top-level declaration by the layout rule.
func (p *parser) declBoundary(i int) bool {
	if !p.layout || i == 0 || i == p.openAt || i >= len(p.toks) {
		return false
	}
	t, prev := p.toks[i], p.toks[i-1]
	if t.Span.Start.Col != 1 || t.Span.Start.Line == prev.Span.End.Line {
		return false
	}
	switch t.Kind {
	case INT, STRING, IDENT, UIDENT:
	case KW:
		if t.Text != "let" && t.Text != "type" {
			return false
		}
	case SYM:
		if t.Text != "(" && t.Text != "[" && t.Text != "!" && t.Text != "{" {
			return false
		}
	default:
		return false
	}
	switch prev.Kind {
	case INT, STRING, IDENT, UIDENT:
		return true
	case KW:
		return prev.Text == "true" || prev.Text == "false" || prev.Text == "end"
	case SYM:
		return prev.Text == ")" || prev.Text == "]" || prev.Text == "_"
	}
	return false
}

// ParseProgram parses a whole source file into declarations.
func ParseProgram(src string) (decls []Decl, err *Diag) {
	toks, d := Lex(src)
	if d != nil {
		return nil, d
	}
	p := &parser{toks: toks, layout: true, openAt: -1}
	defer p.recover(&err)
	for {
		for p.isSym(";;") {
			if !p.declBoundary(p.i) {
				p.i++
			} else {
				break
			}
		}
		if p.peek().Kind == EOF {
			return decls, nil
		}
		p.openAt = p.i
		decls = append(decls, p.parseDecl())
	}
}

// ParseExpr parses a single expression (used by `milner type` / `explain`).
func ParseExpr(src string) (e Expr, err *Diag) {
	toks, d := Lex(src)
	if d != nil {
		return nil, d
	}
	p := &parser{toks: toks}
	defer p.recover(&err)
	e = p.parseExpr()
	for p.isSym(";;") {
		p.i++
	}
	if p.peek().Kind != EOF {
		p.fail("unexpected %s after the end of the expression", p.describe(p.peek()))
	}
	return e, nil
}

func (p *parser) recover(err **Diag) {
	if r := recover(); r != nil {
		if d, ok := r.(*Diag); ok {
			*err = d
			return
		}
		panic(r)
	}
}

func (p *parser) peek() Token {
	if p.declBoundary(p.i) {
		t := syntheticSep
		t.Span = Span{p.toks[p.i].Span.Start, p.toks[p.i].Span.Start}
		return t
	}
	return p.toks[p.i]
}
func (p *parser) peekAt(n int) Token {
	if p.i+n >= len(p.toks) {
		return p.toks[len(p.toks)-1]
	}
	return p.toks[p.i+n]
}
func (p *parser) next() Token {
	if p.declBoundary(p.i) {
		return p.peek() // synthetic separator: consumes nothing
	}
	t := p.toks[p.i]
	if t.Kind != EOF {
		p.i++
	}
	return t
}
func (p *parser) prevSpan() Span { return p.toks[p.i-1].Span }

func (p *parser) isSym(s string) bool { t := p.peek(); return t.Kind == SYM && t.Text == s }
func (p *parser) isKw(s string) bool  { t := p.peek(); return t.Kind == KW && t.Text == s }

func (p *parser) describe(t Token) string {
	if t.Kind == SYM && t.Text == ";;" && t.Span.Start.Off == t.Span.End.Off {
		return "the start of a new declaration (a line beginning at column 1)"
	}
	switch t.Kind {
	case EOF:
		return "end of input"
	case INT:
		return "integer " + t.Text
	case STRING:
		return fmt.Sprintf("string %q", t.Text)
	case KW:
		return "keyword `" + t.Text + "`"
	default:
		return "`" + t.Text + "`"
	}
}

func (p *parser) fail(format string, a ...any) {
	panic(Errorf("syntax", p.peek().Span, format, a...))
}

func (p *parser) expectSym(s, ctx string) Token {
	if !p.isSym(s) {
		p.fail("expected `%s` %s, found %s", s, ctx, p.describe(p.peek()))
	}
	return p.next()
}
func (p *parser) expectKw(s, ctx string) Token {
	if !p.isKw(s) {
		p.fail("expected `%s` %s, found %s", s, ctx, p.describe(p.peek()))
	}
	return p.next()
}

// ---------- declarations ----------

func (p *parser) parseDecl() Decl {
	start := p.peek().Span
	switch {
	case p.isKw("type"):
		p.next()
		var tys []*TypeDecl
		tys = append(tys, p.parseTypeDecl())
		for p.isKw("and") {
			p.next()
			tys = append(tys, p.parseTypeDecl())
		}
		return &DType{Types: tys, Sp: Join(start, p.prevSpan())}
	case p.isKw("let"):
		p.next()
		rec := false
		if p.isKw("rec") {
			p.next()
			rec = true
		}
		bs := p.parseBindings(rec)
		if p.isKw("in") {
			p.next()
			body := p.parseExpr()
			e := &ELet{Rec: rec, Bindings: bs, Body: body, Sp: Join(start, body.ESpan())}
			// allow `let ... in e` followed by more operators? (rare) — treat as a full expression
			return &DExpr{E: e, Sp: e.Sp}
		}
		return &DLet{Rec: rec, Bindings: bs, Sp: Join(start, p.prevSpan())}
	}
	e := p.parseExpr()
	return &DExpr{E: e, Sp: e.ESpan()}
}

func (p *parser) parseTypeDecl() *TypeDecl {
	start := p.peek().Span
	var params []string
	switch {
	case p.peek().Kind == TYVAR:
		params = append(params, p.next().Text[1:])
	case p.isSym("("):
		p.next()
		for {
			t := p.next()
			if t.Kind != TYVAR {
				panic(Errorf("syntax", t.Span, "expected a type variable like 'a, found %s", p.describe(t)))
			}
			params = append(params, t.Text[1:])
			if p.isSym(",") {
				p.next()
				continue
			}
			break
		}
		p.expectSym(")", "after type parameters")
	}
	nameTok := p.next()
	if nameTok.Kind != IDENT {
		panic(Errorf("syntax", nameTok.Span, "expected a lower-case type name, found %s", p.describe(nameTok)))
	}
	p.expectSym("=", "after the type name")
	td := &TypeDecl{Name: nameTok.Text, Params: params}
	if p.isSym("|") {
		p.next()
	}
	if p.peek().Kind != UIDENT {
		td.Alias = p.parseType()
		td.Sp = Join(start, p.prevSpan())
		return td
	}
	for {
		ct := p.next()
		if ct.Kind != UIDENT {
			panic(Errorf("syntax", ct.Span, "expected a constructor name (capitalised), found %s", p.describe(ct)))
		}
		cd := &ConDecl{Name: ct.Text, Sp: ct.Span}
		if p.isKw("of") {
			p.next()
			cd.Args = append(cd.Args, p.parseTyApp())
			for p.isSym("*") {
				p.next()
				cd.Args = append(cd.Args, p.parseTyApp())
			}
			cd.Sp = Join(ct.Span, p.prevSpan())
		}
		td.Cons = append(td.Cons, cd)
		if p.isSym("|") {
			p.next()
			continue
		}
		break
	}
	td.Sp = Join(start, p.prevSpan())
	return td
}

// ---------- types ----------

func (p *parser) parseType() TyExpr {
	t := p.parseTupleTy()
	if p.isSym("->") {
		p.next()
		r := p.parseType()
		return &TyArrow{From: t, To: r, Sp: Join(t.TySpan(), r.TySpan())}
	}
	return t
}

func (p *parser) parseTupleTy() TyExpr {
	t := p.parseTyApp()
	if !p.isSym("*") {
		return t
	}
	elems := []TyExpr{t}
	for p.isSym("*") {
		p.next()
		elems = append(elems, p.parseTyApp())
	}
	return &TyTuple{Elems: elems, Sp: Join(elems[0].TySpan(), elems[len(elems)-1].TySpan())}
}

func (p *parser) parseTyApp() TyExpr {
	var args []TyExpr
	var t TyExpr
	tok := p.peek()
	switch {
	case tok.Kind == TYVAR:
		p.next()
		t = &TyVar{Name: tok.Text[1:], Sp: tok.Span}
	case tok.Kind == IDENT:
		p.next()
		t = &TyCon{Name: tok.Text, Sp: tok.Span}
	case p.isSym("{"):
		p.next()
		rt := &TyRecord{}
		for !p.isSym("}") {
			if p.isSym("..") {
				p.next()
				rt.Open = true
				break
			}
			nt := p.next()
			if nt.Kind != IDENT {
				panic(Errorf("syntax", nt.Span, "expected a field name in the record type, found %s", p.describe(nt)))
			}
			p.expectSym(":", "after the field name")
			rt.Fields = append(rt.Fields, TyField{Name: nt.Text, Ty: p.parseType()})
			if p.isSym(";") {
				p.next()
				continue
			}
			break
		}
		end := p.expectSym("}", "to close the record type")
		rt.Sp = Join(tok.Span, end.Span)
		t = rt
	case p.isSym("("):
		p.next()
		inner := p.parseType()
		if p.isSym(",") {
			args = append(args, inner)
			for p.isSym(",") {
				p.next()
				args = append(args, p.parseType())
			}
			p.expectSym(")", "to close the type argument list")
			if p.peek().Kind != IDENT {
				p.fail("expected a type constructor after the argument list, found %s", p.describe(p.peek()))
			}
			name := p.next()
			t = &TyCon{Name: name.Text, Args: args, Sp: Join(tok.Span, name.Span)}
		} else {
			p.expectSym(")", "to close the parenthesised type")
			t = inner
		}
	default:
		p.fail("expected a type, found %s", p.describe(tok))
	}
	for p.peek().Kind == IDENT {
		name := p.next()
		t = &TyCon{Name: name.Text, Args: []TyExpr{t}, Sp: Join(t.TySpan(), name.Span)}
	}
	return t
}

// ---------- bindings ----------

func (p *parser) startsPatAtom() bool {
	t := p.peek()
	switch t.Kind {
	case INT, STRING, IDENT, UIDENT:
		return true
	case KW:
		return t.Text == "true" || t.Text == "false"
	case SYM:
		return t.Text == "(" || t.Text == "[" || t.Text == "_" || t.Text == "{"
	}
	return false
}

func (p *parser) parseBindings(rec bool) []*Binding {
	var bs []*Binding
	for {
		bs = append(bs, p.parseBinding(rec))
		if p.isKw("and") {
			p.next()
			continue
		}
		return bs
	}
}

func (p *parser) parseBinding(rec bool) *Binding {
	start := p.peek().Span
	var pat Pat
	var params []Pat
	if p.peek().Kind == IDENT {
		nameTok := p.next()
		pat = &PVar{Name: nameTok.Text, Sp: nameTok.Span}
		for p.startsPatAtom() {
			params = append(params, p.parsePatAtom())
		}
	} else {
		if rec {
			p.fail("`let rec` must bind a function name, found %s", p.describe(p.peek()))
		}
		pat = p.parsePat()
	}
	var retTy TyExpr
	if p.isSym(":") {
		p.next()
		retTy = p.parseType()
	}
	p.expectSym("=", "in a let binding")
	body := p.parseExpr()
	if retTy != nil {
		body = &EAnnot{E: body, Ty: retTy, Sp: body.ESpan()}
	}
	if len(params) > 0 {
		body = &EFun{Params: params, Body: body, Sp: Join(params[0].PSpan(), body.ESpan())}
	}
	return &Binding{Pat: pat, Expr: body, Sp: Join(start, body.ESpan())}
}

// ---------- expressions ----------

func (p *parser) startsExpr() bool {
	t := p.peek()
	switch t.Kind {
	case INT, STRING, IDENT, UIDENT:
		return true
	case KW:
		switch t.Text {
		case "let", "fun", "function", "if", "match", "true", "false", "begin":
			return true
		}
	case SYM:
		switch t.Text {
		case "(", "[", "!", "-", "_", "{":
			return true
		}
	}
	return false
}

func (p *parser) parseExpr() Expr {
	e := p.parseNoSeq()
	for p.isSym(";") {
		save := p.i
		p.next()
		if !p.startsExpr() {
			p.i = save + 1 // trailing `;` is allowed before a closer
			break
		}
		r := p.parseNoSeq()
		e = &ESeq{A: e, B: r, Sp: Join(e.ESpan(), r.ESpan())}
	}
	return e
}

func (p *parser) parseNoSeq() Expr {
	t := p.peek()
	if t.Kind == KW {
		switch t.Text {
		case "let":
			p.next()
			rec := false
			if p.isKw("rec") {
				p.next()
				rec = true
			}
			bs := p.parseBindings(rec)
			p.expectKw("in", "after the let bindings")
			body := p.parseExpr()
			return &ELet{Rec: rec, Bindings: bs, Body: body, Sp: Join(t.Span, body.ESpan())}
		case "fun":
			p.next()
			var params []Pat
			for !p.isSym("->") {
				if !p.startsPatAtom() {
					p.fail("expected a parameter pattern or `->` in `fun`, found %s", p.describe(p.peek()))
				}
				params = append(params, p.parsePatAtom())
			}
			if len(params) == 0 {
				p.fail("`fun` needs at least one parameter")
			}
			p.expectSym("->", "in `fun`")
			body := p.parseExpr()
			return &EFun{Params: params, Body: body, Sp: Join(t.Span, body.ESpan())}
		case "function":
			p.next()
			arms := p.parseArms()
			name := "$arg"
			sp := Join(t.Span, arms[len(arms)-1].Sp)
			m := &EMatch{Scrut: &EVar{Name: name, Sp: t.Span}, Arms: arms, Sp: sp}
			return &EFun{Params: []Pat{&PVar{Name: name, Sp: t.Span}}, Body: m, Sp: sp}
		case "if":
			p.next()
			c := p.parseNoSeq()
			p.expectKw("then", "after the `if` condition")
			th := p.parseNoSeq()
			var el Expr
			end := th.ESpan()
			if p.isKw("else") {
				p.next()
				el = p.parseNoSeq()
				end = el.ESpan()
			} else {
				el = &EUnit{Sp: Span{end.End, end.End}}
			}
			return &EIf{Cond: c, Then: th, Else: el, Sp: Join(t.Span, end)}
		case "match":
			p.next()
			scrut := p.parseExpr()
			p.expectKw("with", "after the `match` scrutinee")
			arms := p.parseArms()
			return &EMatch{Scrut: scrut, Arms: arms, Sp: Join(t.Span, arms[len(arms)-1].Sp)}
		}
	}
	return p.parseAssign()
}

func (p *parser) parseArms() []*Arm {
	if p.isSym("|") {
		p.next()
	}
	var arms []*Arm
	for {
		start := p.peek().Span
		pat := p.parsePat()
		var guard Expr
		if p.isKw("when") {
			p.next()
			guard = p.parseExpr()
		}
		p.expectSym("->", "after the pattern")
		body := p.parseExpr()
		arms = append(arms, &Arm{Pat: pat, Guard: guard, Body: body, Sp: Join(start, body.ESpan())})
		if p.isSym("|") {
			p.next()
			continue
		}
		return arms
	}
}

func app2(op string, opSp Span, l, r Expr) Expr {
	f := &EApp{Fn: &EVar{Name: op, Sp: opSp}, Arg: l, Sp: Join(l.ESpan(), opSp)}
	return &EApp{Fn: f, Arg: r, Sp: Join(l.ESpan(), r.ESpan())}
}

func (p *parser) parseAssign() Expr {
	l := p.parseTuple()
	if p.isSym(":=") {
		op := p.next()
		r := p.parseAssign()
		return app2(":=", op.Span, l, r)
	}
	return l
}

func (p *parser) parseTuple() Expr {
	first := p.parseOr()
	if !p.isSym(",") {
		return first
	}
	elems := []Expr{first}
	for p.isSym(",") {
		p.next()
		elems = append(elems, p.parseOr())
	}
	return &ETuple{Elems: elems, Sp: Join(first.ESpan(), elems[len(elems)-1].ESpan())}
}

func (p *parser) parseOr() Expr {
	l := p.parseAnd()
	if p.isSym("||") {
		p.next()
		r := p.parseOr()
		return &EOr{L: l, R: r, Sp: Join(l.ESpan(), r.ESpan())}
	}
	return l
}

func (p *parser) parseAnd() Expr {
	l := p.parseCmp()
	if p.isSym("&&") {
		p.next()
		r := p.parseAnd()
		return &EAnd{L: l, R: r, Sp: Join(l.ESpan(), r.ESpan())}
	}
	return l
}

func (p *parser) parseCmp() Expr {
	l := p.parseConcat()
	for {
		t := p.peek()
		if t.Kind != SYM {
			return l
		}
		switch t.Text {
		case "=", "<>", "<", ">", "<=", ">=":
			p.next()
			r := p.parseConcat()
			l = app2(t.Text, t.Span, l, r)
		case "|>":
			p.next()
			r := p.parseConcat()
			l = &EApp{Fn: r, Arg: l, Sp: Join(l.ESpan(), r.ESpan())}
		default:
			return l
		}
	}
}

func (p *parser) parseConcat() Expr {
	l := p.parseCons()
	if p.isSym("^") || p.isSym("@") {
		op := p.next()
		r := p.parseConcat()
		return app2(op.Text, op.Span, l, r)
	}
	return l
}

func (p *parser) parseCons() Expr {
	l := p.parseAdd()
	if p.isSym("::") {
		p.next()
		r := p.parseCons()
		sp := Join(l.ESpan(), r.ESpan())
		return &ECon{Name: "::", Arg: &ETuple{Elems: []Expr{l, r}, Sp: sp}, Sp: sp}
	}
	return l
}

func (p *parser) parseAdd() Expr {
	l := p.parseMul()
	for p.isSym("+") || p.isSym("-") {
		op := p.next()
		r := p.parseMul()
		l = app2(op.Text, op.Span, l, r)
	}
	return l
}

func (p *parser) parseMul() Expr {
	l := p.parseUnary()
	for p.isSym("*") || p.isSym("/") || p.isKw("mod") {
		op := p.next()
		r := p.parseUnary()
		l = app2(op.Text, op.Span, l, r)
	}
	return l
}

func (p *parser) parseUnary() Expr {
	t := p.peek()
	if t.Kind == SYM && t.Text == "-" {
		p.next()
		if n := p.peek(); n.Kind == INT && n.Span.Start.Off == t.Span.End.Off {
			p.next()
			return &EInt{Val: -n.Int, Sp: Join(t.Span, n.Span)}
		}
		e := p.parseUnary()
		return &EApp{Fn: &EVar{Name: "~-", Sp: t.Span}, Arg: e, Sp: Join(t.Span, e.ESpan())}
	}
	if t.Kind == KW {
		switch t.Text {
		case "let", "fun", "function", "if", "match":
			return p.parseNoSeq()
		}
	}
	return p.parseApp()
}

func (p *parser) startsAtom() bool {
	t := p.peek()
	switch t.Kind {
	case INT, STRING, IDENT, UIDENT:
		return true
	case KW:
		return t.Text == "true" || t.Text == "false" || t.Text == "begin"
	case SYM:
		return t.Text == "(" || t.Text == "[" || t.Text == "!" || t.Text == "_" || t.Text == "{"
	}
	return false
}

// parsePostfix parses an atom followed by any number of `.field` selections.
func (p *parser) parsePostfix() Expr {
	e := p.parseAtom()
	for p.isSym(".") {
		p.next()
		nt := p.next()
		if nt.Kind != IDENT {
			panic(Errorf("syntax", nt.Span, "expected a field name after `.`, found %s", p.describe(nt)))
		}
		e = &EField{E: e, Name: nt.Text, NameSp: nt.Span, Sp: Join(e.ESpan(), nt.Span)}
	}
	return e
}

func (p *parser) parseApp() Expr {
	head := p.parsePostfix()
	if c, ok := head.(*ECon); ok && c.Arg == nil && p.startsAtom() {
		arg := p.parsePostfix()
		head = &ECon{Name: c.Name, Arg: arg, Sp: Join(c.Sp, arg.ESpan())}
	}
	for p.startsAtom() {
		arg := p.parsePostfix()
		head = &EApp{Fn: head, Arg: arg, Sp: Join(head.ESpan(), arg.ESpan())}
	}
	return head
}

func (p *parser) parseFieldInits(ctx string) []*FieldInit {
	var fields []*FieldInit
	for !p.isSym("}") {
		nt := p.next()
		if nt.Kind != IDENT {
			panic(Errorf("syntax", nt.Span, "expected a field name %s, found %s", ctx, p.describe(nt)))
		}
		fi := &FieldInit{Name: nt.Text, Sp: nt.Span}
		if p.isSym("=") {
			p.next()
			fi.Expr = p.parseNoSeq()
			fi.Sp = Join(nt.Span, fi.Expr.ESpan())
		} else {
			fi.Expr = &EVar{Name: nt.Text, Sp: nt.Span} // pun: { x } means { x = x }
		}
		fields = append(fields, fi)
		if p.isSym(";") {
			p.next()
			continue
		}
		break
	}
	return fields
}

func (p *parser) parseRecordExpr(open Token) Expr {
	// { base with f = e; ... }  — detect `IDENT with` / a general expression followed by `with`
	if p.peek().Kind == IDENT && p.peekAt(1).Kind == KW && p.peekAt(1).Text == "with" {
		bt := p.next()
		p.next() // with
		fields := p.parseFieldInits("in the record update")
		if len(fields) == 0 {
			p.fail("a record update needs at least one `field = value`")
		}
		end := p.expectSym("}", "to close the record update")
		return &ERecordWith{Base: &EVar{Name: bt.Text, Sp: bt.Span}, Fields: fields, Sp: Join(open.Span, end.Span)}
	}
	if p.isSym("}") {
		p.fail("a record needs at least one field (use `()` for the empty value)")
	}
	if !(p.peek().Kind == IDENT && (p.peekAt(1).Kind == SYM && (p.peekAt(1).Text == "=" || p.peekAt(1).Text == ";" || p.peekAt(1).Text == "}"))) {
		// general base expression: { (f x) with ... }
		base := p.parseNoSeq()
		p.expectKw("with", "after the record being updated")
		fields := p.parseFieldInits("in the record update")
		if len(fields) == 0 {
			p.fail("a record update needs at least one `field = value`")
		}
		end := p.expectSym("}", "to close the record update")
		return &ERecordWith{Base: base, Fields: fields, Sp: Join(open.Span, end.Span)}
	}
	fields := p.parseFieldInits("in the record")
	end := p.expectSym("}", "to close the record")
	return &ERecord{Fields: fields, Sp: Join(open.Span, end.Span)}
}

var operatorNames = map[string]bool{
	"+": true, "-": true, "*": true, "/": true, "mod": true, "^": true, "@": true,
	"=": true, "<>": true, "<": true, ">": true, "<=": true, ">=": true, ":=": true, "!": true,
}

func (p *parser) parseAtom() Expr {
	save := p.i
	t := p.next()
	switch t.Kind {
	case INT:
		return &EInt{Val: t.Int, Sp: t.Span}
	case STRING:
		return &EStr{Val: t.Text, Sp: t.Span}
	case IDENT:
		return &EVar{Name: t.Text, Sp: t.Span}
	case UIDENT:
		return &ECon{Name: t.Text, Sp: t.Span}
	case KW:
		switch t.Text {
		case "true":
			return &EBool{Val: true, Sp: t.Span}
		case "false":
			return &EBool{Val: false, Sp: t.Span}
		case "begin":
			e := p.parseExpr()
			p.expectKw("end", "to close `begin`")
			return e
		}
	case SYM:
		switch t.Text {
		case "_":
			return &EHole{Sp: t.Span}
		case "!":
			e := p.parseAtom()
			return &EApp{Fn: &EVar{Name: "!", Sp: t.Span}, Arg: e, Sp: Join(t.Span, e.ESpan())}
		case "(":
			return p.parseParen(t)
		case "{":
			return p.parseRecordExpr(t)
		case "[":
			var elems []Expr
			if !p.isSym("]") {
				for {
					elems = append(elems, p.parseNoSeq())
					if p.isSym(";") {
						p.next()
						if p.isSym("]") {
							break
						}
						continue
					}
					break
				}
			}
			end := p.expectSym("]", "to close the list")
			sp := Join(t.Span, end.Span)
			var res Expr = &ECon{Name: "[]", Sp: Span{end.Span.Start, end.Span.End}}
			for i := len(elems) - 1; i >= 0; i-- {
				esp := Join(elems[i].ESpan(), sp)
				if i == 0 {
					esp = sp
				}
				res = &ECon{Name: "::", Arg: &ETuple{Elems: []Expr{elems[i], res}, Sp: esp}, Sp: esp}
			}
			return res
		}
	}
	p.i = save
	p.fail("expected an expression, found %s", p.describe(t))
	return nil
}

func (p *parser) parseParen(open Token) Expr {
	// operator section: ( + ), ( :: ), ( mod )
	nt := p.peek()
	if (nt.Kind == SYM || nt.Kind == KW) && operatorNames[nt.Text] && p.peekAt(1).Kind == SYM && p.peekAt(1).Text == ")" {
		p.next()
		end := p.next()
		return &EVar{Name: nt.Text, Sp: Join(open.Span, end.Span)}
	}
	if nt.Kind == SYM && nt.Text == "::" && p.peekAt(1).Kind == SYM && p.peekAt(1).Text == ")" {
		p.next()
		end := p.next()
		return &ECon{Name: "::", Sp: Join(open.Span, end.Span)}
	}
	if p.isSym(")") {
		end := p.next()
		return &EUnit{Sp: Join(open.Span, end.Span)}
	}
	e := p.parseExpr()
	if p.isSym(":") {
		p.next()
		ty := p.parseType()
		end := p.expectSym(")", "to close the annotation")
		return &EAnnot{E: e, Ty: ty, Sp: Join(open.Span, end.Span)}
	}
	p.expectSym(")", "to close the parenthesis")
	return e
}

// ---------- patterns ----------

func (p *parser) parsePat() Pat {
	l := p.parseOrPat()
	for p.isKw("as") {
		p.next()
		n := p.next()
		if n.Kind != IDENT {
			panic(Errorf("syntax", n.Span, "expected a variable name after `as`, found %s", p.describe(n)))
		}
		l = &PAs{P: l, Name: n.Text, Sp: Join(l.PSpan(), n.Span)}
	}
	return l
}

func (p *parser) parseOrPat() Pat {
	l := p.parseTuplePat()
	for p.isSym("|") {
		p.next()
		r := p.parseTuplePat()
		l = &POr{L: l, R: r, Sp: Join(l.PSpan(), r.PSpan())}
	}
	return l
}

func (p *parser) parseTuplePat() Pat {
	first := p.parseConsPat()
	if !p.isSym(",") {
		return first
	}
	elems := []Pat{first}
	for p.isSym(",") {
		p.next()
		elems = append(elems, p.parseConsPat())
	}
	return &PTuple{Elems: elems, Sp: Join(first.PSpan(), elems[len(elems)-1].PSpan())}
}

func (p *parser) parseConsPat() Pat {
	l := p.parseAppPat()
	if p.isSym("::") {
		p.next()
		r := p.parseConsPat()
		sp := Join(l.PSpan(), r.PSpan())
		return &PCon{Name: "::", Arg: &PTuple{Elems: []Pat{l, r}, Sp: sp}, Sp: sp}
	}
	return l
}

func (p *parser) parseAppPat() Pat {
	if p.peek().Kind == UIDENT {
		c := p.next()
		if p.startsPatAtom() {
			arg := p.parsePatAtom()
			return &PCon{Name: c.Text, Arg: arg, Sp: Join(c.Span, arg.PSpan())}
		}
		return &PCon{Name: c.Text, Sp: c.Span}
	}
	return p.parsePatAtom()
}

func (p *parser) parsePatAtom() Pat {
	save := p.i
	t := p.next()
	switch t.Kind {
	case INT:
		return &PInt{Val: t.Int, Sp: t.Span}
	case STRING:
		return &PStr{Val: t.Text, Sp: t.Span}
	case IDENT:
		return &PVar{Name: t.Text, Sp: t.Span}
	case UIDENT:
		return &PCon{Name: t.Text, Sp: t.Span}
	case KW:
		switch t.Text {
		case "true":
			return &PBool{Val: true, Sp: t.Span}
		case "false":
			return &PBool{Val: false, Sp: t.Span}
		}
	case SYM:
		switch t.Text {
		case "_":
			return &PWild{Sp: t.Span}
		case "-":
			if n := p.peek(); n.Kind == INT {
				p.next()
				return &PInt{Val: -n.Int, Sp: Join(t.Span, n.Span)}
			}
		case "(":
			if p.isSym(")") {
				end := p.next()
				return &PUnit{Sp: Join(t.Span, end.Span)}
			}
			inner := p.parsePat()
			if p.isSym(":") {
				p.next()
				ty := p.parseType()
				end := p.expectSym(")", "to close the annotated pattern")
				return &PAnnot{P: inner, Ty: ty, Sp: Join(t.Span, end.Span)}
			}
			p.expectSym(")", "to close the pattern")
			return inner
		case "{":
			rp := &PRecord{}
			for !p.isSym("}") {
				if p.isSym("..") && len(rp.Fields) > 0 { // `..` documents that other fields are ignored (the default)
					p.next()
					break
				}
				nt := p.next()
				if nt.Kind != IDENT {
					panic(Errorf("syntax", nt.Span, "expected a field name in the record pattern, found %s", p.describe(nt)))
				}
				fp := &FieldPat{Name: nt.Text, Sp: nt.Span}
				if p.isSym("=") {
					p.next()
					fp.Pat = p.parsePat()
					fp.Sp = Join(nt.Span, fp.Pat.PSpan())
				} else {
					fp.Pat = &PVar{Name: nt.Text, Sp: nt.Span}
				}
				rp.Fields = append(rp.Fields, fp)
				if p.isSym(";") {
					p.next()
					continue
				}
				break
			}
			if len(rp.Fields) == 0 {
				p.fail("a record pattern needs at least one field")
			}
			end := p.expectSym("}", "to close the record pattern")
			rp.Sp = Join(t.Span, end.Span)
			return rp
		case "[":
			var elems []Pat
			if !p.isSym("]") {
				for {
					elems = append(elems, p.parsePat())
					if p.isSym(";") {
						p.next()
						if p.isSym("]") {
							break
						}
						continue
					}
					break
				}
			}
			end := p.expectSym("]", "to close the list pattern")
			sp := Join(t.Span, end.Span)
			var res Pat = &PCon{Name: "[]", Sp: end.Span}
			for i := len(elems) - 1; i >= 0; i-- {
				res = &PCon{Name: "::", Arg: &PTuple{Elems: []Pat{elems[i], res}, Sp: sp}, Sp: sp}
			}
			return res
		}
	}
	p.i = save
	p.fail("expected a pattern, found %s", p.describe(t))
	return nil
}

// ParseType parses a standalone type expression (used for built-in signatures).
func ParseType(src string) (t TyExpr, err *Diag) {
	toks, d := Lex(src)
	if d != nil {
		return nil, d
	}
	p := &parser{toks: toks}
	defer p.recover(&err)
	t = p.parseType()
	if p.peek().Kind != EOF {
		p.fail("unexpected %s after the type", p.describe(p.peek()))
	}
	return t, nil
}
