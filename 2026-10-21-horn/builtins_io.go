package main

import (
	"bufio"
	"io"
	"math"
	"math/big"
	"os"
	"strconv"
	"strings"
	"unicode/utf8"
)

type outSink struct{}

type Stream struct {
	id    int64
	alias string
	w     *bufio.Writer
	sb    *strings.Builder
	f     *os.File
	rd    *Reader
	col   int
	input bool
	path  string
	mode  string
}

func (m *Machine) initStreams() {
	in := &Stream{id: 0, alias: "user_input", input: true, mode: "read"}
	out := &Stream{id: 1, alias: "user_output", w: m.out, mode: "append"}
	er := &Stream{id: 2, alias: "user_error", w: m.errOut, mode: "append"}
	m.streams[0], m.streams[1], m.streams[2] = in, out, er
	m.nextStream = 3
	m.curIn, m.curOut = 0, 1
}

func (m *Machine) stdinReader() *Reader {
	s := m.streams[0]
	if s.rd == nil {
		s.rd = newReader(m, os.Stdin)
	}
	return s.rd
}

func (m *Machine) flushOut() { m.out.Flush() }

func (m *Machine) streamTerm(s *Stream) Term { return mk("$stream", Int(s.id)) }

func (m *Machine) getStream(t Term) (*Stream, error) {
	t = deref(t)
	switch x := t.(type) {
	case *Var:
		return nil, instErr()
	case *Atom:
		for _, s := range m.streams {
			if s.alias == x.Name {
				return s, nil
			}
		}
		return nil, existErr("stream", t)
	case *Compound:
		if x.Fn.Name == "$stream" && len(x.Args) == 1 {
			if id, ok := deref(x.Args[0]).(Int); ok {
				if s, ok := m.streams[int64(id)]; ok {
					return s, nil
				}
				return nil, existErr("stream", t)
			}
		}
	}
	return nil, domErr("stream_or_alias", t)
}

func (m *Machine) streamWrite(s *Stream, text string) {
	if text == "" {
		return
	}
	if i := strings.LastIndexByte(text, '\n'); i >= 0 {
		s.col = utf8.RuneCountInString(text[i+1:])
	} else {
		s.col += utf8.RuneCountInString(text)
	}
	switch {
	case s.sb != nil:
		s.sb.WriteString(text)
	case s.id == 2:
		m.out.Flush()
		s.w.WriteString(text)
		s.w.Flush()
	case s.w != nil:
		s.w.WriteString(text)
	}
}

func (m *Machine) write(text string) { m.streamWrite(m.streams[m.curOut], text) }

func (m *Machine) outStream(t Term) (*Stream, error) {
	s, err := m.getStream(t)
	if err != nil {
		return nil, err
	}
	if s.input {
		return nil, permErr("output", "stream", t)
	}
	return s, nil
}

func (m *Machine) inStream(t Term) (*Stream, error) {
	s, err := m.getStream(t)
	if err != nil {
		return nil, err
	}
	if !s.input {
		return nil, permErr("input", "stream", t)
	}
	if s.rd == nil && s.id == 0 {
		m.stdinReader()
	}
	if s.id == 0 {
		m.out.Flush()
	}
	return s, nil
}

func parseWriteOpts(opts Term) (writeOpts, error) {
	o := writeOpts{numberVars: false}
	items, err := getList(opts)
	if err != nil {
		return o, err
	}
	for _, it := range items {
		c, ok := deref(it).(*Compound)
		if !ok || len(c.Args) != 1 {
			continue
		}
		v := deref(c.Args[0]) == Term(atTrue)
		switch c.Fn.Name {
		case "quoted":
			o.quoted = v
		case "ignore_ops":
			o.ignoreOps = v
		case "numbervars":
			o.numberVars = v
		}
	}
	return o, nil
}

