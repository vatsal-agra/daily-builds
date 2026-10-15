package asm

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// Options configure an assembly run.
type Options struct {
	// Include resolves `.include "path"`; nil disables includes.
	Include func(path string) (string, error)
	// NoHeader skips the automatic Nintendo logo / checksum fixup.
	NoHeader bool
	// Defines predefines symbols (like -D).
	Defines map[string]int
}

// Loc is a source position.
type Loc struct {
	File string
	Line int
}

// Result is the output of a successful assembly.
type Result struct {
	ROM     []byte
	Symbols map[string]int
	// Source maps ROM address (bank 0 / fixed region, or bank<<16|addr for switchable banks) to source location.
	Source map[int]Loc
}

// Error is a single assembler diagnostic.
type Error struct {
	Loc Loc
	Msg string
}

func (e Error) Error() string { return fmt.Sprintf("%s:%d: %s", e.Loc.File, e.Loc.Line, e.Msg) }

// ErrorList is returned when assembly fails.
type ErrorList []Error

func (l ErrorList) Error() string {
	var sb strings.Builder
	for i, e := range l {
		if i > 0 {
			sb.WriteByte('\n')
		}
		if i >= 20 {
			fmt.Fprintf(&sb, "... and %d more errors", len(l)-i)
			break
		}
		sb.WriteString(e.Error())
	}
	return sb.String()
}

// FileInclude returns an Include function resolving paths relative to dir.
func FileInclude(dir string) func(string) (string, error) {
	return func(p string) (string, error) {
		b, err := os.ReadFile(filepath.Join(dir, p))
		return string(b), err
	}
}

type srcLine struct {
	Loc
	text string
}

type macro struct {
	name  string
	body  []srcLine
	where Loc
}

type assembler struct {
	opt    Options
	errs   ErrorList
	macros map[string]*macro
	uniq   int

	syms     map[string]int
	lastGlob string

	items []item
	rom   map[int]byte // file offset -> byte
	// state during layout
	virtual bool
	vpc     int
	bank    int
	pc      int

	title    string
	hasTitle bool
	cartType int
	ramCode  int
	hasCart  bool
	hasRAM   bool
	maxOff   int
	src      map[int]Loc
	deferred []deferredEqu
}

type deferredEqu struct {
	name, expr string
	loc        Loc
	glob       string
	pc         int
}

type itemKind int

const (
	kInstr itemKind = iota
	kData8
	kData16
	kFill
)

type operand struct {
	kind string // "lit", "expr", "mem", "spoff"
	text string // literal text (lowercase) or expression source
}

type item struct {
	kind  itemKind
	loc   Loc
	pc    int // logical address
	bank  int
	glob  string // enclosing global label for local-label resolution
	tmpl  *Template
	ops   []operand
	exprs []string // data expressions
	strs  map[int]string
	count int
	fill  int
}

func (a *assembler) dedupe() ErrorList {
	seen := map[Error]bool{}
	var out ErrorList
	for _, e := range a.errs {
		if !seen[e] {
			seen[e] = true
			out = append(out, e)
		}
	}
	return out
}

func (a *assembler) errf(loc Loc, format string, args ...any) {
	a.errs = append(a.errs, Error{loc, fmt.Sprintf(format, args...)})
}

// Assemble assembles source text. name is used in diagnostics.
func Assemble(name, source string, opt Options) (*Result, error) {
	a := &assembler{
		opt: opt, macros: map[string]*macro{}, syms: map[string]int{},
		rom: map[int]byte{}, src: map[int]Loc{}, cartType: 0,
	}
	for k, v := range opt.Defines {
		a.syms[k] = v
	}
	lines := a.preprocess(name, source, 0)
	if len(a.errs) > 0 {
		return nil, a.errs
	}
	a.pass1(lines)
	a.resolveDeferred()
	a.pass2() // keep going after pass-1 errors so one run reports as much as possible
	if len(a.errs) > 0 {
		sort.SliceStable(a.errs, func(i, j int) bool {
			if a.errs[i].Loc.File != a.errs[j].Loc.File {
				return false
			}
			return a.errs[i].Loc.Line < a.errs[j].Loc.Line
		})
		return nil, a.dedupe()
	}
	res := a.finish()
	if len(a.errs) > 0 {
		return nil, a.errs
	}
	return res, nil
}

