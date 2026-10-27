// Package parse reads and writes Bayou's .bn language and the BIF interchange
// format, and reads CSV datasets.
//
// .bn syntax:
//
//	network "Asia"
//	var Smoker { yes, no }
//	cpt Smoker = 0.5, 0.5
//	var Cancer { yes, no }
//	cpt Cancer | Smoker {
//	    yes: 0.10, 0.90
//	    *:   0.01, 0.99        # '*' matches any parent state; explicit rows win
//	}
package parse

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"bayou/internal/bn"
)

// ParseBN parses the .bn language. file is used in error messages.
func ParseBN(file, src string) (*bn.Network, error) {
	toks, err := lex(file, src, "{},:|=", true, true)
	if err != nil {
		return nil, err
	}
	ps := &parser{file: file, toks: toks}
	net := bn.New("")
	type pending struct {
		v      int
		parent []token
		tok    token
		rows   []rowSpec
		flat   []float64
		hasCPT bool
	}
	cpts := map[int]*pending{}
	named := false
	for {
		ps.skipNL()
		t := ps.peek()
		if t.k == tEOF {
			break
		}
		if t.k != tWord {
			return nil, ps.errAt(t, "expected 'network', 'var' or 'cpt', found %s", describe(t))
		}
		ps.next()
		switch t.s {
		case "network":
			if named {
				return nil, ps.errAt(t, "duplicate 'network' declaration")
			}
			nm, err := ps.name("network name")
			if err != nil {
				return nil, err
			}
			net.Name, named = nm.s, true
		case "var":
			nm, err := ps.name("variable name")
			if err != nil {
				return nil, err
			}
			if err := ps.expect("{"); err != nil {
				return nil, err
			}
			var states []string
			for {
				ps.skipNL()
				st, err := ps.name("state name")
				if err != nil {
					return nil, err
				}
				states = append(states, st.s)
				ps.skipNL()
				if ps.accept(",") {
					continue
				}
				break
			}
			ps.skipNL()
			if err := ps.expect("}"); err != nil {
				return nil, err
			}
			if _, err := net.AddVar(nm.s, states); err != nil {
				return nil, ps.errAt(nm, "%v", err)
			}
		case "cpt":
			nm, err := ps.name("variable name")
			if err != nil {
				return nil, err
			}
			v, ok := net.ID(nm.s)
			if !ok {
				return nil, ps.errAt(nm, "cpt for undeclared variable %q (declare it with 'var' first)", nm.s)
			}
			if cpts[v] != nil {
				return nil, ps.errAt(nm, "variable %q already has a cpt", nm.s)
			}
			pd := &pending{v: v, tok: nm, hasCPT: true}
			cpts[v] = pd
			if ps.accept("|") {
				for {
					pn, err := ps.name("parent name")
					if err != nil {
						return nil, err
					}
					pd.parent = append(pd.parent, pn)
					if !ps.accept(",") {
						break
					}
				}
				if err := ps.expect("{"); err != nil {
					return nil, err
				}
				for {
					ps.skipNL()
					if ps.accept("}") {
						break
					}
					row, err := ps.parseRow(len(pd.parent))
					if err != nil {
						return nil, err
					}
					pd.rows = append(pd.rows, row)
				}
			} else {
				if err := ps.expect("="); err != nil {
					return nil, err
				}
				pd.flat, err = ps.parseNumbers()
				if err != nil {
					return nil, err
				}
			}
		default:
			return nil, ps.errAt(t, "unknown declaration %q (expected 'network', 'var' or 'cpt')", t.s)
		}
	}
	// Resolve CPTs after all variables are known so cpt order is free.
	for v := range net.Vars {
		pd := cpts[v]
		if pd == nil {
			return nil, &Error{file, 1, 1, fmt.Sprintf("variable %q has no cpt", net.Vars[v].Name)}
		}
		var parents []int
		for _, pt := range pd.parent {
			pid, ok := net.ID(pt.s)
			if !ok {
				return nil, &Error{file, pt.line, pt.col, fmt.Sprintf("unknown parent %q of %q", pt.s, net.Vars[v].Name)}
			}
			parents = append(parents, pid)
		}
		net.SetParents(v, parents)
	}
	for v := range net.Vars {
		pd := cpts[v]
		if len(pd.parent) == 0 {
			c := net.Card(v)
			if len(pd.flat) != c {
				return nil, &Error{file, pd.tok.line, pd.tok.col, fmt.Sprintf("cpt %s: expected %d probabilities, got %d", net.Vars[v].Name, c, len(pd.flat))}
			}
			copy(net.Vars[v].CPT, pd.flat)
			continue
		}
		if err := fillRows(net, v, pd.rows, file); err != nil {
			return nil, err
		}
	}
	if errs := net.Validate(); len(errs) > 0 {
		return nil, &Error{file, 1, 1, errs[0].Error()}
	}
	return net, nil
}