func (m *Machine) withOutputTo(spec Term, goal Term) (bool, error) {
	spec = deref(spec)
	c, ok := spec.(*Compound)
	if !ok || len(c.Args) != 1 {
		return false, domErr("output_sink", spec)
	}
	s := &Stream{id: m.nextStream, sb: &strings.Builder{}, mode: "write"}
	m.nextStream++
	m.streams[s.id] = s
	old := m.curOut
	m.curOut = s.id
	ok2, err := m.solveOnce(goal)
	m.curOut = old
	delete(m.streams, s.id)
	if err != nil || !ok2 {
		return false, err
	}
	return m.unify(c.Args[0], sinkValue(c.Fn.Name, s.sb.String())), nil
}

func sinkValue(kind, text string) Term {
	switch kind {
	case "codes":
		return codesOf(text)
	case "chars":
		return charsOf(text)
	}
	return mkAtom(text)
}

func (m *Machine) readTerm(s *Stream, opts Term) (Term, error) {
	rd := s.rd
	t, err := rd.ReadTerm()
	if err == io.EOF {
		t = atEOF
	} else if err != nil {
		if se, ok := err.(*SyntaxError); ok {
			return nil, throwTerm(mk("syntax_error", mkAtom(se.Msg)), mk("stream", m.streamTerm(s), Int(se.Line)))
		}
		return nil, err
	}
	if opts != nil {
		items, _ := listToSlice(opts)
		for _, it := range items {
			c, ok := deref(it).(*Compound)
			if !ok || len(c.Args) != 1 {
				continue
			}
			switch c.Fn.Name {
			case "variable_names":
				var bs []Term
				for i, n := range rd.Names {
					bs = append(bs, mk("=", mkAtom(n), rd.Vars[i]))
				}
				if !m.unify(c.Args[0], mkList(bs, atNil)) {
					return nil, nil
				}
			case "variables":
				var vs []Term
				for _, v := range rd.Vars {
					vs = append(vs, v)
				}
				m.unify(c.Args[0], mkList(vs, atNil))
			}
		}
	}
	return t, nil
}

