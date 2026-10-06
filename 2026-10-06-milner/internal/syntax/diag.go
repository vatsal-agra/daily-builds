// Package syntax holds the lexer, AST, parser and diagnostic rendering for Milner ML.
package syntax

import (
	"fmt"
	"strings"
)

// Pos is a position in the source: byte offset plus 1-based line/column (column counted in runes).
type Pos struct {
	Off, Line, Col int
}

// Span is a half-open source range [Start, End).
type Span struct {
	Start, End Pos
}

// Join returns the smallest span covering a and b.
func Join(a, b Span) Span {
	if a.Start.Off == 0 && a.End.Off == 0 && a.Start.Line == 0 {
		return b
	}
	if b.Start.Line == 0 {
		return a
	}
	s, e := a.Start, a.End
	if b.Start.Off < s.Off {
		s = b.Start
	}
	if b.End.Off > e.Off {
		e = b.End
	}
	return Span{s, e}
}

// Diag is a user-facing diagnostic anchored to a span.
type Diag struct {
	Kind  string // "syntax", "type", "pattern", "runtime", ...
	Warn  bool
	Span  Span
	Msg   string
	Label string   // short text printed under the carets
	Notes []string // extra "= note:" lines
}

func (d *Diag) Error() string {
	return fmt.Sprintf("%d:%d: %s error: %s", d.Span.Start.Line, d.Span.Start.Col, d.Kind, d.Msg)
}

// Errorf builds a Diag error.
func Errorf(kind string, sp Span, format string, a ...any) *Diag {
	return &Diag{Kind: kind, Span: sp, Msg: fmt.Sprintf(format, a...)}
}

// Render prints d with a source excerpt and carets. file may be empty.
func (d *Diag) Render(src, file string) string {
	var b strings.Builder
	sev := "error"
	if d.Warn {
		sev = "warning"
	}
	fmt.Fprintf(&b, "%s[%s]: %s\n", sev, d.Kind, d.Msg)
	if d.Span.Start.Line > 0 {
		if file == "" {
			file = "<input>"
		}
		lines := strings.Split(src, "\n")
		endLine, endCol := d.Span.End.Line, d.Span.End.Col
		if endLine > d.Span.Start.Line && endCol == 1 {
			// the span ends at the very start of a line: it really ends at the end of the previous one
			endLine--
			endCol = len([]rune(strings.TrimRight(lines[endLine-1], "\r"))) + 1
		}
		l1, l2 := d.Span.Start.Line, endLine
		if l2 < l1 {
			l2 = l1
		}
		if l1 > len(lines) {
			l1 = len(lines)
		}
		if l2 > len(lines) {
			l2 = len(lines)
		}
		w := len(fmt.Sprint(l2))
		fmt.Fprintf(&b, "%*s--> %s:%d:%d\n", w, "", file, d.Span.Start.Line, d.Span.Start.Col)
		fmt.Fprintf(&b, "%*s |\n", w, "")
		show := l2 - l1
		if show > 4 { // very long spans: show only the first line
			l2 = l1
			show = 0
		}
		for ln := l1; ln <= l2; ln++ {
			text := strings.TrimRight(lines[ln-1], "\r")
			text = strings.ReplaceAll(text, "\t", " ")
			fmt.Fprintf(&b, "%*d | %s\n", w, ln, text)
			rs := []rune(text)
			from, to := 1, len(rs)+1
			if ln == d.Span.Start.Line {
				from = d.Span.Start.Col
			} else {
				for from <= len(rs) && rs[from-1] == ' ' {
					from++
				}
			}
			if ln == endLine && endCol > 0 {
				to = endCol
			}
			if to <= from {
				to = from + 1
			}
			if from < 1 {
				from = 1
			}
			fmt.Fprintf(&b, "%*s | %s%s", w, "", strings.Repeat(" ", from-1), strings.Repeat("^", to-from))
			if ln == l2 && d.Label != "" {
				b.WriteString(" " + d.Label)
			}
			b.WriteString("\n")
		}
		_ = show
	}
	for _, n := range d.Notes {
		fmt.Fprintf(&b, "  = %s\n", n)
	}
	return b.String()
}
