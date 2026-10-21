package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func (m *Machine) errorBallText(ball Term) string { return messageText(ball) }

func (m *Machine) locString(rd *Reader) string {
	if m.loadFile == "" {
		return ""
	}
	return fmt.Sprintf("%s:%d", m.loadFile, rd.Line)
}

func (m *Machine) consultSpec(spec Term) error {
	spec = deref(spec)
	if items, tail := listToSlice(spec); tail == Term(atNil) && len(items) > 0 {
		for _, it := range items {
			if err := m.consultSpec(it); err != nil {
				return err
			}
		}
		return nil
	}
	if c, ok := spec.(*Compound); ok && c.Fn == atLibrary {
		return nil
	}
	name, err := textOf(spec)
	if err != nil {
		return err
	}
	for _, cand := range []string{name, name + ".pl", name + ".pro", name + ".prolog"} {
		if st, err := os.Stat(cand); err == nil && !st.IsDir() {
			return m.consultFile(cand)
		}
	}
	return existErr("source_sink", spec)
}

func (m *Machine) consultFile(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return existErr("source_sink", mkAtom(path))
	}
	defer f.Close()
	abs, _ := filepath.Abs(path)
	return m.consultReader(f, abs, false)
}

func (m *Machine) consultReader(r io.Reader, name string, fromLib bool) error {
	oldFile, oldLoading, oldInits := m.loadFile, m.loading, m.inits
	oldDQ := m.flags["double_quotes"]
	m.loadFile, m.loading, m.inits = name, true, nil
	if fromLib {
		m.loadFile = ""
	}
	defer func() {
		m.loadFile, m.loading = oldFile, oldLoading
		if fromLib || true {
			m.flags["double_quotes"] = oldDQ
		}
	}()
	rd := newReader(m, r)
	for {
		t, err := rd.ReadTerm()
		if err == io.EOF {
			break
		}
		if err != nil {
			if se, ok := err.(*SyntaxError); ok {
				m.printMessage("ERROR", "Syntax error: "+se.Msg, fmt.Sprintf("%s:%d", name, se.Line))
				continue
			}
			return err
		}
		if herr := m.handleLoadedTerm(t, rd, fromLib); herr != nil {
			if _, ok := herr.(*haltSignal); ok {
				return herr
			}
			return herr
		}
	}
	inits := m.inits
	m.inits = oldInits
	for _, g := range inits {
		if err := m.runDirective(g, ""); err != nil {
			return err
		}
	}
	return nil
}

func (m *Machine) handleLoadedTerm(t Term, rd *Reader, fromLib bool) error {
	loc := m.locString(rd)
	if p := m.lookupPred(mkAtom("term_expansion"), 2, false); p != nil && len(p.clauses) > 0 && !fromLib {
		x := m.newVar()
		ok, err := m.solveOnce(mk("term_expansion", t, x))
		if err == nil && ok {
			res := deref(x)
			items, tail := listToSlice(res)
			if tail == Term(atNil) && res != Term(atNil) {
				for _, it := range items {
					if err := m.handleOne(it, rd, fromLib, loc, true); err != nil {
						return err
					}
				}
				return nil
			}
			return m.handleOne(res, rd, fromLib, loc, true)
		}
	}
	return m.handleOne(t, rd, fromLib, loc, false)
}

func (m *Machine) handleOne(t Term, rd *Reader, fromLib bool, loc string, expanded bool) error {
	t = deref(t)
	if c, ok := t.(*Compound); ok {
		switch {
		case (c.Fn == atNeck || c.Fn.Name == "?-") && len(c.Args) == 1:
			return m.runDirective(c.Args[0], loc)
		case c.Fn == atDCG && len(c.Args) == 2:
			nt, err := m.dcgRule(c)
			if err != nil {
				m.printMessage("ERROR", messageText(err.(*PrologError).Ball), loc)
				return nil
			}
			t = nt
		}
	}
	if !fromLib && !expanded {
		if sg := rd.Singletons(); len(sg) > 0 {
			m.printMessage("Warning", "Singleton variables: ["+strings.Join(sg, ",")+"]", loc)
		}
	}
	if err := m.addClause(t, true, fromLib); err != nil {
		if pe, ok := err.(*PrologError); ok {
			m.printMessage("ERROR", messageText(pe.Ball), loc)
			return nil
		}
		return err
	}
	return nil
}

