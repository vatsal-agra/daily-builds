package sim

import (
	"bufio"
	"fmt"
	"io"
	"math/big"
	"math/rand"
	"strconv"
	"strings"
)

// Result summarises a testbench run.
type Result struct {
	Checks   int
	Failures []string
	Cycles   int
}

func (r *Result) OK() bool { return len(r.Failures) == 0 }

type cmd struct {
	line int
	toks []string
	body []*cmd // for repeat
}

// ParseValue parses 42, 0x2a, 0b101010, 8'h2a, 'd9.
func ParseValue(s string) (*big.Int, error) {
	t := strings.ReplaceAll(s, "_", "")
	if q := strings.IndexByte(t, '\''); q >= 0 {
		if q+1 >= len(t) {
			return nil, fmt.Errorf("bad value %q", s)
		}
		base := map[byte]int{'b': 2, 'o': 8, 'd': 10, 'h': 16}[t[q+1]|0x20]
		if base == 0 {
			return nil, fmt.Errorf("bad value %q", s)
		}
		v, ok := new(big.Int).SetString(t[q+2:], base)
		if !ok {
			return nil, fmt.Errorf("bad value %q", s)
		}
		return v, nil
	}
	v, ok := new(big.Int).SetString(t, 0)
	if !ok {
		return nil, fmt.Errorf("bad value %q", s)
	}
	return v, nil
}

func parseScript(r io.Reader) ([]*cmd, error) {
	sc := bufio.NewScanner(r)
	var root []*cmd
	stack := [][]*cmd{}
	var openRepeat []*cmd
	line := 0
	cur := &root
	for sc.Scan() {
		line++
		txt := sc.Text()
		if i := strings.IndexAny(txt, "#"); i >= 0 {
			txt = txt[:i]
		}
		if i := strings.Index(txt, "//"); i >= 0 {
			txt = txt[:i]
		}
		toks := strings.Fields(txt)
		if len(toks) == 0 {
			continue
		}
		switch toks[0] {
		case "repeat":
			if len(toks) != 2 {
				return nil, fmt.Errorf("line %d: usage: repeat <n>", line)
			}
			c := &cmd{line: line, toks: toks}
			*cur = append(*cur, c)
			stack = append(stack, nil)
			openRepeat = append(openRepeat, c)
			cur = &c.body
		case "end":
			if len(openRepeat) == 0 {
				return nil, fmt.Errorf("line %d: 'end' without 'repeat'", line)
			}
			openRepeat = openRepeat[:len(openRepeat)-1]
			stack = stack[:len(stack)-1]
			if len(openRepeat) == 0 {
				cur = &root
			} else {
				cur = &openRepeat[len(openRepeat)-1].body
			}
		default:
			*cur = append(*cur, &cmd{line: line, toks: toks})
		}
	}
	if len(openRepeat) != 0 {
		return nil, fmt.Errorf("line %d: 'repeat' without matching 'end'", openRepeat[len(openRepeat)-1].line)
	}
	return root, sc.Err()
}

// RunScript executes a testbench script. out receives print output.
func (s *Sim) RunScript(r io.Reader, out io.Writer) (*Result, error) {
	prog, err := parseScript(r)
	if err != nil {
		return nil, err
	}
	res := &Result{}
	rng := rand.New(rand.NewSource(1))
	var run func(cs []*cmd) error
	run = func(cs []*cmd) error {
		for _, c := range cs {
			if err := s.runCmd(c, res, rng, out, run); err != nil {
				return fmt.Errorf("line %d: %v", c.line, err)
			}
		}
		return nil
	}
	if err := run(prog); err != nil {
		return res, err
	}
	res.Cycles = s.Cycle
	return res, nil
}

func (s *Sim) runCmd(c *cmd, res *Result, rng *rand.Rand, out io.Writer, run func([]*cmd) error) error {
	t := c.toks
	need := func(n int, usage string) error {
		if len(t) < n {
			return fmt.Errorf("usage: %s", usage)
		}
		return nil
	}
	switch t[0] {
	case "set":
		if err := need(3, "set <input> <value>"); err != nil {
			return err
		}
		v, err := ParseValue(t[2])
		if err != nil {
			return err
		}
		return s.Set(t[1], v)
	case "tick":
		clock, n := "", 1
		for _, a := range t[1:] {
			if k, err := strconv.Atoi(a); err == nil {
				n = k
			} else {
				clock = a
			}
		}
		if n < 0 {
			return fmt.Errorf("negative tick count")
		}
		return s.Tick(clock, n)
	case "eval":
		s.Eval()
	case "reset":
		s.Reset()
	case "seed":
		if err := need(2, "seed <n>"); err != nil {
			return err
		}
		k, err := strconv.ParseInt(t[1], 0, 64)
		if err != nil {
			return err
		}
		rng.Seed(k)
	case "randomize":
		names := t[1:]
		if len(names) == 0 {
			for _, p := range s.G.Inputs {
				if !s.clocks[p.Name] {
					names = append(names, p.Name)
				}
			}
		}
		for _, n := range names {
			p := s.G.FindInput(n)
			if p == nil {
				return fmt.Errorf("no input port %q", n)
			}
			v := new(big.Int)
			for i := range p.Bits {
				if rng.Intn(2) == 1 {
					v.SetBit(v, i, 1)
				}
			}
			if err := s.Set(n, v); err != nil {
				return err
			}
		}
	case "print":
		for _, n := range t[1:] {
			v, w, err := s.Get(n)
			if err != nil {
				return err
			}
			fmt.Fprintf(out, "[cycle %d] %s = %s\n", s.Cycle, n, Format(v, w))
		}
	case "expect":
		// expect <sig> [op] <value>
		if err := need(3, "expect <signal> [==|!=|<|<=|>|>=] <value>"); err != nil {
			return err
		}
		op, vs := "==", t[2]
		if len(t) >= 4 {
			op, vs = t[2], t[3]
		}
		want, err := ParseValue(vs)
		if err != nil {
			return err
		}
		got, w, err := s.Get(t[1])
		if err != nil {
			return err
		}
		res.Checks++
		cmp := got.Cmp(want)
		ok := false
		switch op {
		case "==":
			ok = cmp == 0
		case "!=":
			ok = cmp != 0
		case "<":
			ok = cmp < 0
		case "<=":
			ok = cmp <= 0
		case ">":
			ok = cmp > 0
		case ">=":
			ok = cmp >= 0
		default:
			return fmt.Errorf("unknown comparison %q", op)
		}
		if !ok {
			msg := fmt.Sprintf("line %d, cycle %d: expected %s %s %s, got %s", c.line, s.Cycle, t[1], op, want.String(), Format(got, w))
			res.Failures = append(res.Failures, msg)
			fmt.Fprintf(out, "FAIL %s\n", msg)
		}
	case "repeat":
		n, err := strconv.Atoi(t[1])
		if err != nil || n < 0 {
			return fmt.Errorf("bad repeat count %q", t[1])
		}
		for i := 0; i < n; i++ {
			if err := run(c.body); err != nil {
				return err
			}
		}
	default:
		return fmt.Errorf("unknown command %q", t[0])
	}
	return nil
}
