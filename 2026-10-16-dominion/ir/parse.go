package ir

import (
	"fmt"
	"strconv"
	"strings"
)

// ParseError carries a line number.
type ParseError struct {
	Line int
	Msg  string
}

func (e *ParseError) Error() string { return fmt.Sprintf("line %d: %s", e.Line, e.Msg) }

type parser struct {
	f      *Func
	vals   map[string]*Value
	blocks map[string]*Block
	line   int
}

func (p *parser) errf(format string, a ...any) error {
	return &ParseError{p.line, fmt.Sprintf(format, a...)}
}

// Parse reads textual IR (as produced by Module.String).
func Parse(src string) (*Module, error) {
	m := &Module{}
	lines := strings.Split(src, "\n")
	for i := 0; i < len(lines); i++ {
		l := clean(lines[i])
		if l == "" {
			continue
		}
		if !strings.HasPrefix(l, "func @") {
			return nil, &ParseError{i + 1, "expected 'func @name(...) {'"}
		}
		// collect body
		start := i
		var body []string
		var nums []int
		i++
		closed := false
		for ; i < len(lines); i++ {
			c := clean(lines[i])
			if c == "}" {
				closed = true
				break
			}
			body = append(body, c)
			nums = append(nums, i+1)
		}
		if !closed {
			return nil, &ParseError{start + 1, "unterminated function"}
		}
		f, err := parseFunc(clean(lines[start]), start+1, body, nums)
		if err != nil {
			return nil, err
		}
		if m.Func(f.Name) != nil {
			return nil, &ParseError{start + 1, "duplicate function @" + f.Name}
		}
		m.Funcs = append(m.Funcs, f)
	}
	return m, nil
}

func clean(s string) string {
	if i := strings.Index(s, ";"); i >= 0 {
		s = s[:i]
	}
	return strings.TrimSpace(s)
}

type pendingPhi struct {
	v    *Value
	b    *Block
	ents []phiEnt
	line int
}
type phiEnt struct {
	val  string
	pred string
}