func (m *Machine) runDirective(goal Term, loc string) error {
	ok, err := m.solveOnce(goal)
	if err != nil {
		if pe, isPE := err.(*PrologError); isPE {
			m.printMessage("ERROR", messageText(pe.Ball), loc)
			return nil
		}
		return err
	}
	if !ok {
		m.printMessage("Warning", "Goal (directive) failed: user:"+formatTermOpts(goal, writeOpts{quoted: true, numberVars: true}), loc)
	}
	return nil
}

// ---------- toplevel ----------

func (m *Machine) openCPs(base int) bool {
	for i := base + 1; i < len(m.cps); i++ {
		switch m.cps[i].kind {
		case cpClauses, cpAlts, cpGoal:
			return true
		}
	}
	return false
}

func (m *Machine) formatBindings(rd *Reader) string {
	type grp struct {
		names []string
		val   Term
	}
	var groups []*grp
	byVar := map[*Var]*grp{}
	for i, n := range rd.Names {
		if strings.HasPrefix(n, "_") {
			continue
		}
		v := deref(rd.Vars[i])
		if uv, ok := v.(*Var); ok {
			if g, ok := byVar[uv]; ok {
				g.names = append(g.names, n)
				continue
			}
			g := &grp{names: []string{n}, val: nil}
			byVar[uv] = g
			groups = append(groups, g)
			continue
		}
		groups = append(groups, &grp{names: []string{n}, val: v})
	}
	var lines []string
	for _, g := range groups {
		if g.val == nil {
			if len(g.names) > 1 {
				lines = append(lines, strings.Join(g.names, " = "))
			}
			continue
		}
		o := writeOpts{quoted: true, numberVars: true}
		w := &writer{o: o, ops: m.ops}
		w.write(g.val, 699)
		lines = append(lines, strings.Join(g.names, " = ")+" = "+w.sb.String())
	}
	if len(lines) == 0 {
		return "true"
	}
	return strings.Join(lines, ",\n")
}

func (m *Machine) toplevel(interactive, all bool) error {
	rd := m.stdinReader()
	for {
		if interactive {
			m.out.WriteString("?- ")
			m.out.Flush()
		}
		t, err := rd.ReadTerm()
		if err == io.EOF {
			if interactive {
				m.out.WriteString("\n")
			}
			return nil
		}
		if err != nil {
			if se, ok := err.(*SyntaxError); ok {
				m.printMessage("ERROR", "Syntax error: "+se.Msg, "")
				continue
			}
			return err
		}
		if err := m.runQuery(t, rd, interactive, all); err != nil {
			return err
		}
	}
}

func (m *Machine) runQuery(goal Term, rd *Reader, interactive, all bool) error {
	q := m.newQuery(goal)
	defer q.close()
	first := true
	for {
		ok, err := q.next()
		if err != nil {
			if pe, isPE := err.(*PrologError); isPE {
				m.printMessage("ERROR", messageText(pe.Ball), "")
				m.out.WriteString("\n")
				return nil
			}
			return err
		}
		if !ok {
			if first {
				m.out.WriteString("false.\n\n")
			} else {
				m.out.WriteString("false.\n\n")
			}
			return nil
		}
		first = false
		if m.streams[1].col != 0 {
			m.out.WriteString("\n")
			m.streams[1].col = 0
		}
		m.out.WriteString(m.formatBindings(rd))
		more := m.openCPs(q.base)
		if !more {
			m.out.WriteString(".\n\n")
			return nil
		}
		if all {
			m.out.WriteString(" ;\n")
			continue
		}
		if !interactive {
			m.out.WriteString(" .\n\n")
			return nil
		}
		m.out.WriteString(" ")
		m.out.Flush()
		ans := m.readAnswerChar()
		if ans == ';' || ans == 'n' || ans == ' ' || ans == '\t' {
			m.out.WriteString(";\n")
			continue
		}
		m.out.WriteString(".\n\n")
		return nil
	}
}

func (m *Machine) readAnswerChar() rune {
	src := m.stdinReader().src
	c := src.next()
	if c != '\n' && c != -1 {
		for src.peek() != '\n' && src.peek() != -1 {
			src.next()
		}
		src.next()
	}
	if c == '\n' {
		return '.'
	}
	return c
}