// ---- preprocessing ----------------------------------------------------

func stripComment(s string) string {
	inQ := byte(0)
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case inQ != 0:
			if c == '\\' && i+1 < len(s) {
				i++
			} else if c == inQ {
				inQ = 0
			}
		case c == '"':
			inQ = c
		case c == '\'' && i+2 < len(s) && s[i+2] == '\'':
			i += 2 // character literal, may contain ';'
		case c == ';':
			return s[:i]
		}
	}
	return s
}

func (a *assembler) preprocess(file, text string, depth int) []srcLine {
	if depth > 16 {
		a.errf(Loc{file, 0}, "include/macro nesting too deep")
		return nil
	}
	var out []srcLine
	raw := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	for i := 0; i < len(raw); i++ {
		loc := Loc{file, i + 1}
		line := strings.TrimSpace(stripComment(raw[i]))
		if line == "" {
			continue
		}
		lower := strings.ToLower(line)
		word, rest := splitWord(line)
		lword := strings.ToLower(word)
		switch {
		case lword == ".include":
			if a.opt.Include == nil {
				a.errf(loc, ".include is not available here")
				continue
			}
			p := strings.Trim(strings.TrimSpace(rest), "\"")
			body, err := a.opt.Include(p)
			if err != nil {
				a.errf(loc, "cannot include %q: %v", p, err)
				continue
			}
			out = append(out, a.preprocess(p, body, depth+1)...)
		case lword == ".macro":
			mname := strings.ToLower(strings.TrimSpace(rest))
			if mname == "" || strings.ContainsAny(mname, " ,") {
				a.errf(loc, ".macro needs a single name")
				continue
			}
			if _, dup := a.macros[mname]; dup {
				a.errf(loc, "macro %q already defined", mname)
			}
			m := &macro{name: mname, where: loc}
			j := i + 1
			closed := false
			for ; j < len(raw); j++ {
				l := strings.TrimSpace(stripComment(raw[j]))
				if strings.EqualFold(l, ".endm") {
					closed = true
					break
				}
				if l != "" {
					m.body = append(m.body, srcLine{Loc{file, j + 1}, l})
				}
			}
			if !closed {
				a.errf(loc, "macro %q has no .endm", mname)
			}
			a.macros[mname] = m
			i = j
		case lword == ".rept":
			n, err := strconv.Atoi(strings.TrimSpace(rest))
			if err != nil || n < 0 || n > 4096 {
				a.errf(loc, ".rept needs a count between 0 and 4096")
				continue
			}
			var body []string
			j := i + 1
			closed := false
			for ; j < len(raw); j++ {
				l := strings.TrimSpace(stripComment(raw[j]))
				if strings.EqualFold(l, ".endr") {
					closed = true
					break
				}
				body = append(body, raw[j])
			}
			if !closed {
				a.errf(loc, ".rept has no .endr")
			}
			for k := 0; k < n; k++ {
				sub := a.preprocess(file, strings.Join(body, "\n"), depth+1)
				for si := range sub {
					sub[si].Line += i + 1 // approximate position inside the file
				}
				out = append(out, sub...)
			}
			i = j
		default:
			// label prefix? macro call may follow "label:"
			prefix := ""
			body := line
			if ci := strings.Index(line, ":"); ci > 0 && isIdentStart(line[0]) && validIdent(line[:ci]) {
				prefix = line[:ci+1]
				body = strings.TrimSpace(line[ci+1:])
			}
			mw, mrest := splitWord(body)
			if m, ok := a.macros[strings.ToLower(mw)]; ok && mw != "" {
				if prefix != "" {
					out = append(out, srcLine{loc, prefix})
				}
				args := splitTopLevel(mrest)
				a.uniq++
				id := a.uniq
				var expanded []string
				for _, bl := range m.body {
					t := bl.text
					t = strings.ReplaceAll(t, `\@`, fmt.Sprintf("_m%d", id))
					for k := 9; k >= 1; k-- {
						v := ""
						if k <= len(args) {
							v = strings.TrimSpace(args[k-1])
						}
						t = strings.ReplaceAll(t, `\`+strconv.Itoa(k), v)
					}
					expanded = append(expanded, t)
				}
				sub := a.preprocess(m.where.File, strings.Join(expanded, "\n"), depth+1)
				for si := range sub {
					sub[si].Loc = loc // report errors at the call site
				}
				out = append(out, sub...)
				continue
			}
			_ = lower
			out = append(out, srcLine{loc, line})
		}
	}
	return out
}

func splitWord(s string) (string, string) {
	s = strings.TrimSpace(s)
	i := strings.IndexAny(s, " \t")
	if i < 0 {
		return s, ""
	}
	return s[:i], strings.TrimSpace(s[i+1:])
}

func validIdent(s string) bool {
	if s == "" || !isIdentStart(s[0]) {
		return false
	}
	for i := 1; i < len(s); i++ {
		if !isIdentChar(s[i]) {
			return false
		}
	}
	return true
}

// splitTopLevel splits on commas outside brackets, parens and quotes.
func splitTopLevel(s string) []string {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil
	}
	var out []string
	depth := 0
	inQ := byte(0)
	start := 0
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case inQ != 0:
			if c == '\\' {
				i++
			} else if c == inQ {
				inQ = 0
			}
		case c == '"':
			inQ = c
		case c == '\'' && i+2 < len(s) && s[i+2] == '\'':
			i += 2
		case c == '[' || c == '(':
			depth++
		case c == ']' || c == ')':
			depth--
		case c == ',' && depth == 0:
			out = append(out, strings.TrimSpace(s[start:i]))
			start = i + 1
		}
	}
	return append(out, strings.TrimSpace(s[start:]))
}

// ---- symbols ------------------------------------------------------------

func (a *assembler) qualify(name, glob string) string {
	if strings.HasPrefix(name, ".") {
		return glob + name
	}
	return name
}

func (a *assembler) lookupFn(glob string) symLookup {
	return func(name string) (int, bool) {
		v, ok := a.syms[a.qualify(name, glob)]
		return v, ok
	}
}

func (a *assembler) define(loc Loc, name string, v int) {
	if _, dup := a.syms[name]; dup {
		a.errf(loc, "symbol %q already defined", name)
		return
	}
	if isReserved(name) {
		a.errf(loc, "%q is a reserved register/condition name", name)
		return
	}
	a.syms[name] = v
}

var reserved = map[string]bool{
	"a": true, "b": true, "c": true, "d": true, "e": true, "h": true, "l": true,
	"af": true, "bc": true, "de": true, "hl": true, "sp": true, "nz": true, "z": true, "nc": true,
	"low": true, "high": true,
}

func isReserved(n string) bool { return reserved[strings.ToLower(n)] }

// ---- pass 1: layout ----------------------------------------------------

func (a *assembler) cursor() int {
	if a.virtual {
		return a.vpc
	}
	return a.pc
}

func (a *assembler) advance(n int) {
	if a.virtual {
		a.vpc += n
	} else {
		a.pc += n
	}
}

func (a *assembler) pass1(lines []srcLine) {
	for _, ln := range lines {
		a.line1(ln)
	}
}

func (a *assembler) line1(ln srcLine) {
	text := ln.text
	loc := ln.Loc
	// "NAME = expr"
	if eq := strings.Index(text, "="); eq > 0 {
		lhs := strings.TrimSpace(text[:eq])
		if validIdent(lhs) && !strings.Contains(text[:eq], "[") {
			a.doEqu(loc, lhs, strings.TrimSpace(text[eq+1:]))
			return
		}
	}
	// labels
	for {
		ci := strings.Index(text, ":")
		if ci <= 0 {
			break
		}
		name := strings.TrimSpace(text[:ci])
		if !validIdent(name) {
			break
		}
		if strings.HasPrefix(name, ".") {
			name = a.lastGlob + name
		} else {
			a.lastGlob = name
		}
		a.define(loc, name, a.cursor())
		text = strings.TrimSpace(text[ci+1:])
	}
	if text == "" {
		return
	}
	word, rest := splitWord(text)
	// "NAME equ expr"
	if r2, r3 := splitWord(rest); strings.EqualFold(r2, "equ") && validIdent(word) {
		a.doEqu(loc, word, r3)
		return
	}
	lw := strings.ToLower(word)
	switch lw { // bare directive spellings used by many assemblers
	case "db", "dw", "ds":
		lw = "." + lw
	}
	if strings.HasPrefix(lw, ".") {
		a.directive(loc, lw, rest)
		return
	}
	a.instruction(loc, lw, rest)
}

func (a *assembler) doEqu(loc Loc, name, expr string) {
	q := a.qualify(name, a.lastGlob)
	v, err := evalExpr(expr, a.cursor(), a.lookupFn(a.lastGlob))
	if err != nil {
		if _, ok := err.(*undefinedError); ok {
			a.deferred = append(a.deferred, deferredEqu{q, expr, loc, a.lastGlob, a.cursor()})
			return
		}
		a.errf(loc, "%v", err)
		return
	}
	a.define(loc, q, v)
}

func (a *assembler) resolveDeferred() {
	for len(a.deferred) > 0 {
		progress := false
		var left []deferredEqu
		for _, d := range a.deferred {
			v, err := evalExpr(d.expr, d.pc, a.lookupFn(d.glob))
			if err != nil {
				if _, ok := err.(*undefinedError); ok {
					left = append(left, d)
					continue
				}
				a.errf(d.loc, "%v", err)
				progress = true
				continue
			}
			a.define(d.loc, d.name, v)
			progress = true
		}
		a.deferred = left
		if !progress {
			for _, d := range left {
				_, err := evalExpr(d.expr, d.pc, a.lookupFn(d.glob))
				a.errf(d.loc, "cannot resolve %q: %v", d.name, err)
			}
			return
		}
	}
}

func (a *assembler) constExpr(loc Loc, s string) (int, bool) {
	v, err := evalExpr(s, a.cursor(), a.lookupFn(a.lastGlob))
	if err != nil {
		a.errf(loc, "%v (this value must be known at its point of use)", err)
		return 0, false
	}
	return v, true
}

func (a *assembler) directive(loc Loc, d, rest string) {
	switch d {
	case ".org":
		v, ok := a.constExpr(loc, rest)
		if !ok {
			return
		}
		if v < 0 || v > 0xFFFF {
			a.errf(loc, ".org address %#x out of range", v)
			return
		}
		if v >= 0x8000 {
			a.virtual, a.vpc = true, v
			return
		}
		a.virtual = false
		a.pc = v
		if v < 0x4000 {
			a.bank = 0
		} else if a.bank == 0 {
			a.bank = 1
		}
	case ".bank":
		v, ok := a.constExpr(loc, rest)
		if !ok {
			return
		}
		if v < 0 || v > 511 {
			a.errf(loc, "bank %d out of range", v)
			return
		}
		a.virtual = false
		a.bank = v
		if v == 0 {
			a.pc = 0
		} else {
			a.pc = 0x4000
		}
	case ".db", ".byte", ".dw", ".word":
		parts := splitTopLevel(rest)
		if len(parts) == 0 {
			a.errf(loc, "%s needs at least one value", d)
			return
		}
		if a.virtual {
			a.errf(loc, "%s cannot emit bytes into RAM (address >= $8000); use .ds to reserve space", d)
			return
		}
		wide := d == ".dw" || d == ".word"
		it := item{loc: loc, pc: a.pc, bank: a.bank, glob: a.lastGlob, strs: map[int]string{}}
		if wide {
			it.kind = kData16
		} else {
			it.kind = kData8
		}
		size := 0
		for _, p := range parts {
			if !wide && len(p) >= 2 && p[0] == '"' && p[len(p)-1] == '"' {
				s, err := strconv.Unquote(p)
				if err != nil {
					a.errf(loc, "bad string literal %s", p)
					return
				}
				for i := 0; i < len(s); i++ {
					it.exprs = append(it.exprs, strconv.Itoa(int(s[i])))
				}
				size += len(s)
				continue
			}
			it.exprs = append(it.exprs, p)
			if wide {
				size += 2
			} else {
				size++
			}
		}
		a.items = append(a.items, it)
		a.advance(size)
	case ".ds", ".space":
		parts := splitTopLevel(rest)
		if len(parts) < 1 || len(parts) > 2 {
			a.errf(loc, ".ds needs a size and optional fill byte")
			return
		}
		n, ok := a.constExpr(loc, parts[0])
		if !ok {
			return
		}
		if n < 0 || n > 0x10000 {
			a.errf(loc, ".ds size %d out of range", n)
			return
		}
		if !a.virtual {
			fill := 0
			if len(parts) == 2 {
				var ok2 bool
				fill, ok2 = a.constExpr(loc, parts[1])
				if !ok2 {
					return
				}
			}
			a.items = append(a.items, item{kind: kFill, loc: loc, pc: a.pc, bank: a.bank, count: n, fill: fill})
		}
		a.advance(n)
	case ".equ":
		parts := splitTopLevel(rest)
		if len(parts) != 2 || !validIdent(parts[0]) {
			a.errf(loc, ".equ needs NAME, value")
			return
		}
		a.doEqu(loc, parts[0], parts[1])
	case ".title":
		s, err := strconv.Unquote(strings.TrimSpace(rest))
		if err != nil || len(s) > 16 {
			a.errf(loc, ".title needs a quoted string of at most 16 characters")
			return
		}
		a.title, a.hasTitle = s, true
	case ".cart":
		v, ok := a.constExpr(loc, rest)
		if ok {
			a.cartType, a.hasCart = v, true
		}
	case ".ramsize":
		v, ok := a.constExpr(loc, rest)
		if ok {
			a.ramCode, a.hasRAM = v, true
		}
	default:
		a.errf(loc, "unknown directive %s", d)
	}
}

var litWords = map[string]string{
	"a": "a", "b": "b", "c": "c", "d": "d", "e": "e", "h": "h", "l": "l",
	"af": "af", "bc": "bc", "de": "de", "hl": "hl", "sp": "sp",
	"nz": "nz", "z": "z", "nc": "nc",
	"[hl]": "[hl]", "[bc]": "[bc]", "[de]": "[de]", "[c]": "[c]",
	"[hl+]": "[hl+]", "[hl-]": "[hl-]", "[hli]": "[hl+]", "[hld]": "[hl-]",
}

func parseOperand(s string) operand {
	compact := strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(s, " ", ""), "\t", ""))
	if l, ok := litWords[compact]; ok {
		return operand{kind: "lit", text: l}
	}
	if len(s) >= 2 && s[0] == '[' && s[len(s)-1] == ']' {
		return operand{kind: "mem", text: strings.TrimSpace(s[1 : len(s)-1])}
	}
	if strings.HasPrefix(compact, "sp+") || strings.HasPrefix(compact, "sp-") {
		idx := strings.IndexAny(strings.ToLower(s), "sS")
		_ = idx
		t := strings.TrimSpace(s)
		t = strings.TrimSpace(t[2:]) // after "sp"
		return operand{kind: "spoff", text: t}
	}
	return operand{kind: "expr", text: s}
}

func (a *assembler) instruction(loc Loc, mn, rest string) {
	if a.virtual {
		a.errf(loc, "cannot emit code at an address >= $8000 (ROM only spans $0000-$7FFF)")
		return
	}
	parts := splitTopLevel(rest)
	ops := make([]operand, len(parts))
	for i, p := range parts {
		if p == "" {
			a.errf(loc, "empty operand in %s", mn)
			return
		}
		if msg := badOperandSyntax(p); msg != "" {
			a.errf(loc, "%s: %s", mn, msg)
			return
		}
		ops[i] = parseOperand(p)
	}
	// ldh [c],a / ldh a,[c] and jp [hl] are accepted spellings of ld [c],a / ld a,[c] / jp hl
	if mn == "ldh" && len(ops) == 2 && (ops[0].text == "[c]" || ops[1].text == "[c]") && (ops[0].kind == "lit" || ops[1].kind == "lit") {
		mn = "ld"
	}
	if mn == "jp" && len(ops) == 1 && ops[0].kind == "lit" && ops[0].text == "[hl]" {
		ops[0].text = "hl"
	}
	// optional accumulator operand normalisation
	switch mn {
	case "sub", "and", "xor", "or", "cp":
		if len(ops) == 2 && ops[0].kind == "lit" && ops[0].text == "a" {
			ops = ops[1:]
		}
	case "add", "adc", "sbc":
		if len(ops) == 1 {
			ops = append([]operand{{kind: "lit", text: "a"}}, ops...)
		}
	case "ldi", "ldd":
		// ldi a,[hl] / ldi [hl],a
		suffix := "+"
		if mn == "ldd" {
			suffix = "-"
		}
		mn = "ld"
		for i := range ops {
			if ops[i].kind == "lit" && ops[i].text == "[hl]" {
				ops[i].text = "[hl" + suffix + "]"
			}
		}
	}
	cands := byMnemonic[mn]
	if len(cands) == 0 {
		a.errf(loc, "unknown instruction %q", mn)
		return
	}
	var chosen *Template
	for _, t := range cands {
		if a.matches(loc, t, ops) {
			chosen = t
			break
		}
	}
	if chosen == nil {
		switch mn {
		case "bit", "res", "set", "rst":
			for _, o := range ops {
				if o.kind == "expr" {
					if _, err := evalExpr(o.text, a.pc, a.lookupFn(a.lastGlob)); err != nil {
						a.errf(loc, "%s operand %q: %v (it must be a constant defined before this line)", mn, o.text, err)
						return
					}
				}
			}
		}
		a.errf(loc, "no form of %q accepts operands (%s)", mn, rest)
		return
	}
	a.items = append(a.items, item{kind: kInstr, loc: loc, pc: a.pc, bank: a.bank, glob: a.lastGlob, tmpl: chosen, ops: ops})
	a.advance(chosen.Size)
}

// badOperandSyntax catches common spelling mistakes before template matching.
func badOperandSyntax(p string) string {
	if strings.Count(p, "[") != strings.Count(p, "]") {
		return fmt.Sprintf("unbalanced brackets in %q", p)
	}
	if strings.Count(p, "(") != strings.Count(p, ")") {
		return fmt.Sprintf("unbalanced parentheses in %q", p)
	}
	if len(p) > 2 && p[0] == '(' && p[len(p)-1] == ')' {
		inner := strings.ToLower(strings.ReplaceAll(p[1:len(p)-1], " ", ""))
		if _, ok := litWords["["+inner+"]"]; ok || reserved[inner] {
			return fmt.Sprintf("%q: memory operands are written with square brackets, e.g. [%s]", p, strings.TrimSpace(p[1:len(p)-1]))
		}
	}
	return ""
}

func isNumLit(p string) bool {
	return p != "" && (p[0] == '$' || (p[0] >= '0' && p[0] <= '9'))
}

func (a *assembler) matches(loc Loc, t *Template, ops []operand) bool {
	if len(t.Ops) != len(ops) {
		return false
	}
	for i, p := range t.Ops {
		o := ops[i]
		switch p {
		case phD8, phD16, phJP16, phE8:
			if o.kind != "expr" {
				return false
			}
		case phA8, phA16:
			if o.kind != "mem" {
				return false
			}
		case phSPE8:
			if o.kind != "spoff" {
				return false
			}
		default:
			if isNumLit(p) {
				if o.kind != "expr" {
					return false
				}
				want, _ := evalExpr(p, 0, nil)
				got, err := evalExpr(o.text, a.pc, a.lookupFn(a.lastGlob))
				if err != nil || got != want {
					return false
				}
			} else if o.kind != "lit" || o.text != p {
				return false
			}
		}
	}
	return true
}

// ---- pass 2: emit ------------------------------------------------------

func offsetOf(bank, pc int) int {
	if pc < 0x4000 || bank == 0 {
		return pc // bank 0 is "flat": code may run straight on into bank 1
	}
	return bank*0x4000 + (pc - 0x4000)
}

func (a *assembler) put(loc Loc, bank, pc int, bs ...byte) {
	for i, b := range bs {
		addr := pc + i
		if addr >= 0x8000 {
			a.errf(loc, "code/data runs past the end of the 32 KiB address window at %#04x", addr)
			return
		}
		off := offsetOf(bank, addr)
		if _, dup := a.rom[off]; dup {
			a.errf(loc, "overlapping output at %#04x (bank %d)", addr, bank)
			return
		}
		a.rom[off] = b
		if off+1 > a.maxOff {
			a.maxOff = off + 1
		}
	}
}

func (a *assembler) pass2() {
	for i := range a.items {
		it := &a.items[i]
		lookup := a.lookupFn(it.glob)
		eval := func(s string) (int, bool) {
			v, err := evalExpr(s, it.pc, lookup)
			if err != nil {
				a.errf(it.loc, "%v", err)
				return 0, false
			}
			return v, true
		}
		switch it.kind {
		case kFill:
			bs := make([]byte, it.count)
			for j := range bs {
				bs[j] = byte(it.fill)
			}
			a.put(it.loc, it.bank, it.pc, bs...)
		case kData8:
			for j, e := range it.exprs {
				v, ok := eval(e)
				if !ok {
					continue
				}
				if v < -128 || v > 255 {
					a.errf(it.loc, "value %d does not fit in a byte", v)
					continue
				}
				a.put(it.loc, it.bank, it.pc+j, byte(v))
			}
		case kData16:
			for j, e := range it.exprs {
				v, ok := eval(e)
				if !ok {
					continue
				}
				if v < -32768 || v > 65535 {
					a.errf(it.loc, "value %d does not fit in a word", v)
					continue
				}
				a.put(it.loc, it.bank, it.pc+2*j, byte(v), byte(v>>8))
			}
		case kInstr:
			a.emitInstr(it, eval)
		}
	}
}

func (a *assembler) emitInstr(it *item, eval func(string) (int, bool)) {
	t := it.tmpl
	var bs []byte
	if t.CB {
		bs = append(bs, 0xCB)
	}
	bs = append(bs, t.Opcode)
	if t.HasImp {
		bs = append(bs, t.Implicit)
	}
	for i, p := range t.Ops {
		o := it.ops[i]
		switch p {
		case phD8:
			v, ok := eval(o.text)
			if !ok {
				return
			}
			if v < -128 || v > 255 {
				a.errf(it.loc, "immediate %d does not fit in 8 bits", v)
				return
			}
			bs = append(bs, byte(v))
		case phD16, phJP16, phA16:
			v, ok := eval(o.text)
			if !ok {
				return
			}
			if v < -32768 || v > 65535 {
				a.errf(it.loc, "value %d does not fit in 16 bits", v)
				return
			}
			bs = append(bs, byte(v), byte(v>>8))
		case phA8:
			v, ok := eval(o.text)
			if !ok {
				return
			}
			if v >= 0xFF00 && v <= 0xFFFF {
				v -= 0xFF00
			}
			if v < 0 || v > 255 {
				a.errf(it.loc, "ldh address %#x must be in $FF00-$FFFF (or 0-255)", v)
				return
			}
			bs = append(bs, byte(v))
		case phE8:
			v, ok := eval(o.text)
			if !ok {
				return
			}
			if t.Mnemonic == "jr" {
				rel := v - (it.pc + t.Size)
				if rel < -128 || rel > 127 {
					a.errf(it.loc, "jr target is %d bytes away; limit is -128..127", rel)
					return
				}
				bs = append(bs, byte(int8(rel)))
			} else {
				if v < -128 || v > 127 {
					a.errf(it.loc, "offset %d does not fit in a signed byte", v)
					return
				}
				bs = append(bs, byte(int8(v)))
			}
		case phSPE8:
			v, ok := eval(o.text)
			if !ok {
				return
			}
			if v < -128 || v > 127 {
				a.errf(it.loc, "offset %d does not fit in a signed byte", v)
				return
			}
			bs = append(bs, byte(int8(v)))
		}
	}
	a.put(it.loc, it.bank, it.pc, bs...)
	off := offsetOf(it.bank, it.pc)
	a.src[off] = it.loc
}

// ---- finishing: header + padding ---------------------------------------

var nintendoLogo = []byte{
	0xCE, 0xED, 0x66, 0x66, 0xCC, 0x0D, 0x00, 0x0B, 0x03, 0x73, 0x00, 0x83, 0x00, 0x0C, 0x00, 0x0D,
	0x00, 0x08, 0x11, 0x1F, 0x88, 0x89, 0x00, 0x0E, 0xDC, 0xCC, 0x6E, 0xE6, 0xDD, 0xDD, 0xD9, 0x99,
	0xBB, 0xBB, 0x67, 0x63, 0x6E, 0x0E, 0xEC, 0xCC, 0xDD, 0xDC, 0x99, 0x9F, 0xBB, 0xB9, 0x33, 0x3E,
}

func (a *assembler) finish() *Result {
	if len(a.rom) == 0 {
		a.errf(Loc{"<input>", 1}, "nothing to assemble: the program has no instructions or data")
		return nil
	}
	size := a.maxOff
	if size < 0x150 && !a.opt.NoHeader {
		size = 0x150
	}
	// round up to 32 KiB << n
	code := 0
	total := 0x8000
	for total < size {
		total <<= 1
		code++
	}
	if code > 8 {
		a.errf(Loc{"<output>", 0}, "ROM larger than 8 MiB")
		return nil
	}
	rom := make([]byte, total)
	for off, b := range a.rom {
		rom[off] = b
	}
	if !a.opt.NoHeader {
		fill := func(off int, bs []byte) {
			for i, b := range bs {
				if _, used := a.rom[off+i]; !used {
					rom[off+i] = b
				}
			}
		}
		fill(0x104, nintendoLogo)
		if a.hasTitle {
			t := make([]byte, 16)
			copy(t, a.title)
			fill(0x134, t)
		}
		rom[0x147] = byte(a.cartType)
		rom[0x148] = byte(code)
		if a.hasRAM {
			rom[0x149] = byte(a.ramCode)
		}
		var x byte
		for i := 0x134; i <= 0x14C; i++ {
			x = x - rom[i] - 1
		}
		rom[0x14D] = x
		var sum uint16
		for i, b := range rom {
			if i == 0x14E || i == 0x14F {
				continue
			}
			sum += uint16(b)
		}
		rom[0x14E], rom[0x14F] = byte(sum>>8), byte(sum)
	}
	syms := map[string]int{}
	for k, v := range a.syms {
		syms[k] = v
	}
	return &Result{ROM: rom, Symbols: syms, Source: a.src}
}

// SymFile renders symbols in the common "BB:AAAA name" format, sorted by address.
func (r *Result) SymFile() string {
	type kv struct {
		n string
		v int
	}
	var l []kv
	for n, v := range r.Symbols {
		if v >= 0 && v <= 0xFFFF {
			l = append(l, kv{n, v})
		}
	}
	sort.Slice(l, func(i, j int) bool {
		if l[i].v != l[j].v {
			return l[i].v < l[j].v
		}
		return l[i].n < l[j].n
	})
	var sb strings.Builder
	for _, e := range l {
		fmt.Fprintf(&sb, "00:%04X %s\n", e.v, e.n)
	}
	return sb.String()
}
