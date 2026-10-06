package types

import (
	"fmt"
	"sort"
	"strings"
)

// Printer renders types with stable variable names ('a, 'b, ...). Reuse one printer to print several
// types that must share names (e.g. expected vs found).
type Printer struct {
	names map[*TVar]string
	n     int
	weak  int
	Plain bool               // print unresolved non-generic variables as ordinary 'a (for error messages)
	namer func(*TVar) string // optional: custom name for a variable ("" = use the default)
}

func NewPrinter() *Printer { return &Printer{names: map[*TVar]string{}} }

func letterName(i int) string {
	s := string(rune('a' + i%26))
	if i >= 26 {
		s += fmt.Sprint(i / 26)
	}
	return s
}

func (p *Printer) nameOf(v *TVar) string {
	if s, ok := p.names[v]; ok {
		return s
	}
	if p.namer != nil {
		if s := p.namer(v); s != "" {
			p.names[v] = s
			return s
		}
	}
	var s string
	if v.Level == Generic || p.Plain {
		s = "'" + letterName(p.n)
		p.n++
	} else {
		s = "'_" + letterName(p.weak)
		p.weak++
	}
	p.names[v] = s
	return s
}

// String renders t.
func (p *Printer) String(t Type) string {
	var b strings.Builder
	p.write(&b, t, 0)
	return b.String()
}

// precedence: 0 = top / arrow result, 1 = arrow parameter, 2 = tuple element, 3 = constructor argument
func (p *Printer) write(b *strings.Builder, t Type, prec int) {
	t = Prune(t)
	switch x := t.(type) {
	case *TVar:
		b.WriteString(p.nameOf(x))
	case *TCon:
		switch {
		case x.Head == HRecord:
			p.writeRecord(b, x.Args[0])
		case x.Head.Row:
			b.WriteString("<row>") // rows are only printed inside records
		case x.Head == HArrow:
			if prec > 0 {
				b.WriteByte('(')
			}
			p.write(b, x.Args[0], 1)
			b.WriteString(" -> ")
			p.write(b, x.Args[1], 0)
			if prec > 0 {
				b.WriteByte(')')
			}
		case x.Head == HTuple:
			if prec >= 2 {
				b.WriteByte('(')
			}
			for i, a := range x.Args {
				if i > 0 {
					b.WriteString(" * ")
				}
				p.write(b, a, 2)
			}
			if prec >= 2 {
				b.WriteByte(')')
			}
		case len(x.Args) == 0:
			b.WriteString(x.Head.Name)
		case len(x.Args) == 1:
			p.write(b, x.Args[0], 3)
			b.WriteString(" " + x.Head.Name)
		default:
			b.WriteByte('(')
			for i, a := range x.Args {
				if i > 0 {
					b.WriteString(", ")
				}
				p.write(b, a, 0)
			}
			b.WriteString(") " + x.Head.Name)
		}
	}
}

// TypeString is a convenience for printing a single type.
func TypeString(t Type) string { return NewPrinter().String(t) }

// SchemeString prints a scheme.
func SchemeString(s *Scheme) string { return NewPrinter().String(s.Type) }

func (p *Printer) writeRecord(b *strings.Builder, row Type) {
	type field struct {
		label string
		t     Type
	}
	var fs []field
	cur := Prune(row)
	open := false
	var tail *TVar
	for {
		c, ok := cur.(*TCon)
		if !ok {
			open = true
			tail, _ = cur.(*TVar)
			break
		}
		if c.Head == HRowEmpty {
			break
		}
		fs = append(fs, field{c.Head.Label, c.Args[0]})
		cur = Prune(c.Args[1])
	}
	sort.Slice(fs, func(i, j int) bool { return fs[i].label < fs[j].label })
	b.WriteString("{")
	for i, f := range fs {
		if i > 0 {
			b.WriteString("; ")
		} else {
			b.WriteString(" ")
		}
		b.WriteString(f.label + " : ")
		p.write(b, f.t, 0)
	}
	if open {
		if len(fs) > 0 {
			b.WriteString("; ")
		} else {
			b.WriteString(" ")
		}
		b.WriteString("..")
		_ = tail
	}
	b.WriteString(" }")
}
