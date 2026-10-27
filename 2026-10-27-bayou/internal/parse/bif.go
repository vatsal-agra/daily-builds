package parse

import (
	"fmt"
	"io"
	"strconv"
	"strings"

	"bayou/internal/bn"
)

// ParseBIF reads the Bayesian Interchange Format (the dialect used by bnlearn,
// pgmpy and Hugin exports). A `table` entry for a variable with parents is read
// in Bayou's CPT layout (parents slowest, child fastest); per-parent-state
// entries `(a, b) p1, p2;` and `default` are fully supported.
func ParseBIF(file, src string) (*bn.Network, error) {
	toks, err := lex(file, src, "{}[](),;|", false, true)
	if err != nil {
		return nil, err
	}
	ps := &parser{file: file, toks: toks}
	net := bn.New("")
	type probDecl struct {
		tok     token
		child   token
		parents []token
		body    []token
	}
	var probs []probDecl
	for ps.peek().k != tEOF {
		t := ps.next()
		if t.k != tWord {
			return nil, ps.errAt(t, "unexpected %s", describe(t))
		}
		switch t.s {
		case "network":
			nm, err := ps.name("network name")
			if err != nil {
				return nil, err
			}
			net.Name = nm.s
			if _, err := ps.skipBlock(); err != nil {
				return nil, err
			}
		case "variable":
			nm, err := ps.name("variable name")
			if err != nil {
				return nil, err
			}
			body, err := ps.skipBlock()
			if err != nil {
				return nil, err
			}
			states, err := bifStates(body)
			if err != nil {
				return nil, &Error{file, nm.line, nm.col, fmt.Sprintf("variable %s: %v", nm.s, err)}
			}
			if _, err := net.AddVar(nm.s, states); err != nil {
				return nil, ps.errAt(nm, "%v", err)
			}
		case "probability":
			if err := ps.expect("("); err != nil {
				return nil, err
			}
			child, err := ps.name("variable name")
			if err != nil {
				return nil, err
			}
			d := probDecl{tok: t, child: child}
			if ps.accept("|") {
				for {
					p, err := ps.name("parent name")
					if err != nil {
						return nil, err
					}
					d.parents = append(d.parents, p)
					if !ps.accept(",") {
						break
					}
				}
			}
			if err := ps.expect(")"); err != nil {
				return nil, err
			}
			d.body, err = ps.skipBlock()
			if err != nil {
				return nil, err
			}
			probs = append(probs, d)
		default:
			return nil, ps.errAt(t, "unknown BIF block %q", t.s)
		}
	}
	done := map[int]bool{}
	for _, d := range probs {
		v, ok := net.ID(d.child.s)
		if !ok {
			return nil, &Error{file, d.child.line, d.child.col, fmt.Sprintf("probability for undeclared variable %q", d.child.s)}
		}
		if done[v] {
			return nil, &Error{file, d.child.line, d.child.col, fmt.Sprintf("variable %q has two probability blocks", d.child.s)}
		}
		done[v] = true
		var parents []int
		for _, pt := range d.parents {
			pid, ok := net.ID(pt.s)
			if !ok {
				return nil, &Error{file, pt.line, pt.col, fmt.Sprintf("unknown parent %q", pt.s)}
			}
			parents = append(parents, pid)
		}
		net.SetParents(v, parents)
	}
	for _, d := range probs {
		v := net.MustID(d.child.s)
		if err := fillBIF(net, v, d.body, file); err != nil {
			return nil, err
		}
	}
	for v := range net.Vars {
		if !done[v] {
			return nil, &Error{file, 1, 1, fmt.Sprintf("variable %q has no probability block", net.Vars[v].Name)}
		}
	}
	if errs := net.Validate(); len(errs) > 0 {
		return nil, &Error{file, 1, 1, errs[0].Error()}
	}
	net.Renormalize()
	return net, nil
}

// skipBlock consumes `{ ... }` (nesting aware) and returns the inner tokens.
func (ps *parser) skipBlock() ([]token, error) {
	if err := ps.expect("{"); err != nil {
		return nil, err
	}
	depth := 1
	var body []token
	for {
		t := ps.next()
		if t.k == tEOF {
			return nil, ps.errAt(t, "unterminated '{' block")
		}
		if t.k == tPunct && t.s == "{" {
			depth++
		}
		if t.k == tPunct && t.s == "}" {
			if depth--; depth == 0 {
				return body, nil
			}
		}
		body = append(body, t)
	}
}

func bifStates(body []token) ([]string, error) {
	// type discrete [ N ] { a, b, c };
	for i := 0; i < len(body); i++ {
		if body[i].k == tWord && body[i].s == "discrete" {
			j := i + 1
			if j < len(body) && body[j].s == "[" {
				for j < len(body) && body[j].s != "]" {
					j++
				}
				j++
			}
			if j >= len(body) || body[j].s != "{" {
				return nil, fmt.Errorf("expected '{' state list after 'discrete'")
			}
			var st []string
			for j++; j < len(body) && body[j].s != "}"; j++ {
				if body[j].k == tPunct && body[j].s == "," {
					continue
				}
				st = append(st, body[j].s)
			}
			return st, nil
		}
	}
	return nil, fmt.Errorf("no 'type discrete' declaration")
}

