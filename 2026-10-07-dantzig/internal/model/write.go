package model

import (
	"fmt"
	"strings"
)

type term struct {
	neg  bool
	text string // magnitude with name, e.g. "3 x" or "x"
}

func mkTerm(c, name string) term {
	neg := strings.HasPrefix(c, "-")
	mag := strings.TrimPrefix(c, "-")
	if mag == "1" {
		return term{neg, name}
	}
	return term{neg, mag + " " + name}
}

// writeExpr renders terms as "a x + b y - c z", wrapping long lines with the
// operator at the end of the line (the parser treats that as a continuation).
func writeExpr(b *strings.Builder, terms []term, indent string) {
	col := 0
	for k, t := range terms {
		var piece string
		switch {
		case k == 0 && t.neg:
			piece = "- " + t.text
		case k == 0:
			piece = t.text
		case t.neg:
			piece = "- " + t.text
		default:
			piece = "+ " + t.text
		}
		if k > 0 {
			if col+len(piece) > 96 {
				// move the operator to the end of the current line
				op := piece[:1]
				b.WriteString(" " + op + "\n" + indent)
				piece = piece[2:]
				col = len(indent)
			} else {
				b.WriteString(" ")
				col++
			}
		}
		b.WriteString(piece)
		col += len(piece)
	}
}

// Format renders the model in the canonical LP text form (parse(Format(m)) == m).
func Format(m *Model) string {
	var b strings.Builder
	if m.Maximize {
		b.WriteString("Maximize\n")
	} else {
		b.WriteString("Minimize\n")
	}
	obj := "obj"
	if m.ObjName != "" {
		obj = m.ObjName
	}
	b.WriteString(" " + obj + ": ")
	var ot []term
	listed := listInObjective(m)
	for j, v := range m.Vars {
		if listed[j] {
			ot = append(ot, mkTerm(RatStr(v.Obj), v.Name))
		}
	}
	if m.ObjConst.Sign() != 0 {
		c := RatStr(m.ObjConst)
		ot = append(ot, term{strings.HasPrefix(c, "-"), strings.TrimPrefix(c, "-")})
	}
	writeExpr(&b, ot, "    ") // empty objective = pure feasibility problem
	b.WriteString("\nSubject To\n")
	for _, r := range m.Rows {
		b.WriteString(" " + r.Name + ": ")
		var rt []term
		for _, e := range SortedEntries(r.Entries) {
			rt = append(rt, mkTerm(RatStr(e.V), m.Vars[e.J].Name))
		}
		var lhs strings.Builder
		writeExpr(&lhs, rt, "    ")
		switch {
		case r.Lo != nil && r.Hi != nil && r.Lo.Cmp(r.Hi) == 0:
			fmt.Fprintf(&b, "%s = %s\n", lhs.String(), RatStr(r.Lo))
		case r.Lo != nil && r.Hi != nil:
			fmt.Fprintf(&b, "%s <= %s <= %s\n", RatStr(r.Lo), lhs.String(), RatStr(r.Hi))
		case r.Hi != nil:
			fmt.Fprintf(&b, "%s <= %s\n", lhs.String(), RatStr(r.Hi))
		case r.Lo != nil:
			fmt.Fprintf(&b, "%s >= %s\n", lhs.String(), RatStr(r.Lo))
		default:
			fmt.Fprintf(&b, "%s >= -inf\n", lhs.String())
		}
	}
	var bounds []string
	for _, v := range m.Vars {
		switch {
		case v.Lo == nil && v.Hi == nil:
			bounds = append(bounds, v.Name+" free")
		case v.Lo != nil && v.Hi != nil && v.Lo.Cmp(v.Hi) == 0:
			bounds = append(bounds, fmt.Sprintf("%s = %s", v.Name, RatStr(v.Lo)))
		case v.Lo == nil:
			bounds = append(bounds, fmt.Sprintf("-inf <= %s <= %s", v.Name, RatStr(v.Hi)))
		case v.Hi == nil:
			if v.Lo.Sign() != 0 {
				bounds = append(bounds, fmt.Sprintf("%s >= %s", v.Name, RatStr(v.Lo)))
			}
		default:
			bounds = append(bounds, fmt.Sprintf("%s <= %s <= %s", RatStr(v.Lo), v.Name, RatStr(v.Hi)))
		}
	}
	if len(bounds) > 0 {
		b.WriteString("Bounds\n")
		for _, s := range bounds {
			b.WriteString(" " + s + "\n")
		}
	}
	var ints []string
	for _, v := range m.Vars {
		if v.Int {
			ints = append(ints, v.Name)
		}
	}
	if len(ints) > 0 {
		b.WriteString("Integer\n")
		for i := 0; i < len(ints); i += 8 {
			b.WriteString(" " + strings.Join(ints[i:min(i+8, len(ints))], " ") + "\n")
		}
	}
	b.WriteString("End\n")
	return b.String()
}

// listInObjective decides which variables the objective line must mention so
// that re-parsing reproduces the variable order: all costed variables, plus
// zero-cost ones that would otherwise first appear out of order. When a cheap
// choice does not reproduce the order, every variable is listed.
func listInObjective(m *Model) []bool {
	n := len(m.Vars)
	last := -1
	for j, v := range m.Vars {
		if v.Obj.Sign() != 0 {
			last = j
		}
	}
	pick := make([]bool, n)
	for j := range pick {
		pick[j] = j <= last
	}
	// simulate the parser's variable creation order
	var order []int
	seen := make([]bool, n)
	for j := 0; j < n; j++ {
		if pick[j] {
			order = append(order, j)
			seen[j] = true
		}
	}
	for _, r := range m.Rows {
		for _, e := range SortedEntries(r.Entries) {
			if !seen[e.J] {
				seen[e.J] = true
				order = append(order, e.J)
			}
		}
	}
	ok := len(order) == n
	for i, j := range order {
		if i != j {
			ok = false
		}
	}
	if !ok {
		for j := range pick {
			pick[j] = true
		}
	}
	return pick
}
