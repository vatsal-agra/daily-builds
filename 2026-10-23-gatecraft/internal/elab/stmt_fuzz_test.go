package elab_test

import (
	"fmt"
	"math/big"
	"math/rand"
	"strings"
	"testing"

	"gatecraft/internal/hdl"
	"gatecraft/internal/sim"
	"gatecraft/internal/testutil"
)

// ---- concrete reference interpreter for procedural code ----

type refMachine struct {
	w    map[string]int
	val  refEnv
	nba  map[string]*big.Int // pending non-blocking updates (name -> merged value)
	loop map[string]int64
}

func (m *refMachine) lvalueWidth(e hdl.Expr) int {
	switch e := e.(type) {
	case *hdl.Ident:
		return m.w[e.Name]
	case *hdl.Index:
		if e.Part == 0 {
			return 1
		}
		return int(e.Hi.(*hdl.Number).Val.Int64()-e.Lo.(*hdl.Number).Val.Int64()) + 1
	}
	panic("lvalue")
}

// write v (already width-limited) into the target; nonblocking writes go to a shadow copy.
func (m *refMachine) write(lhs hdl.Expr, v *big.Int, nb bool) {
	name := ""
	lo, width := 0, 0
	dynamicSkip := false
	switch e := lhs.(type) {
	case *hdl.Ident:
		name, lo, width = e.Name, 0, m.w[e.Name]
	case *hdl.Index:
		name = e.X.(*hdl.Ident).Name
		if e.Part == 0 {
			width = 1
			if n, ok := e.Hi.(*hdl.Number); ok {
				lo = int(n.Val.Int64())
			} else {
				ix := m.eval(e.Hi, selfW(e.Hi))
				if !ix.IsInt64() || ix.Int64() >= int64(m.w[name]) {
					dynamicSkip = true
				} else {
					lo = int(ix.Int64())
				}
			}
		} else {
			lo = int(e.Lo.(*hdl.Number).Val.Int64())
			width = int(e.Hi.(*hdl.Number).Val.Int64()) - lo + 1
		}
	}
	if dynamicSkip {
		return
	}
	target := m.val[name]
	if nb {
		if cur, ok := m.nba[name]; ok {
			target = cur
		}
	}
	nv := new(big.Int).Set(target)
	for i := 0; i < width; i++ {
		nv.SetBit(nv, lo+i, v.Bit(i))
	}
	if nb {
		m.nba[name] = nv
	} else {
		m.val[name] = nv
	}
}

func (m *refMachine) eval(e hdl.Expr, w int) *big.Int {
	// loop variables behave as integer constants
	if id, ok := e.(*hdl.Ident); ok {
		if v, ok := m.loop[id.Name]; ok {
			return trunc(big.NewInt(v), w)
		}
	}
	return ev(e, w, m.val)
}

func (m *refMachine) exec(s hdl.Stmt) {
	switch s := s.(type) {
	case *hdl.Block:
		for _, x := range s.Stmts {
			m.exec(x)
		}
	case *hdl.Assign:
		lw := m.lvalueWidth(s.LHS)
		cw := max(lw, selfW(s.RHS))
		v := trunc(m.eval(s.RHS, cw), lw)
		m.write(s.LHS, v, s.NonBlocking)
	case *hdl.If:
		if m.eval(s.C, selfW(s.C)).Sign() != 0 {
			m.exec(s.Then)
		} else if s.Else != nil {
			m.exec(s.Else)
		}
	case *hdl.Case:
		sw := selfW(s.Sel)
		for _, it := range s.Items {
			if len(it.Labels) == 0 {
				continue
			}
			for _, l := range it.Labels {
				cw := max(sw, selfW(l))
				if m.eval(s.Sel, cw).Cmp(m.eval(l, cw)) == 0 {
					m.exec(it.Body)
					return
				}
			}
		}
		for _, it := range s.Items {
			if len(it.Labels) == 0 {
				m.exec(it.Body)
				return
			}
		}
	case *hdl.For:
		name := s.Init.LHS.(*hdl.Ident).Name
		m.loop[name] = s.Init.RHS.(*hdl.Number).Val.Int64()
		for {
			cmp := s.Cond.(*hdl.Binary)
			if !(m.loop[name] < cmp.R.(*hdl.Number).Val.Int64()) {
				break
			}
			m.exec(s.Body)
			m.loop[name]++
		}
		delete(m.loop, name)
	}
}

// ---- random program generator ----

type progGen struct {
	*gen
	widths map[string]int
}

func (p *progGen) lhs(name string) string {
	w := p.widths[name]
	if w == 1 {
		return name
	}
	switch p.rng.Intn(6) {
	case 0:
		return fmt.Sprintf("%s[%d]", name, p.rng.Intn(w))
	case 1:
		hi := p.rng.Intn(w)
		lo := p.rng.Intn(hi + 1)
		return fmt.Sprintf("%s[%d:%d]", name, hi, lo)
	case 2:
		return fmt.Sprintf("%s[b[1:0]]", name) // dynamic bit write
	}
	return name
}

