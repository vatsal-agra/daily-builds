package vm

import (
	"strings"
	"testing"

	"dominion/ir"
)

func prog(code []Instr, funcs []FuncInfo) *Program {
	return &Program{Code: code, Funcs: funcs, NumRegs: 4, CallerSaved: 2, Scratch: 3}
}

func TestArithmeticAndControlFlow(t *testing.T) {
	// r0 = sum of 1..10 using a loop
	code := []Instr{
		{Op: Mov, Rd: 0, A: I(0)},
		{Op: Mov, Rd: 1, A: I(1)},
		{Op: Alu, ALU: ir.OpGt, Rd: 2, A: R(1), B: I(10)},
		{Op: Brnz, A: R(2), Target: 7},
		{Op: Alu, ALU: ir.OpAdd, Rd: 0, A: R(0), B: R(1)},
		{Op: Alu, ALU: ir.OpAdd, Rd: 1, A: R(1), B: I(1)},
		{Op: Jmp, Target: 2},
		{Op: Print, A: R(0)},
		{Op: Ret},
	}
	res, st := prog(code, []FuncInfo{{Name: "main", Entry: 0, FrameSize: 0}}).Run(10000)
	if res.Trap != "" || res.Ret != 55 || res.Out != "55\n" {
		t.Fatalf("got %v", res)
	}
	if st.Instrs == 0 || st.Cycles < st.Instrs {
		t.Fatalf("stats look wrong: %+v", st)
	}
}

func TestMemoryBoundsAndTraps(t *testing.T) {
	mk := func(idx int64) *Program {
		return prog([]Instr{
			{Op: StX, Off: 0, A: I(idx), B: I(9), Size: 4},
			{Op: LdX, Rd: 0, Off: 0, A: I(idx), Size: 4},
			{Op: Ret},
		}, []FuncInfo{{Name: "main", Entry: 0, FrameSize: 4}})
	}
	if r, _ := mk(3).Run(100); r.Trap != "" || r.Ret != 9 {
		t.Fatalf("in bounds: %v", r)
	}
	for _, i := range []int64{4, -1, 1 << 40} {
		if r, _ := mk(i).Run(100); r.Trap != ir.TrapOOB {
			t.Errorf("index %d: trap %q", i, r.Trap)
		}
	}
	div := prog([]Instr{{Op: Alu, ALU: ir.OpDiv, Rd: 0, A: I(1), B: I(0)}, {Op: Ret}}, []FuncInfo{{Name: "main"}})
	if r, _ := div.Run(100); r.Trap != ir.TrapDivZero {
		t.Fatalf("got %v", r)
	}
	spin := prog([]Instr{{Op: Jmp, Target: 0}}, []FuncInfo{{Name: "main"}})
	if r, _ := spin.Run(500); r.Trap != ir.TrapFuel {
		t.Fatalf("got %v", r)
	}
	flood := prog([]Instr{{Op: Print, A: I(123456789)}, {Op: Jmp, Target: 0}}, []FuncInfo{{Name: "main"}})
	if r, _ := flood.Run(1 << 40); r.Trap != ir.TrapOutput {
		t.Fatalf("got %v", r.Trap)
	}
	if r, _ := prog(nil, nil).Run(10); !strings.Contains(r.Trap, "main") {
		t.Fatalf("missing main must be reported: %v", r)
	}
}

func TestCallFramesAndArgumentPassing(t *testing.T) {
	// f(a, b) = a*10 + b, with its parameters in frame slots 0 and 1
	code := []Instr{
		// main
		{Op: SetArg, Off: 0, A: I(4)},
		{Op: SetArg, Off: 1, A: I(2)},
		{Op: Call, Target: 1},
		{Op: Ret},
		// f
		{Op: Ld, Rd: 1, Off: 0},
		{Op: Ld, Rd: 0, Off: 1},
		{Op: Alu, ALU: ir.OpMul, Rd: 1, A: R(1), B: I(10)},
		{Op: Alu, ALU: ir.OpAdd, Rd: 0, A: R(0), B: R(1)},
		{Op: Ret},
	}
	p := prog(code, []FuncInfo{{Name: "main", Entry: 0, FrameSize: 0}, {Name: "f", Entry: 4, NParams: 2, FrameSize: 2}})
	if r, st := p.Run(1000); r.Ret != 42 || st.Calls != 1 {
		t.Fatalf("got %v %+v", r, st)
	}
}

// The VM enforces the calling convention: caller-saved registers hold garbage after a call, so code
// that wrongly keeps a value in one across a call computes nonsense (which the fuzzers then catch).
func TestCallerSavedRegistersArePoisonedAfterReturn(t *testing.T) {
	code := []Instr{
		{Op: Mov, Rd: 1, A: I(5)}, // r1 is caller-saved (CallerSaved=2)
		{Op: Mov, Rd: 2, A: I(6)}, // r2 is callee-saved
		{Op: Call, Target: 1},
		{Op: Alu, ALU: ir.OpAdd, Rd: 0, A: R(1), B: R(2)},
		{Op: Ret},
		{Op: Mov, Rd: 0, A: I(0)}, // callee
		{Op: Ret},
	}
	p := prog(code, []FuncInfo{{Name: "main", Entry: 0}, {Name: "g", Entry: 5}})
	r, _ := p.Run(100)
	if r.Ret == 11 {
		t.Fatal("r1 survived the call; the ABI is not being enforced")
	}
	// a callee-saved register is preserved by this (non-clobbering) callee
	code[3] = Instr{Op: Alu, ALU: ir.OpAdd, Rd: 0, A: R(2), B: I(1)}
	if r, _ := prog(code, p.Funcs).Run(100); r.Ret != 7 {
		t.Fatalf("callee-saved r2 lost: %v", r)
	}
}

func TestCallDepthLimit(t *testing.T) {
	p := prog([]Instr{{Op: Call, Target: 0}, {Op: Ret}}, []FuncInfo{{Name: "main", Entry: 0}})
	if r, _ := p.Run(1 << 20); r.Trap != ir.TrapStack {
		t.Fatalf("got %v", r)
	}
}

func TestDisassembly(t *testing.T) {
	p := prog([]Instr{
		{Op: Alu, ALU: ir.OpSelect, Rd: 0, A: R(1), B: I(2), C: I(3), Comment: "pick"},
		{Op: LdX, Rd: 0, Off: 2, A: R(1), Size: 8},
		{Op: Ret},
	}, []FuncInfo{{Name: "main", Entry: 0, FrameSize: 10}})
	d := p.Disasm()
	for _, want := range []string{"main:", "select r0, r1, 2, 3", "; pick", "ldx    r0, [fp+2+r1] <8", "ret", "r0-r1 caller-saved"} {
		if !strings.Contains(d, want) {
			t.Errorf("disassembly lacks %q:\n%s", want, d)
		}
	}
}