func (m *Machine) openFile(name Term, mode Term, st Term) (bool, error) {
	fn, err := textOf(name)
	if err != nil {
		return false, err
	}
	md, err := getAtom(mode)
	if err != nil {
		return false, err
	}
	s := &Stream{id: m.nextStream, path: fn, mode: md.Name}
	var f *os.File
	switch md.Name {
	case "read":
		f, err = os.Open(fn)
		s.input = true
	case "write":
		f, err = os.Create(fn)
	case "append":
		f, err = os.OpenFile(fn, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	default:
		return false, domErr("io_mode", mode)
	}
	if err != nil {
		if os.IsNotExist(err) {
			return false, existErr("source_sink", name)
		}
		return false, permErr("open", "source_sink", name)
	}
	s.f = f
	if s.input {
		s.rd = newReader(m, f)
	} else {
		s.w = bufio.NewWriter(f)
	}
	m.nextStream++
	m.streams[s.id] = s
	return m.unify(st, m.streamTerm(s)), nil
}

func (m *Machine) closeStream(s *Stream) {
	if s.id <= 2 {
		return
	}
	if s.w != nil {
		s.w.Flush()
	}
	if s.f != nil {
		s.f.Close()
	}
	delete(m.streams, s.id)
	if m.curOut == s.id {
		m.curOut = 1
	}
	if m.curIn == s.id {
		m.curIn = 0
	}
}

func (m *Machine) installIOBuiltins() {
	wr := func(name string, o writeOpts) {
		m.det(name, 1, func(m *Machine, a []Term) (bool, error) {
			m.write(formatTermOpts(a[0], o))
			return true, nil
		})
		m.det(name, 2, func(m *Machine, a []Term) (bool, error) {
			s, err := m.outStream(a[0])
			if err != nil {
				return false, err
			}
			m.streamWrite(s, formatTermOpts(a[1], o))
			return true, nil
		})
	}
	wr("write", writeOpts{numberVars: true})
	wr("print", writeOpts{quoted: true, numberVars: true})
	wr("writeq", writeOpts{quoted: true, numberVars: true})
	wr("write_canonical", writeOpts{quoted: true, ignoreOps: false})
	m.det("writeln", 1, func(m *Machine, a []Term) (bool, error) {
		m.write(formatTermOpts(a[0], writeOpts{numberVars: true}) + "\n")
		return true, nil
	})
	m.det("writeln", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		m.streamWrite(s, formatTermOpts(a[1], writeOpts{numberVars: true})+"\n")
		return true, nil
	})
	m.det("write_term", 2, func(m *Machine, a []Term) (bool, error) {
		o, err := parseWriteOpts(a[1])
		if err != nil {
			return false, err
		}
		m.write(formatTermOpts(a[0], o))
		return true, nil
	})
	m.det("write_term", 3, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		o, err := parseWriteOpts(a[2])
		if err != nil {
			return false, err
		}
		m.streamWrite(s, formatTermOpts(a[1], o))
		return true, nil
	})
	m.det("nl", 0, func(m *Machine, a []Term) (bool, error) { m.write("\n"); return true, nil })
	m.det("nl", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		m.streamWrite(s, "\n")
		return true, nil
	})
	m.det("tab", 1, func(m *Machine, a []Term) (bool, error) {
		n, err := m.eval(a[0])
		if err != nil {
			return false, err
		}
		if i, ok := n.(Int); ok && i > 0 {
			m.write(strings.Repeat(" ", int(i)))
		}
		return true, nil
	})
	m.det("tab", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		n, err := m.eval(a[1])
		if err != nil {
			return false, err
		}
		if i, ok := n.(Int); ok && i > 0 {
			m.streamWrite(s, strings.Repeat(" ", int(i)))
		}
		return true, nil
	})
	putc := func(m *Machine, s *Stream, t Term, code bool) (bool, error) {
		t = deref(t)
		switch x := t.(type) {
		case *Var:
			return false, instErr()
		case *Atom:
			if utf8.RuneCountInString(x.Name) == 1 && !code {
				m.streamWrite(s, x.Name)
				return true, nil
			}
		case Int:
			if code {
				m.streamWrite(s, string(rune(x)))
				return true, nil
			}
		}
		if code {
			return false, typeErr("integer", t)
		}
		return false, typeErr("character", t)
	}
	m.det("put_char", 1, func(m *Machine, a []Term) (bool, error) { return putc(m, m.streams[m.curOut], a[0], false) })
	m.det("put_char", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		return putc(m, s, a[1], false)
	})
	m.det("put_code", 1, func(m *Machine, a []Term) (bool, error) { return putc(m, m.streams[m.curOut], a[0], true) })
	m.det("put_code", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		return putc(m, s, a[1], true)
	})
	m.det("flush_output", 0, func(m *Machine, a []Term) (bool, error) {
		s := m.streams[m.curOut]
		if s.w != nil {
			s.w.Flush()
		}
		return true, nil
	})
	m.det("flush_output", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		if s.w != nil {
			s.w.Flush()
		}
		return true, nil
	})
	m.det("format", 1, func(m *Machine, a []Term) (bool, error) {
		return m.formatTo(m.streams[m.curOut], a[0], atNil)
	})
	m.det("format", 2, func(m *Machine, a []Term) (bool, error) {
		return m.formatTo(m.streams[m.curOut], a[0], a[1])
	})
	m.det("format", 3, func(m *Machine, a []Term) (bool, error) {
		sink := deref(a[0])
		if c, ok := sink.(*Compound); ok && len(c.Args) == 1 && c.Fn.Name != "$stream" {
			s := &Stream{id: -1, sb: &strings.Builder{}}
			if ok, err := m.formatTo(s, a[1], a[2]); !ok || err != nil {
				return ok, err
			}
			return m.unify(c.Args[0], sinkValue(c.Fn.Name, s.sb.String())), nil
		}
		s, err := m.outStream(sink)
		if err != nil {
			return false, err
		}
		return m.formatTo(s, a[1], a[2])
	})
	m.det("with_output_to", 2, func(m *Machine, a []Term) (bool, error) { return m.withOutputTo(a[0], a[1]) })
	m.det("read", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(mk("$stream", Int(m.curIn)))
		if err != nil {
			return false, err
		}
		t, err := m.readTerm(s, nil)
		if err != nil {
			return false, err
		}
		return m.unify(a[0], t), nil
	})
	m.det("read", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(a[0])
		if err != nil {
			return false, err
		}
		t, err := m.readTerm(s, nil)
		if err != nil {
			return false, err
		}
		return m.unify(a[1], t), nil
	})
	m.det("read_term", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(mk("$stream", Int(m.curIn)))
		if err != nil {
			return false, err
		}
		t, err := m.readTerm(s, a[1])
		if err != nil || t == nil {
			return false, err
		}
		return m.unify(a[0], t), nil
	})
	m.det("read_term", 3, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(a[0])
		if err != nil {
			return false, err
		}
		t, err := m.readTerm(s, a[2])
		if err != nil || t == nil {
			return false, err
		}
		return m.unify(a[1], t), nil
	})
	getc := func(peek, code bool) DetFn {
		return func(m *Machine, a []Term) (bool, error) {
			var s *Stream
			var err error
			var out Term
			if len(a) == 2 {
				s, err = m.inStream(a[0])
				out = a[1]
			} else {
				s, err = m.inStream(mk("$stream", Int(m.curIn)))
				out = a[0]
			}
			if err != nil {
				return false, err
			}
			var r rune
			if peek {
				r = s.rd.src.peek()
			} else {
				r = s.rd.src.next()
			}
			var v Term
			switch {
			case r == -1 && code:
				v = Int(-1)
			case r == -1:
				v = atEOF
			case code:
				v = Int(r)
			default:
				v = mkAtom(string(r))
			}
			return m.unify(out, v), nil
		}
	}
	for _, n := range []struct {
		name       string
		peek, code bool
	}{{"get_char", false, false}, {"peek_char", true, false}, {"get_code", false, true}, {"peek_code", true, true}} {
		m.det(n.name, 1, getc(n.peek, n.code))
		m.det(n.name, 2, getc(n.peek, n.code))
	}
	m.det("at_end_of_stream", 0, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(mk("$stream", Int(m.curIn)))
		if err != nil {
			return false, err
		}
		return s.rd.src.peek() == -1, nil
	})
	m.det("at_end_of_stream", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(a[0])
		if err != nil {
			return false, err
		}
		return s.rd.src.peek() == -1, nil
	})
	m.det("open", 3, func(m *Machine, a []Term) (bool, error) { return m.openFile(a[0], a[1], a[2]) })
	m.det("open", 4, func(m *Machine, a []Term) (bool, error) { return m.openFile(a[0], a[1], a[2]) })
	m.det("close", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.getStream(a[0])
		if err != nil {
			return false, err
		}
		m.closeStream(s)
		return true, nil
	})
	m.det("close", 2, func(m *Machine, a []Term) (bool, error) {
		s, err := m.getStream(a[0])
		if err != nil {
			return false, err
		}
		m.closeStream(s)
		return true, nil
	})
	m.det("current_output", 1, func(m *Machine, a []Term) (bool, error) {
		return m.unify(a[0], m.streamTerm(m.streams[m.curOut])), nil
	})
	m.det("current_input", 1, func(m *Machine, a []Term) (bool, error) {
		return m.unify(a[0], m.streamTerm(m.streams[m.curIn])), nil
	})
	m.det("set_output", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.outStream(a[0])
		if err != nil {
			return false, err
		}
		m.curOut = s.id
		return true, nil
	})
	m.det("set_input", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := m.inStream(a[0])
		if err != nil {
			return false, err
		}
		m.curIn = s.id
		return true, nil
	})
	m.det("see", 1, func(m *Machine, a []Term) (bool, error) {
		var st Var
		if ok, err := m.openFile(a[0], mkAtom("read"), &st); !ok || err != nil {
			return ok, err
		}
		s, _ := m.getStream(&st)
		m.curIn = s.id
		return true, nil
	})
	m.det("seen", 0, func(m *Machine, a []Term) (bool, error) {
		if s, ok := m.streams[m.curIn]; ok {
			m.closeStream(s)
		}
		m.curIn = 0
		return true, nil
	})
	m.det("tell", 1, func(m *Machine, a []Term) (bool, error) {
		var st Var
		if ok, err := m.openFile(a[0], mkAtom("write"), &st); !ok || err != nil {
			return ok, err
		}
		s, _ := m.getStream(&st)
		m.curOut = s.id
		return true, nil
	})
	m.det("told", 0, func(m *Machine, a []Term) (bool, error) {
		if s, ok := m.streams[m.curOut]; ok {
			m.closeStream(s)
		}
		m.curOut = 1
		return true, nil
	})
	m.det("exists_file", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		st, err := os.Stat(s)
		return err == nil && !st.IsDir(), nil
	})
	m.det("delete_file", 1, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		if os.Remove(s) != nil {
			return false, existErr("file", a[0])
		}
		return true, nil
	})
	m.det("read_term_from_atom", 3, func(m *Machine, a []Term) (bool, error) {
		s, err := textOf(a[0])
		if err != nil {
			return false, err
		}
		t, _, err := m.parseTermFromText(s)
		if err != nil {
			return false, err
		}
		return m.unify(a[1], t), nil
	})
}

