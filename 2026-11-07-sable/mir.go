package sable

import (
	"fmt"
	"strings"
)

// Machine IR: three-address code over virtual registers (before allocation) or
// physical registers (after). It is also the executable form run by the VM.

type MOp uint8

const (
	MLi     MOp = iota // D = imm A
	MMov               // D = A
	MBin               // D = A <alu> B   (B may be an immediate)
	MUn                // D = <alu> A
	MParam             // D = incoming argument Idx
	MArg               // outgoing argument Idx = A
	MCall              // call Callee (clobbers caller-saved registers)
	MGetRet            // D = return value of the last call
	MRet               // return A
	MPrint             // print A
	MJmp               // goto T
	MBr                // if A != 0 goto T else goto F
	MLd                // D = frame slot Slot  (spill reload / callee-save restore)
	MSt                // frame slot Slot = A  (spill store / callee-save save)
	MSetRet            // return value = A (epilogue helper: restores follow)
)

type OK uint8

const (
	ONone OK = iota
	OVReg
	OImm
	OReg // physical register
)

type Opd struct {
	K OK
	V int64
}

func VReg(n int) Opd       { return Opd{OVReg, int64(n)} }
func Imm(n int64) Opd      { return Opd{OImm, n} }
func PReg(n int) Opd       { return Opd{OReg, int64(n)} }
func (o Opd) IsVReg() bool { return o.K == OVReg }

type MInstr struct {
	Op      MOp
	Alu     Op
	D, A, B Opd
	Callee  string
	Idx     int
	Slot    int
	T, F    *MBlock
}

type MBlock struct {
	ID     int
	Instrs []MInstr
	Depth  int // loop nesting depth (for spill costs)
	Succs  []*MBlock
}

type MFunc struct {
	Name       string
	NParams    int
	Blocks     []*MBlock // layout order; Blocks[0] is the entry
	NVRegs     int
	NSlots     int
	SpillSlots int
	// results of allocation
	K          int
	UsedCallee []int
	TempVRegs  map[int]bool // vregs introduced by spill code
}

func (f *MFunc) newVReg() int { f.NVRegs++; return f.NVRegs - 1 }

// uses returns pointers to the operand fields an instruction reads.
func (in *MInstr) uses() []*Opd {
	switch in.Op {
	case MMov, MUn, MArg, MRet, MPrint, MBr, MSt, MSetRet:
		return []*Opd{&in.A}
	case MBin:
		return []*Opd{&in.A, &in.B}
	}
	return nil
}

// def returns the operand written, or nil.
func (in *MInstr) def() *Opd {
	switch in.Op {
	case MLi, MMov, MBin, MUn, MParam, MGetRet, MLd:
		return &in.D
	}
	return nil
}

func (in *MInstr) isTerm() bool { return in.Op == MJmp || in.Op == MBr || in.Op == MRet }

func (o Opd) String() string {
	switch o.K {
	case OVReg:
		return fmt.Sprintf("%%%d", o.V)
	case OImm:
		return fmt.Sprintf("#%d", o.V)
	case OReg:
		return fmt.Sprintf("r%d", o.V)
	}
	return "_"
}

func (b *MBlock) label() string { return fmt.Sprintf(".L%d", b.ID) }

// Format prints one instruction. next is the following block in layout (for fallthrough).
func (in *MInstr) Format(next *MBlock) string {
	switch in.Op {
	case MLi:
		return fmt.Sprintf("li    %s, %s", in.D, in.A)
	case MMov:
		return fmt.Sprintf("mov   %s, %s", in.D, in.A)
	case MBin:
		return fmt.Sprintf("%-5s %s, %s, %s", in.Alu, in.D, in.A, in.B)
	case MUn:
		return fmt.Sprintf("%-5s %s, %s", in.Alu, in.D, in.A)
	case MParam:
		return fmt.Sprintf("param %s, %d", in.D, in.Idx)
	case MArg:
		return fmt.Sprintf("arg   %d, %s", in.Idx, in.A)
	case MCall:
		return fmt.Sprintf("call  %s", in.Callee)
	case MGetRet:
		return fmt.Sprintf("getret %s", in.D)
	case MSetRet:
		return fmt.Sprintf("setret %s", in.A)
	case MRet:
		if in.A.K == ONone {
			return "ret"
		}
		return fmt.Sprintf("ret   %s", in.A)
	case MPrint:
		return fmt.Sprintf("print %s", in.A)
	case MJmp:
		if in.T == next {
			return "; fallthrough " + in.T.label()
		}
		return fmt.Sprintf("jmp   %s", in.T.label())
	case MBr:
		switch {
		case in.F == next:
			return fmt.Sprintf("bnz   %s, %s", in.A, in.T.label())
		case in.T == next:
			return fmt.Sprintf("bz    %s, %s", in.A, in.F.label())
		}
		return fmt.Sprintf("bnz   %s, %s ; jmp %s", in.A, in.T.label(), in.F.label())
	case MLd:
		return fmt.Sprintf("ld    %s, [fp+%d]", in.D, in.Slot)
	case MSt:
		return fmt.Sprintf("st    [fp+%d], %s", in.Slot, in.A)
	}
	return "?"
}

func (f *MFunc) String() string {
	var sb strings.Builder
	fmt.Fprintf(&sb, "%s:   ; %d regs, %d frame slots\n", f.Name, f.K, f.NSlots)
	for i, b := range f.Blocks {
		var next *MBlock
		if i+1 < len(f.Blocks) {
			next = f.Blocks[i+1]
		}
		fmt.Fprintf(&sb, "%s:\n", b.label())
		for j := range b.Instrs {
			s := b.Instrs[j].Format(next)
			fmt.Fprintf(&sb, "    %s\n", s)
		}
	}
	return sb.String()
}

// StaticSize counts emitted instructions (fallthrough jumps are free).
func (f *MFunc) StaticSize() int {
	n := 0
	for i, b := range f.Blocks {
		var next *MBlock
		if i+1 < len(f.Blocks) {
			next = f.Blocks[i+1]
		}
		for j := range b.Instrs {
			in := &b.Instrs[j]
			switch {
			case in.Op == MJmp && in.T == next:
			case in.Op == MBr && in.F != next && in.T != next:
				n += 2
			default:
				n++
			}
		}
	}
	return n
}