func (p *progGen) stmt(targets []string, nb bool, depth int, loopVar bool) string {
	op := "="
	if nb {
		op = "<="
	}
	pick := func() string { return targets[p.rng.Intn(len(targets))] }
	assign := func() string {
		return fmt.Sprintf("%s %s %s;", p.lhs(pick()), op, p.expr(2))
	}
	if depth <= 0 {
		return assign()
	}
	switch p.rng.Intn(7) {
	case 0:
		return fmt.Sprintf("if (%s) %s else %s", p.expr(1), p.stmt(targets, nb, depth-1, loopVar), p.stmt(targets, nb, depth-1, loopVar))
	case 1:
		return fmt.Sprintf("if (%s) begin %s %s end", p.expr(1), p.stmt(targets, nb, depth-1, loopVar), p.stmt(targets, nb, depth-1, loopVar))
	case 2:
		var b strings.Builder
		fmt.Fprintf(&b, "case (%s)\n", p.expr(1))
		for i := 0; i < 1+p.rng.Intn(3); i++ {
			fmt.Fprintf(&b, "  %d: %s\n", p.rng.Intn(8), p.stmt(targets, nb, depth-1, loopVar))
		}
		if p.rng.Intn(2) == 0 {
			fmt.Fprintf(&b, "  default: %s\n", p.stmt(targets, nb, depth-1, loopVar))
		}
		b.WriteString("endcase")
		return b.String()
	case 3:
		if !loopVar {
			return fmt.Sprintf("for (i = 0; i < %d; i = i + 1) begin %s end", 1+p.rng.Intn(4), p.stmt(targets, nb, depth-1, true))
		}
	case 4:
		return fmt.Sprintf("begin %s %s end", p.stmt(targets, nb, depth-1, loopVar), p.stmt(targets, nb, depth-1, loopVar))
	}
	return assign()
}

func TestProceduralCodeAgainstInterpreter(t *testing.T) {
	rng := rand.New(rand.NewSource(77))
	widths := map[string]int{"a": 4, "b": 4, "s": 1, "r1": 4, "r2": 4, "r3": 2, "t": 4, "y": 4, "z": 3}
	sigWidth = widths
	for it := 0; it < 250; it++ {
		g := &gen{rng: rng, names: []string{"a", "b", "s", "r1", "r2", "r3", "t", "y", "z"}}
		pg := &progGen{gen: g, widths: widths}
		clk := pg.stmt([]string{"r1", "r2", "r3"}, true, 3, false)
		tmp := pg.stmt([]string{"t"}, false, 1, false)
		// the combinational block starts by defining y and z, then may refine them (reading them is safe)
		comb := pg.stmt([]string{"y", "z"}, false, 3, false)
		src := fmt.Sprintf(`module m(input clk, input [3:0] a, input [3:0] b, input s, output reg [3:0] y, output reg [2:0] z, output [3:0] w);
  reg [3:0] r1, r2; reg [1:0] r3; reg [3:0] t;
  integer i;
  always @(posedge clk) begin
    r1 <= r1 + 4'd1; r3 <= r3 ^ {1'b0, s}; t = t;
    %s
    %s
    r2 <= r2 ^ t;
  end
  always @* begin
    y = a ^ r1; z = r3 + s;
    %s
  end
  assign w = r1 ^ r2;
endmodule`, tmp, clk, comb)
		f, err := hdl.Parse("p.v", src)
		if err != nil {
			t.Fatalf("parse: %v\n%s", err, src)
		}
		g2, err := testutil.Try(src, "")
		if err != nil {
			if strings.Contains(err.Error(), "out of range") || strings.Contains(err.Error(), "mixes") || strings.Contains(err.Error(), "unsized number") {
				continue
			}
			t.Fatalf("elab: %v\n%s", err, src)
		}
		m := f.Modules[0]
		// reference machine
		ref := &refMachine{w: widths, val: refEnv{}, nba: map[string]*big.Int{}, loop: map[string]int64{}}
		for n := range widths {
			ref.val[n] = new(big.Int)
		}
		s := sim.New(g2)
		for cyc := 0; cyc < 24; cyc++ {
			av, bv, sv := big.NewInt(int64(rng.Intn(16))), big.NewInt(int64(rng.Intn(16))), big.NewInt(int64(rng.Intn(2)))
			ref.val["a"], ref.val["b"], ref.val["s"] = av, bv, sv
			s.Set("a", av)
			s.Set("b", bv)
			s.Set("s", sv)
			// combinational outputs (before the edge)
			ref.exec(m.Always[1].Body)
			check := func(phase string) {
				for _, n := range []string{"y", "z"} {
					got, _, _ := s.Get(n)
					if got.Cmp(ref.val[n]) != 0 {
						t.Fatalf("iter %d cycle %d %s: %s = %s, reference %s\n%s", it, cyc, phase, n, got, ref.val[n], src)
					}
				}
				for _, n := range []string{"r1", "r2", "r3", "t"} {
					got, _, err := s.Get(n)
					if err != nil {
						t.Fatal(err)
					}
					if got.Cmp(ref.val[n]) != 0 {
						t.Fatalf("iter %d cycle %d %s: reg %s = %s, reference %s\n%s", it, cyc, phase, n, got, ref.val[n], src)
					}
				}
				w, _, _ := s.Get("w")
				if exp := new(big.Int).Xor(ref.val["r1"], ref.val["r2"]); w.Cmp(exp) != 0 {
					t.Fatalf("iter %d cycle %d: w mismatch", it, cyc)
				}
			}
			check("pre-edge")
			// clock edge: run the clocked block against pre-edge values, then apply NBAs
			ref.nba = map[string]*big.Int{}
			ref.exec(m.Always[0].Body)
			for n, v := range ref.nba {
				ref.val[n] = v
			}
			if err := s.Tick("clk", 1); err != nil {
				t.Fatal(err)
			}
			ref.exec(m.Always[1].Body)
			check("post-edge")
		}
	}
}
