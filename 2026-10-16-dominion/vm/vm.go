// Package vm defines the DVM register machine that Dominion compiles to, and its executor.
package vm

import (
	"fmt"
	"strconv"
	"strings"

	"dominion/ir"
)

// Opcode is a machine opcode.
type Opcode uint8

const (
	Mov    Opcode = iota // Rd = A
	Alu                  // Rd = ALU(A,B[,C])  (ALU is an ir.Op: arithmetic, compare, neg, not, select)
	Ld                   // Rd = frame[Off]
	St                   // frame[Off] = A
	LdX                  // Rd = frame[Off + A], bounds-checked against Size
	StX                  // frame[Off + A] = B, bounds-checked against Size
	Jmp                  // pc = Target
	Brnz                 // if A != 0 { pc = Target }
	Brz                  // if A == 0 { pc = Target }
	SetArg               // outgoing argument Off = A
	Call                 // call function Target
	Ret                  // return (value in r0)
	Print                // print A
	numOpcodes
)

// Operand is a register or an immediate.
type Operand struct {
	Imm bool
	R   int
	V   int64
}

func R(r int) Operand   { return Operand{R: r} }
func I(v int64) Operand { return Operand{Imm: true, V: v} }
func (o Operand) String() string {
	if o.Imm {
		return strconv.FormatInt(o.V, 10)
	}
	return "r" + strconv.Itoa(o.R)
}

// Instr is one machine instruction.
type Instr struct {
	Op      Opcode
	ALU     ir.Op
	Rd      int
	A, B, C Operand
	Off     int
	Size    int64
	Target  int
	Comment string
}

// FuncInfo describes a compiled function.
type FuncInfo struct {
	Name      string
	Entry     int
	NParams   int
	FrameSize int
}

// Program is a linked executable.
type Program struct {
	Code        []Instr
	Funcs       []FuncInfo
	NumRegs     int // allocatable registers r0..NumRegs-1
	CallerSaved int // r0..CallerSaved-1 are clobbered by calls
	Scratch     int // number of scratch registers after the allocatable ones
}

func (p *Program) FuncAt(pc int) *FuncInfo {
	for i := len(p.Funcs) - 1; i >= 0; i-- {
		if p.Funcs[i].Entry <= pc {
			return &p.Funcs[i]
		}
	}
	return nil
}

// Disasm renders a listing.
func (p *Program) Disasm() string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "; DVM program: %d regs (r0-r%d caller-saved, r%d-r%d callee-saved), %d scratch\n",
		p.NumRegs, p.CallerSaved-1, p.CallerSaved, p.NumRegs-1, p.Scratch)
	fi := 0
	for pc, in := range p.Code {
		for fi < len(p.Funcs) && p.Funcs[fi].Entry == pc {
			fmt.Fprintf(&sb, "\n%s:    ; frame=%d params=%d\n", p.Funcs[fi].Name, p.Funcs[fi].FrameSize, p.Funcs[fi].NParams)
			fi++
		}
		fmt.Fprintf(&sb, "%5d  %s\n", pc, in.String())
	}
	return sb.String()
}

func (in Instr) String() string {
	var s string
	switch in.Op {
	case Mov:
		s = fmt.Sprintf("mov    r%d, %s", in.Rd, in.A)
	case Alu:
		switch in.ALU {
		case ir.OpNeg, ir.OpNot:
			s = fmt.Sprintf("%-6s r%d, %s", in.ALU, in.Rd, in.A)
		case ir.OpSelect:
			s = fmt.Sprintf("select r%d, %s, %s, %s", in.Rd, in.A, in.B, in.C)
		default:
			s = fmt.Sprintf("%-6s r%d, %s, %s", in.ALU, in.Rd, in.A, in.B)
		}
	case Ld:
		s = fmt.Sprintf("ld     r%d, [fp+%d]", in.Rd, in.Off)
	case St:
		s = fmt.Sprintf("st     [fp+%d], %s", in.Off, in.A)
	case LdX:
		s = fmt.Sprintf("ldx    r%d, [fp+%d+%s] <%d", in.Rd, in.Off, in.A, in.Size)
	case StX:
		s = fmt.Sprintf("stx    [fp+%d+%s], %s <%d", in.Off, in.A, in.B, in.Size)
	case Jmp:
		s = fmt.Sprintf("jmp    %d", in.Target)
	case Brnz:
		s = fmt.Sprintf("brnz   %s, %d", in.A, in.Target)
	case Brz:
		s = fmt.Sprintf("brz    %s, %d", in.A, in.Target)
	case SetArg:
		s = fmt.Sprintf("setarg %d, %s", in.Off, in.A)
	case Call:
		s = fmt.Sprintf("call   %d", in.Target)
	case Ret:
		s = "ret"
	case Print:
		s = fmt.Sprintf("print  %s", in.A)
	}
	if in.Comment != "" {
		s = fmt.Sprintf("%-34s ; %s", s, in.Comment)
	}
	return s
}