type rowSpec struct {
	tok    token
	states []token // parent state labels or "*"
	probs  []float64
}

func (ps *parser) parseRow(nparents int) (rowSpec, error) {
	r := rowSpec{tok: ps.peek()}
	for {
		t, err := ps.name("parent state or '*'")
		if err != nil {
			return r, err
		}
		r.states = append(r.states, t)
		if !ps.accept(",") {
			break
		}
	}
	if len(r.states) != nparents {
		return r, ps.errAt(r.tok, "row names %d parent states but the cpt has %d parents", len(r.states), nparents)
	}
	if err := ps.expect(":"); err != nil {
		return r, err
	}
	var err error
	r.probs, err = ps.parseNumbers()
	return r, err
}

// parseNumbers reads comma separated numbers up to end of line / '}'.
func (ps *parser) parseNumbers() ([]float64, error) {
	var out []float64
	for {
		t := ps.next()
		if t.k != tWord {
			return nil, ps.errAt(t, "expected a probability, found %s", describe(t))
		}
		x, err := parseProb(t.s)
		if err != nil {
			return nil, ps.errAt(t, "%v", err)
		}
		out = append(out, x)
		if ps.accept(",") {
			ps.skipNL() // a trailing comma continues the list on the next line
			continue
		}
		break
	}
	nt := ps.peek()
	if nt.k != tNL && nt.k != tEOF && !(nt.k == tPunct && nt.s == "}") {
		return nil, ps.errAt(nt, "unexpected %s after probabilities", describe(nt))
	}
	return out, nil
}

func parseProb(s string) (float64, error) {
	if i := strings.IndexByte(s, '/'); i > 0 {
		a, e1 := strconv.ParseFloat(s[:i], 64)
		b, e2 := strconv.ParseFloat(s[i+1:], 64)
		if e1 != nil || e2 != nil || b == 0 {
			return 0, fmt.Errorf("bad fraction %q", s)
		}
		return a / b, nil
	}
	x, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsNaN(x) || math.IsInf(x, 0) {
		return 0, fmt.Errorf("%q is not a number", s)
	}
	return x, nil
}

