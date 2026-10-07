package model

import (
	"fmt"
	"math/big"
	"strings"
)

func termStr(first bool, c string, name string) string {
	neg := strings.HasPrefix(c, "-")
	mag := strings.TrimPrefix(c, "-")
	if mag == "1" {
		mag = ""
	} else {
		mag += " "
	}
	switch {
	case first && neg:
		return "- " + mag + name
	case first:
		return mag + name
	case neg:
		return " - " + mag + name
	}
	return " + " + mag + name
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
	first := true
	for _, v := range m.Vars {
		if v.Obj.Sign() == 0 {
			continue
		}
		b.WriteString(termStr(first, RatStr(v.Obj), v.Name))
		first = false
	}
	if m.ObjConst.Sign() != 0 {
		if first {
			b.WriteString(RatStr(m.ObjConst))
		} else if m.ObjConst.Sign() < 0 {
			b.WriteString(" - " + RatStr(new(big.Rat).Neg(m.ObjConst)))
		} else {
			b.WriteString(" + " + RatStr(m.ObjConst))
		}
		first = false
	}
	if first {
		b.WriteString("0 " + zeroVar(m))
	}
	b.WriteString("\nSubject To\n")
	for _, r := range m.Rows {
		b.WriteString(" " + r.Name + ": ")
		var lhs strings.Builder
		for k, e := range SortedEntries(r.Entries) {
			lhs.WriteString(termStr(k == 0, RatStr(e.V), m.Vars[e.J].Name))
		}
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

func zeroVar(m *Model) string {
	if len(m.Vars) > 0 {
		return m.Vars[0].Name
	}
	return "x"
}