func fillBIF(net *bn.Network, v int, body []token, file string) error {
	c := net.Card(v)
	x := net.Vars[v]
	nrows := net.ParentConfigs(v)
	nums := func(i int) ([]float64, int, error) {
		var out []float64
		for ; i < len(body); i++ {
			t := body[i]
			if t.k == tPunct && t.s == ";" {
				return out, i + 1, nil
			}
			if t.k == tPunct && t.s == "," {
				continue
			}
			f, err := parseProb(t.s)
			if err != nil {
				return nil, i, &Error{file, t.line, t.col, err.Error()}
			}
			out = append(out, f)
		}
		return nil, i, &Error{file, 1, 1, "missing ';' in probability block"}
	}
	filled := make([]bool, nrows)
	var def []float64
	for i := 0; i < len(body); {
		t := body[i]
		switch {
		case t.k == tWord && t.s == "table":
			vals, ni, err := nums(i + 1)
			if err != nil {
				return err
			}
			if len(vals) != nrows*c {
				return &Error{file, t.line, t.col, fmt.Sprintf("%s: table has %d values, want %d", x.Name, len(vals), nrows*c)}
			}
			copy(x.CPT, vals)
			for r := range filled {
				filled[r] = true
			}
			i = ni
		case t.k == tWord && t.s == "default":
			vals, ni, err := nums(i + 1)
			if err != nil {
				return err
			}
			if len(vals) != c {
				return &Error{file, t.line, t.col, fmt.Sprintf("%s: default row has %d values, want %d", x.Name, len(vals), c)}
			}
			def = vals
			i = ni
		case t.k == tPunct && t.s == "(":
			j := i + 1
			var labels []token
			for ; j < len(body) && body[j].s != ")"; j++ {
				if body[j].k == tPunct && body[j].s == "," {
					continue
				}
				labels = append(labels, body[j])
			}
			if len(labels) != len(x.Parents) {
				return &Error{file, t.line, t.col, fmt.Sprintf("%s: entry names %d parent states, expected %d", x.Name, len(labels), len(x.Parents))}
			}
			idx := 0
			for k, lb := range labels {
				sid, ok := net.StateID(x.Parents[k], lb.s)
				if !ok {
					return &Error{file, lb.line, lb.col, fmt.Sprintf("%s: parent %s has no state %q", x.Name, net.Vars[x.Parents[k]].Name, lb.s)}
				}
				idx = idx*net.Card(x.Parents[k]) + sid
			}
			vals, ni, err := nums(j + 1)
			if err != nil {
				return err
			}
			if len(vals) != c {
				return &Error{file, t.line, t.col, fmt.Sprintf("%s: entry has %d values, want %d", x.Name, len(vals), c)}
			}
			copy(x.CPT[idx*c:(idx+1)*c], vals)
			filled[idx] = true
			i = ni
		case t.k == tWord && t.s == "property":
			for i < len(body) && !(body[i].k == tPunct && body[i].s == ";") {
				i++
			}
			i++
		default:
			return &Error{file, t.line, t.col, fmt.Sprintf("%s: unexpected %s in probability block", x.Name, describe(t))}
		}
	}
	for r, ok := range filled {
		if !ok && def != nil {
			copy(x.CPT[r*c:(r+1)*c], def)
			continue
		}
		if !ok {
			return &Error{file, 1, 1, fmt.Sprintf("%s: no entry for %s", x.Name, net.RowLabel(v, r))}
		}
	}
	return nil
}

// WriteBIF writes the network in BIF.
func WriteBIF(w io.Writer, n *bn.Network) error {
	var b strings.Builder
	fmt.Fprintf(&b, "network %s {\n}\n", bifName(n.Name))
	for _, v := range n.Vars {
		fmt.Fprintf(&b, "variable %s {\n  type discrete [ %d ] { %s };\n}\n", bifName(v.Name), len(v.States), strings.Join(mapStr(v.States, bifName), ", "))
	}
	for id, v := range n.Vars {
		c := n.Card(id)
		if len(v.Parents) == 0 {
			fmt.Fprintf(&b, "probability ( %s ) {\n  table %s;\n}\n", bifName(v.Name), joinProbs(v.CPT[:c]))
			continue
		}
		fmt.Fprintf(&b, "probability ( %s | %s ) {\n", bifName(v.Name), strings.Join(mapIDs(n, v.Parents), ", "))
		for r := 0; r < n.ParentConfigs(id); r++ {
			cfg := n.DecodeRow(id, r)
			ls := make([]string, len(cfg))
			for i, s := range cfg {
				ls[i] = bifName(n.Vars[v.Parents[i]].States[s])
			}
			fmt.Fprintf(&b, "  (%s) %s;\n", strings.Join(ls, ", "), joinProbs(v.CPT[r*c:(r+1)*c]))
		}
		b.WriteString("}\n")
	}
	_, err := io.WriteString(w, b.String())
	return err
}

func joinProbs(p []float64) string {
	s := make([]string, len(p))
	for i, x := range p {
		s[i] = strconv.FormatFloat(x, 'g', -1, 64)
	}
	return strings.Join(s, ", ")
}
func mapStr(a []string, f func(string) string) []string {
	o := make([]string, len(a))
	for i, s := range a {
		o[i] = f(s)
	}
	return o
}
func mapIDs(n *bn.Network, ids []int) []string {
	o := make([]string, len(ids))
	for i, v := range ids {
		o[i] = bifName(n.Vars[v].Name)
	}
	return o
}

// bifName makes a name safe for BIF (which has no quoting): unsafe runes become '_'.
func bifName(s string) string {
	if s == "" {
		return "_"
	}
	var b strings.Builder
	for _, r := range s {
		if strings.ContainsRune("{}[](),;|\"# \t\n", r) {
			b.WriteByte('_')
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}