func fillRows(net *bn.Network, v int, rows []rowSpec, file string) error {
	x := net.Vars[v]
	c := net.Card(v)
	nrows := net.ParentConfigs(v)
	filled := make([]bool, nrows)
	explicitSeen := make([]bool, nrows)
	var dupRow *rowSpec
	apply := func(wild bool) error {
		for _, r := range rows {
			isWild := false
			for _, s := range r.states {
				if s.s == "*" {
					isWild = true
				}
			}
			if isWild != wild {
				continue
			}
			if len(r.probs) != c {
				return &Error{file, r.tok.line, r.tok.col, fmt.Sprintf("cpt %s: row has %d probabilities, variable has %d states", x.Name, len(r.probs), c)}
			}
			// Enumerate matching parent configurations.
			cand := make([][]int, len(x.Parents))
			for i, p := range x.Parents {
				if r.states[i].s == "*" {
					for s := 0; s < net.Card(p); s++ {
						cand[i] = append(cand[i], s)
					}
					continue
				}
				sid, ok := net.StateID(p, r.states[i].s)
				if !ok {
					return &Error{file, r.states[i].line, r.states[i].col, fmt.Sprintf("cpt %s: parent %s has no state %q (states: %s)",
						x.Name, net.Vars[p].Name, r.states[i].s, strings.Join(net.Vars[p].States, ", "))}
				}
				cand[i] = []int{sid}
			}
			var rec func(i, idx int)
			rec = func(i, idx int) {
				if i == len(cand) {
					copy(x.CPT[idx*c:(idx+1)*c], r.probs)
					if !wild && filled[idx] && explicitSeen[idx] {
						dupRow = &r
					}
					if !wild {
						explicitSeen[idx] = true
					}
					filled[idx] = true
					return
				}
				for _, s := range cand[i] {
					rec(i+1, idx*net.Card(x.Parents[i])+s)
				}
			}
			rec(0, 0)
		}
		return nil
	}
	if err := apply(true); err != nil {
		return err
	}
	if err := apply(false); err != nil {
		return err
	}
	if dupRow != nil {
		return &Error{file, dupRow.tok.line, dupRow.tok.col, fmt.Sprintf("cpt %s: parent configuration listed twice", x.Name)}
	}
	for i, ok := range filled {
		if !ok {
			return &Error{file, 1, 1, fmt.Sprintf("cpt %s: no row for %s (add it or a '*' row)", x.Name, net.RowLabel(v, i))}
		}
	}
	return nil
}

func quoteIfNeeded(s string) string {
	if s == "" || strings.ContainsAny(s, " \t\n{},:|=#\"") || strings.HasPrefix(s, "//") || strings.Contains(s, "/*") || s == "*" {
		return strconv.Quote(s)
	}
	return s
}

func fmtProb(x float64) string { return strconv.FormatFloat(x, 'g', -1, 64) }

// FormatBN prints a network in .bn syntax; ParseBN(FormatBN(n)) reproduces n exactly.
func FormatBN(n *bn.Network) string {
	var b strings.Builder
	fmt.Fprintf(&b, "network %s\n\n", quoteIfNeeded(n.Name))
	for _, v := range n.Vars {
		qs := make([]string, len(v.States))
		for i, s := range v.States {
			qs[i] = quoteIfNeeded(s)
		}
		fmt.Fprintf(&b, "var %s { %s }\n", quoteIfNeeded(v.Name), strings.Join(qs, ", "))
	}
	b.WriteString("\n")
	for id, v := range n.Vars {
		c := n.Card(id)
		probs := func(r int) string {
			ps := make([]string, c)
			for s := 0; s < c; s++ {
				ps[s] = fmtProb(v.CPT[r*c+s])
			}
			return strings.Join(ps, ", ")
		}
		if len(v.Parents) == 0 {
			fmt.Fprintf(&b, "cpt %s = %s\n\n", quoteIfNeeded(v.Name), probs(0))
			continue
		}
		pn := make([]string, len(v.Parents))
		for i, p := range v.Parents {
			pn[i] = quoteIfNeeded(n.Vars[p].Name)
		}
		fmt.Fprintf(&b, "cpt %s | %s {\n", quoteIfNeeded(v.Name), strings.Join(pn, ", "))
		for r := 0; r < n.ParentConfigs(id); r++ {
			cfg := n.DecodeRow(id, r)
			ls := make([]string, len(cfg))
			for i, s := range cfg {
				ls[i] = quoteIfNeeded(n.Vars[v.Parents[i]].States[s])
			}
			fmt.Fprintf(&b, "    %s: %s\n", strings.Join(ls, ", "), probs(r))
		}
		b.WriteString("}\n\n")
	}
	return strings.TrimRight(b.String(), "\n") + "\n"
}