// Stats are dynamic execution counts.
type Stats struct {
	Cycles int64
	Instrs int64
	MemOps int64 // dynamic frame loads/stores (spills, saves, arrays)
	Calls  int64
}

// Cost model in cycles.
func cost(in *Instr) int64 {
	switch in.Op {
	case Alu:
		switch in.ALU {
		case ir.OpMul:
			return 3
		case ir.OpDiv, ir.OpRem:
			return 12
		}
		return 1
	case Ld, St, LdX, StX:
		return 3
	case Call:
		return 5
	case Ret:
		return 3
	}
	return 1
}

const (
	MaxDepth = ir.MaxCallDepth
	poison   = int64(0x5DEADBEEF5DEAD)
)

type frame struct {
	retPC int
	fp    int
	fsize int
}

// Run executes @main.
func (p *Program) Run(maxInstrs int64) (ir.Result, Stats) {
	var st Stats
	var out strings.Builder
	mainIdx := -1
	for i, f := range p.Funcs {
		if f.Name == "main" {
			mainIdx = i
		}
	}
	if mainIdx < 0 {
		return ir.Result{Trap: "no @main"}, st
	}
	nregs := p.NumRegs + p.Scratch
	regs := make([]int64, nregs)
	stack := make([]int64, 0, 1<<12)
	var calls []frame
	fp := 0
	enter := func(fi int) {
		f := p.Funcs[fi]
		need := fp + f.FrameSize
		for len(stack) < need {
			stack = append(stack, 0)
		}
		for i := fp; i < need; i++ {
			stack[i] = 0
		}
	}
	trap := func(msg string) (ir.Result, Stats) {
		return ir.Result{Out: out.String(), Trap: msg, Steps: st.Instrs}, st
	}
	enter(mainIdx)
	pc := p.Funcs[mainIdx].Entry
	curFrame := p.Funcs[mainIdx].FrameSize
	var args [64]int64
	val := func(o Operand) int64 {
		if o.Imm {
			return o.V
		}
		return regs[o.R]
	}
	for {
		in := &p.Code[pc]
		st.Instrs++
		st.Cycles += cost(in)
		if st.Instrs > maxInstrs {
			return trap(ir.TrapFuel)
		}
		pc++
		switch in.Op {
		case Mov:
			regs[in.Rd] = val(in.A)
		case Alu:
			r, ok := ir.Eval(in.ALU, val(in.A), val(in.B), val(in.C))
			if !ok {
				return trap(ir.TrapDivZero)
			}
			regs[in.Rd] = r
		case Ld:
			st.MemOps++
			regs[in.Rd] = stack[fp+in.Off]
		case St:
			st.MemOps++
			stack[fp+in.Off] = val(in.A)
		case LdX:
			st.MemOps++
			i := val(in.A)
			if i < 0 || i >= in.Size {
				return trap(ir.TrapOOB)
			}
			regs[in.Rd] = stack[fp+in.Off+int(i)]
		case StX:
			st.MemOps++
			i := val(in.A)
			if i < 0 || i >= in.Size {
				return trap(ir.TrapOOB)
			}
			stack[fp+in.Off+int(i)] = val(in.B)
		case Jmp:
			pc = in.Target
		case Brnz:
			if val(in.A) != 0 {
				pc = in.Target
				st.Cycles++ // taken-branch penalty
			}
		case Brz:
			if val(in.A) == 0 {
				pc = in.Target
				st.Cycles++
			}
		case SetArg:
			args[in.Off] = val(in.A)
		case Call:
			st.Calls++
			if len(calls)+1 >= MaxDepth {
				return trap(ir.TrapStack)
			}
			calls = append(calls, frame{retPC: pc, fp: fp, fsize: curFrame})
			fp += curFrame
			f := p.Funcs[in.Target]
			enter(in.Target)
			for i := 0; i < f.NParams; i++ {
				stack[fp+i] = args[i]
			}
			curFrame = f.FrameSize
			pc = f.Entry
		case Ret:
			if len(calls) == 0 {
				return ir.Result{Ret: regs[0], Out: out.String(), Steps: st.Instrs}, st
			}
			fr := calls[len(calls)-1]
			calls = calls[:len(calls)-1]
			pc, fp, curFrame = fr.retPC, fr.fp, fr.fsize
			for r := 0; r < p.CallerSaved; r++ { // enforce the ABI: caller-saved registers die at a call
				if r != 0 {
					regs[r] = poison
				}
			}
			for r := p.NumRegs; r < nregs; r++ {
				regs[r] = poison
			}
		case Print:
			out.WriteString(strconv.FormatInt(val(in.A), 10))
			out.WriteByte('\n')
		}
	}
}