// ---------- format/2 ----------

func (m *Machine) formatTo(s *Stream, fmtT Term, argsT Term) (bool, error) {
	f, err := textOf(fmtT)
	if err != nil {
		return false, err
	}
	var args []Term
	argsT = deref(argsT)
	if items, tail := listToSlice(argsT); tail == Term(atNil) {
		args = items
	} else {
		args = []Term{argsT}
	}
	out, err := m.formatString(f, args, s.col)
	if err != nil {
		return false, err
	}
	m.streamWrite(s, out)
	return true, nil
}

func fmtErr(msg string) error {
	return throwTerm(mk("format", mkAtom(msg)), nil)
}

type fillPt struct {
	pos int
	ch  rune
}

func groupDigits(s string, sep string, n int) string {
	neg := strings.HasPrefix(s, "-")
	if neg {
		s = s[1:]
	}
	var parts []string
	for len(s) > n {
		parts = append([]string{s[len(s)-n:]}, parts...)
		s = s[:len(s)-n]
	}
	parts = append([]string{s}, parts...)
	r := strings.Join(parts, sep)
	if neg {
		r = "-" + r
	}
	return r
}

func (m *Machine) formatString(f string, args []Term, startCol int) (string, error) {
	var out []rune
	rs := []rune(f)
	argi := 0
	lineStart := 0 // index in out where current line starts
	baseCol := startCol
	segStart := 0
	var fills []fillPt
	lastStop := startCol
	colNow := func() int { return baseCol + len(out) - lineStart }
	nextArg := func() (Term, error) {
		if argi >= len(args) {
			return nil, fmtErr("not enough arguments")
		}
		a := args[argi]
		argi++
		return a, nil
	}
	emit := func(s string) {
		for _, r := range s {
			out = append(out, r)
			if r == '\n' {
				lineStart = len(out)
				baseCol = 0
				segStart = len(out)
				fills = nil
				lastStop = 0
			}
		}
	}
	for i := 0; i < len(rs); i++ {
		c := rs[i]
		if c != '~' {
			emit(string(c))
			continue
		}
		i++
		if i >= len(rs) {
			return string(out), fmtErr("truncated format specification")
		}
		numArg := -1
		fillCh := ' '
		if rs[i] == '*' {
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			n, err := getInt(a)
			if err != nil {
				return string(out), fmtErr("no or negative integer for `*' argument")
			}
			numArg = n
			i++
		} else if rs[i] == '`' {
			fillCh = rs[i+1]
			numArg = int(rs[i+1])
			i += 2
		} else {
			st := i
			for i < len(rs) && rs[i] >= '0' && rs[i] <= '9' {
				i++
			}
			if i > st {
				numArg, _ = strconv.Atoi(string(rs[st:i]))
			}
		}
		if i >= len(rs) {
			return string(out), fmtErr("truncated format specification")
		}
		d := rs[i]
		switch d {
		case 'w', 'p', 'q', 'a', 'd', 'D', 's', 'e', 'f', 'g', 'c', 'r', 'R', 'i', 'k', 'x':
			if d != 'x' {
			}
		}
		switch d {
		case '~':
			emit("~")
		case 'n':
			n := 1
			if numArg > 0 {
				n = numArg
			}
			emit(strings.Repeat("\n", n))
		case 'w', 'p', 'q', 'k':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			o := writeOpts{numberVars: true}
			if d == 'q' || d == 'p' {
				o.quoted = true
			}
			if d == 'k' {
				o = writeOpts{quoted: true, ignoreOps: true}
			}
			emit(formatTermOpts(a, o))
		case 'a':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			s, err := textOf(a)
			if err != nil {
				return string(out), err
			}
			emit(s)
		case 's':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			s, err := textOf(a)
			if err != nil {
				return string(out), err
			}
			emit(s)
		case 'd', 'D':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			v, err := m.eval(a)
			if err != nil || !isInt(v) {
				return string(out), fmtErr("~D expects an integer argument")
			}
			s := toBig(v).String()
			frac := ""
			if numArg > 0 {
				neg := strings.HasPrefix(s, "-")
				if neg {
					s = s[1:]
				}
				for len(s) <= numArg {
					s = "0" + s
				}
				frac = "." + s[len(s)-numArg:]
				s = s[:len(s)-numArg]
				if neg {
					s = "-" + s
				}
			}
			if d == 'D' {
				s = groupDigits(s, ",", 3)
			}
			emit(s + frac)
		case 'f', 'e', 'g':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			v, err := m.eval(a)
			if err != nil {
				return string(out), err
			}
			prec := 6
			if numArg >= 0 {
				prec = numArg
			}
			if d == 'f' && isInt(v) {
				bf := new(big.Float).SetPrec(2000).SetInt(toBig(v))
				emit(bf.Text('f', prec))
			} else {
				emit(strconv.FormatFloat(toFloat(v), byte(d), prec, 64))
			}
		case 'c':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			code, err := getInt(a)
			if err != nil {
				return string(out), err
			}
			n := 1
			if numArg > 0 {
				n = numArg
			}
			emit(strings.Repeat(string(rune(code)), n))
		case 'r', 'R':
			a, err := nextArg()
			if err != nil {
				return string(out), err
			}
			v, err := m.eval(a)
			if err != nil || !isInt(v) {
				return string(out), fmtErr("~r expects an integer argument")
			}
			if numArg < 2 || numArg > 36 {
				return string(out), fmtErr("~r requires a radix between 2 and 36")
			}
			s := toBig(v).Text(numArg)
			if d == 'R' {
				s = strings.ToUpper(s)
			}
			emit(s)
		case 'i':
			if _, err := nextArg(); err != nil {
				return string(out), err
			}
		case 't':
			fills = append(fills, fillPt{pos: len(out), ch: fillCh})
		case '|', '+':
			target := 0
			if d == '|' {
				target = colNow()
				if numArg >= 0 {
					target = numArg
				}
			} else {
				w := 8
				if numArg >= 0 {
					w = numArg
				}
				target = lastStop + w
			}
			pad := target - colNow()
			if pad > 0 {
				if len(fills) == 0 {
					if d == '+' {
						// default: pad on the left for column ~+? SWI pads right (text left aligned)
						fills = append(fills, fillPt{pos: len(out), ch: ' '})
					} else {
						fills = append(fills, fillPt{pos: len(out), ch: ' '})
					}
				}
				per := pad / len(fills)
				extra := pad % len(fills)
				var nout []rune
				prev := 0
				for k, fp := range fills {
					nout = append(nout, out[prev:fp.pos]...)
					cnt := per
					if k == len(fills)-1 {
						cnt += extra
					}
					for j := 0; j < cnt; j++ {
						nout = append(nout, fp.ch)
					}
					prev = fp.pos
				}
				nout = append(nout, out[prev:]...)
				out = nout
			}
			lastStop = target
			if pad < 0 {
				lastStop = colNow()
			}
			segStart = len(out)
			fills = nil
		default:
			return string(out), fmtErr("unknown directive ~" + string(d))
		}
	}
	_ = segStart
	if argi < len(args) {
		return string(out), fmtErr("too many arguments")
	}
	return string(out), nil
}

var _ = math.Pi