func parseFunc(header string, hline int, body []string, nums []int) (*Func, error) {
	p := &parser{vals: map[string]*Value{}, blocks: map[string]*Block{}, line: hline}
	h := strings.TrimSuffix(strings.TrimSpace(header), "{")
	h = strings.TrimSpace(strings.TrimPrefix(h, "func @"))
	op := strings.Index(h, "(")
	cp := strings.LastIndex(h, ")")
	if op < 0 || cp < op {
		return nil, p.errf("bad function header")
	}
	name := h[:op]
	var pnames []string
	if s := strings.TrimSpace(h[op+1 : cp]); s != "" {
		for _, x := range strings.Split(s, ",") {
			pnames = append(pnames, strings.TrimSpace(x))
		}
	}
	f := NewFunc(name, len(pnames))
	p.f = f
	for i, pn := range pnames {
		if !strings.HasPrefix(pn, "%") {
			return nil, p.errf("bad parameter %q", pn)
		}
		if _, dup := p.vals[pn]; dup {
			return nil, p.errf("duplicate name %s", pn)
		}
		p.vals[pn] = f.Params[i]
	}
	// pass 1: blocks
	for i, l := range body {
		if strings.HasSuffix(l, ":") && !strings.Contains(l, " ") {
			bn := strings.TrimSuffix(l, ":")
			p.line = nums[i]
			if _, dup := p.blocks[bn]; dup {
				return nil, p.errf("duplicate block %s", bn)
			}
			p.blocks[bn] = f.NewBlock(bn)
		}
	}
	if len(f.Blocks) == 0 {
		return nil, p.errf("function @%s has no blocks", name)
	}
	var cur *Block
	var phis []pendingPhi
	type edge struct {
		from *Block
		to   []string
		line int
	}
	var edges []edge
	defined := map[string]bool{}
	for i, l := range body {
		p.line = nums[i]
		if strings.HasSuffix(l, ":") && !strings.Contains(l, " ") {
			cur = p.blocks[strings.TrimSuffix(l, ":")]
			continue
		}
		if cur == nil {
			return nil, p.errf("instruction outside block")
		}
		if cur.Term != TermNone {
			return nil, p.errf("instruction after terminator in %s", cur.Name)
		}
		// terminators
		switch {
		case strings.HasPrefix(l, "br "):
			t := strings.TrimSpace(l[3:])
			cur.Term = TermBr
			edges = append(edges, edge{cur, []string{t}, p.line})
			continue
		case strings.HasPrefix(l, "condbr "):
			parts := splitArgs(l[7:])
			if len(parts) != 3 {
				return nil, p.errf("condbr needs 3 operands")
			}
			c, err := p.operand(parts[0])
			if err != nil {
				return nil, err
			}
			cur.Term, cur.Ctrl = TermCondBr, c
			edges = append(edges, edge{cur, parts[1:], p.line})
			continue
		case strings.HasPrefix(l, "ret "):
			c, err := p.operand(strings.TrimSpace(l[4:]))
			if err != nil {
				return nil, err
			}
			cur.Term, cur.Ctrl = TermRet, c
			continue
		}
		dst := ""
		rhs := l
		if k := strings.Index(l, " = "); k >= 0 {
			dst, rhs = strings.TrimSpace(l[:k]), strings.TrimSpace(l[k+3:])
			if !strings.HasPrefix(dst, "%") {
				return nil, p.errf("bad destination %q", dst)
			}
		}
		sp := strings.IndexByte(rhs, ' ')
		opn, rest := rhs, ""
		if sp >= 0 {
			opn, rest = rhs[:sp], strings.TrimSpace(rhs[sp+1:])
		}
		var v *Value
		if dst != "" {
			if defined[dst] {
				return nil, p.errf("redefinition of %s", dst)
			}
			defined[dst] = true
			v = p.get(dst)
			if v.Op == OpParam {
				return nil, p.errf("redefinition of parameter %s", dst)
			}
		} else {
			v = &Value{ID: f.NewID()}
		}
		switch opn {
		case "phi":
			var ents []phiEnt
			for _, part := range splitArgs(rest) {
				part = strings.TrimSpace(part)
				if !strings.HasPrefix(part, "[") || !strings.HasSuffix(part, "]") {
					return nil, p.errf("bad phi entry %q", part)
				}
				in := strings.Split(part[1:len(part)-1], ",")
				if len(in) != 2 {
					return nil, p.errf("bad phi entry %q", part)
				}
				ents = append(ents, phiEnt{strings.TrimSpace(in[0]), strings.TrimSpace(in[1])})
			}
			v.Op = OpPhi
			if dst == "" {
				return nil, p.errf("phi needs a destination")
			}
			cur.Append(v)
			phis = append(phis, pendingPhi{v, cur, ents, p.line})
			continue
		case "alloca":
			n, err := strconv.ParseInt(rest, 10, 64)
			if err != nil || n < 1 || n > 1<<20 {
				return nil, p.errf("bad alloca size %q", rest)
			}
			v.Op, v.Const = OpAlloca, n
		case "call":
			if !strings.HasPrefix(rest, "@") || !strings.HasSuffix(rest, ")") {
				return nil, p.errf("bad call syntax")
			}
			po := strings.Index(rest, "(")
			if po < 0 {
				return nil, p.errf("bad call syntax")
			}
			v.Op, v.Callee = OpCall, rest[1:po]
			if dst == "" {
				return nil, p.errf("call needs a destination")
			}
			for _, a := range splitArgs(rest[po+1 : len(rest)-1]) {
				o, err := p.operand(a)
				if err != nil {
					return nil, err
				}
				v.Args = append(v.Args, o)
			}
		default:
			op, ok := OpByName(opn)
			if !ok || op == OpAlloca || op == OpPhi || op == OpCall {
				return nil, p.errf("unknown opcode %q", opn)
			}
			v.Op = op
			for _, a := range splitArgs(rest) {
				o, err := p.operand(a)
				if err != nil {
					return nil, err
				}
				v.Args = append(v.Args, o)
			}
			if len(v.Args) != op.NumArgs() {
				return nil, p.errf("%s takes %d operands, got %d", opn, op.NumArgs(), len(v.Args))
			}
			if op.HasResultKind() != (dst != "") {
				return nil, p.errf("%s %s a destination", opn, map[bool]string{true: "needs", false: "must not have"}[op.HasResultKind()])
			}
		}
		cur.Append(v)
	}
	for _, b := range f.Blocks {
		if b.Term == TermNone {
			return nil, &ParseError{hline, "block " + b.Name + " has no terminator"}
		}
	}
	for _, e := range edges {
		p.line = e.line
		for _, tn := range e.to {
			t, ok := p.blocks[strings.TrimSpace(tn)]
			if !ok {
				return nil, p.errf("unknown block %q", tn)
			}
			e.from.Succs = append(e.from.Succs, t)
			t.Preds = append(t.Preds, e.from)
		}
	}
	for _, ph := range phis {
		p.line = ph.line
		if len(ph.ents) != len(ph.b.Preds) {
			return nil, p.errf("phi in %s has %d entries but block has %d predecessors", ph.b.Name, len(ph.ents), len(ph.b.Preds))
		}
		used := make([]bool, len(ph.ents))
		ph.v.Args = make([]*Value, len(ph.b.Preds))
		for i, pr := range ph.b.Preds {
			found := false
			for j, e := range ph.ents {
				if !used[j] && e.pred == pr.Name {
					a, err := p.operand(e.val)
					if err != nil {
						return nil, err
					}
					ph.v.Args[i] = a
					used[j] = true
					found = true
					break
				}
			}
			if !found {
				return nil, p.errf("phi in %s lacks entry for predecessor %s", ph.b.Name, pr.Name)
			}
		}
	}
	for name, v := range p.vals {
		if v.Op == OpInvalid {
			return nil, &ParseError{hline, "use of undefined value " + name}
		}
	}
	return f, nil
}

// HasResultKind reports whether an opcode defines a value (by opcode alone).
func (o Op) HasResultKind() bool { return o != OpStore && o != OpPrint }

func (p *parser) get(name string) *Value {
	if v, ok := p.vals[name]; ok {
		return v
	}
	v := &Value{ID: p.f.NewID()}
	p.vals[name] = v
	return v
}

func (p *parser) operand(s string) (*Value, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, p.errf("missing operand")
	}
	if s[0] == '%' {
		return p.get(s), nil
	}
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return nil, p.errf("bad operand %q", s)
	}
	return p.f.Const(n), nil
}

// splitArgs splits on commas that are not inside [...].
func splitArgs(s string) []string {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	var out []string
	depth, start := 0, 0
	for i := 0; i < len(s); i++ {
		switch s[i] {
		case '[':
			depth++
		case ']':
			depth--
		case ',':
			if depth == 0 {
				out = append(out, strings.TrimSpace(s[start:i]))
				start = i + 1
			}
		}
	}
	return append(out, strings.TrimSpace(s[start:]))
}
