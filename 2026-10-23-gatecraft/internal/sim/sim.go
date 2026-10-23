// Package sim is a cycle-accurate simulator over an AIG, with VCD output and a
// small testbench scripting language.
package sim

import (
	"fmt"
	"math/big"
	"strings"

	"gatecraft/internal/aig"
)

// Sim simulates one design.
type Sim struct {
	G      *aig.AIG
	S      *aig.Simulator
	Cycle  int
	inVal  map[string]*big.Int
	dirty  bool
	vcd    *VCD
	clocks map[string]bool
}

// New builds a simulator with all inputs 0 and flops at their init values.
func New(g *aig.AIG) *Sim {
	s := &Sim{G: g, S: aig.NewSimulator(g), inVal: map[string]*big.Int{}, dirty: true, clocks: map[string]bool{}}
	for _, l := range g.Latches {
		s.clocks[l.Clock] = true
	}
	for _, p := range g.Inputs {
		s.inVal[p.Name] = new(big.Int)
	}
	s.Eval()
	return s
}

// AttachVCD starts waveform recording (call before the first Tick).
func (s *Sim) AttachVCD(v *VCD) {
	s.vcd = v
	v.Header(s.G)
	s.Eval()
	v.Sample(s, 0, false)
}

// Reset returns all flops to their initial values and the cycle counter to 0.
func (s *Sim) Reset() {
	s.S.Reset()
	s.dirty = true
	s.Eval()
}

func mask(w int) *big.Int {
	return new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(w)), big.NewInt(1))
}

// Set drives an input port.
func (s *Sim) Set(port string, v *big.Int) error {
	p := s.G.FindInput(port)
	if p == nil {
		return fmt.Errorf("no input port %q", port)
	}
	if v.Sign() < 0 || v.BitLen() > len(p.Bits) {
		return fmt.Errorf("value %s does not fit in %d-bit input %q", v, len(p.Bits), port)
	}
	s.inVal[port] = new(big.Int).Set(v)
	s.dirty = true
	return nil
}

// Eval settles combinational logic for the current inputs and state.
func (s *Sim) Eval() {
	for i, pi := range s.G.PIs {
		var w uint64
		if v, ok := s.inVal[pi.Port]; ok && v.Bit(pi.Bit) == 1 {
			w = ^uint64(0)
		}
		s.S.SetPI(i, w)
	}
	s.S.Eval()
	s.dirty = false
}

func (s *Sim) bits(ls []aig.Lit) *big.Int {
	if s.dirty {
		s.Eval()
	}
	v := new(big.Int)
	for i, l := range ls {
		if s.S.Lit(l)&1 == 1 {
			v.SetBit(v, i, 1)
		}
	}
	return v
}

// Lookup returns the bit-vector literals for a port, register or internal net name.
func (s *Sim) Lookup(name string) ([]aig.Lit, error) {
	if p := s.G.FindOutput(name); p != nil {
		return p.Bits, nil
	}
	if p := s.G.FindInput(name); p != nil {
		return p.Bits, nil
	}
	if b, ok := s.G.Names[name]; ok {
		return b, nil
	}
	// bit select name[3]
	if i := strings.IndexByte(name, '['); i > 0 && strings.HasSuffix(name, "]") {
		var idx int
		if _, err := fmt.Sscanf(name[i:], "[%d]", &idx); err == nil {
			if b, err := s.Lookup(name[:i]); err == nil && idx >= 0 && idx < len(b) {
				return b[idx : idx+1], nil
			}
		}
	}
	return nil, fmt.Errorf("unknown signal %q", name)
}

// Get reads a signal's current value.
func (s *Sim) Get(name string) (*big.Int, int, error) {
	ls, err := s.Lookup(name)
	if err != nil {
		return nil, 0, err
	}
	return s.bits(ls), len(ls), nil
}

// ClockNames lists clock inputs used by flops.
func (s *Sim) ClockNames() []string { return s.G.Clocks() }

// Tick applies n rising edges of the named clock ("" = the only clock).
func (s *Sim) Tick(clock string, n int) error {
	if clock == "" {
		cs := s.G.Clocks()
		switch len(cs) {
		case 0:
			return fmt.Errorf("design has no flip-flops, so there is no clock to tick")
		case 1:
			clock = cs[0]
		default:
			return fmt.Errorf("design has several clocks (%s); name one", strings.Join(cs, ", "))
		}
	} else if !s.clocks[clock] {
		return fmt.Errorf("%q is not a clock of any flip-flop", clock)
	}
	for k := 0; k < n; k++ {
		s.Eval()
		if s.vcd != nil {
			s.vcd.Sample(s, s.Cycle*10+0, false)
		}
		s.S.Clock(func(l *aig.Latch) bool { return l.Clock == clock })
		s.Cycle++
		s.dirty = true
		s.Eval()
		if s.vcd != nil {
			s.vcd.Sample(s, (s.Cycle-1)*10+5, true)
		}
	}
	return nil
}

// Finish flushes the waveform with a final sample.
func (s *Sim) Finish() {
	if s.vcd != nil {
		s.Eval()
		s.vcd.Sample(s, s.Cycle*10, false)
		s.vcd.Close()
	}
}

// Format renders a value as decimal and hex.
func Format(v *big.Int, width int) string {
	if width == 1 {
		return v.String()
	}
	return fmt.Sprintf("%s (0x%s)", v.String(), v.Text(16))
}

// RunTrace drives the design through per-cycle input maps, ticking the clock
// after each cycle except that outputs are sampled before the final edge.
func (s *Sim) RunTrace(inputs []map[string]*big.Int) error {
	for t, in := range inputs {
		for _, p := range s.G.Inputs {
			if v, ok := in[p.Name]; ok && !s.clocks[p.Name] {
				if err := s.Set(p.Name, v); err != nil {
					return err
				}
			}
		}
		s.Eval()
		if len(s.G.Clocks()) > 0 {
			if err := s.Tick("", 1); err != nil {
				return err
			}
		} else if t == len(inputs)-1 && s.vcd != nil {
			s.vcd.Sample(s, s.Cycle*10, false)
		}
	}
	return nil
}

// TraceScript renders a counterexample trace as a testbench script that reproduces it.
func TraceScript(g *aig.AIG, inputs []map[string]*big.Int, watch []string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "# counterexample trace, %d cycles from reset\n", len(inputs))
	clocks := map[string]bool{}
	for _, c := range g.Clocks() {
		clocks[strings.SplitN(c, "[", 2)[0]] = true
	}
	for t, in := range inputs {
		fmt.Fprintf(&b, "# cycle %d\n", t)
		for _, p := range g.Inputs {
			if v, ok := in[p.Name]; ok && !clocks[p.Name] {
				fmt.Fprintf(&b, "set %s %s\n", p.Name, v.String())
			}
		}
		if len(watch) > 0 {
			fmt.Fprintf(&b, "print %s\n", strings.Join(watch, " "))
		}
		if t != len(inputs)-1 && len(g.Clocks()) > 0 {
			fmt.Fprintf(&b, "tick\n")
		}
	}
	return b.String()
}
