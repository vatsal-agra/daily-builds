package ir

import (
	"fmt"
	"strings"
)

// Namer assigns stable readable names to values for printing.
type namer map[*Value]string

func (f *Func) names() namer {
	n := namer{}
	i := 0
	for _, p := range f.Params {
		n[p] = fmt.Sprintf("%%a%d", p.Index)
	}
	for _, b := range f.Blocks {
		for _, v := range b.Phis {
			n[v] = fmt.Sprintf("%%v%d", i)
			i++
		}
		for _, v := range b.Instrs {
			if v.HasResult() {
				n[v] = fmt.Sprintf("%%v%d", i)
				i++
			}
		}
	}
	return n
}

func (n namer) ref(v *Value) string {
	if v == nil {
		return "<nil>"
	}
	if v.Op == OpConst {
		return fmt.Sprintf("%d", v.Const)
	}
	if s, ok := n[v]; ok {
		return s
	}
	return fmt.Sprintf("%%?%d", v.ID)
}

// String renders the module.
func (m *Module) String() string {
	var sb strings.Builder
	for i, f := range m.Funcs {
		if i > 0 {
			sb.WriteString("\n")
		}
		sb.WriteString(f.String())
	}
	return sb.String()
}

// String renders a function in the textual IR syntax accepted by Parse.
func (f *Func) String() string {
	n := f.names()
	var sb strings.Builder
	var ps []string
	for _, p := range f.Params {
		ps = append(ps, n[p])
	}
	fmt.Fprintf(&sb, "func @%s(%s) {\n", f.Name, strings.Join(ps, ", "))
	for _, b := range f.Blocks {
		fmt.Fprintf(&sb, "%s:\n", b.Name)
		for _, v := range b.Phis {
			sb.WriteString("  " + n.instr(v, b) + "\n")
		}
		for _, v := range b.Instrs {
			sb.WriteString("  " + n.instr(v, b) + "\n")
		}
		switch b.Term {
		case TermBr:
			fmt.Fprintf(&sb, "  br %s\n", b.Succs[0].Name)
		case TermCondBr:
			fmt.Fprintf(&sb, "  condbr %s, %s, %s\n", n.ref(b.Ctrl), b.Succs[0].Name, b.Succs[1].Name)
		case TermRet:
			fmt.Fprintf(&sb, "  ret %s\n", n.ref(b.Ctrl))
		default:
			sb.WriteString("  <no terminator>\n")
		}
	}
	sb.WriteString("}\n")
	return sb.String()
}

func (n namer) instr(v *Value, b *Block) string {
	var s string
	switch v.Op {
	case OpAlloca:
		s = fmt.Sprintf("alloca %d", v.Const)
	case OpPhi:
		var parts []string
		for i, a := range v.Args {
			pn := "?"
			if i < len(b.Preds) {
				pn = b.Preds[i].Name
			}
			parts = append(parts, fmt.Sprintf("[%s, %s]", n.ref(a), pn))
		}
		s = "phi " + strings.Join(parts, ", ")
	case OpCall:
		var as []string
		for _, a := range v.Args {
			as = append(as, n.ref(a))
		}
		s = fmt.Sprintf("call @%s(%s)", v.Callee, strings.Join(as, ", "))
	default:
		var as []string
		for _, a := range v.Args {
			as = append(as, n.ref(a))
		}
		s = v.Op.String() + " " + strings.Join(as, ", ")
	}
	if v.HasResult() {
		return fmt.Sprintf("%s = %s", n[v], s)
	}
	return s
}
