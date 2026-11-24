package sp

import (
	"errors"
	"fmt"
)

// MemWords is the size of the data memory (addresses are masked with MemWords-1).
const MemWords = 256

// Stats are dynamic execution counters under the cost model.
type Stats struct {
	Steps       int // dynamic instructions
	Cycles      int // cost-model cycles
	SpillLoads  int // dynamic spill_ld
	SpillStores int
	Moves       int // dynamic mov
	MemOps      int // dynamic program load/store
}

// Result is the observable behaviour of a run.
type Result struct {
	Ret    int64
	Output []int64
	Mem    [MemWords]int64
	Stats  Stats
}

// ErrStepLimit is returned when a program exceeds the step budget.
var ErrStepLimit = errors.New("step limit exceeded")

// cost is the cycle model: ALU 1, mul 3, div/rem 12, memory 4, spill 4, branch 1-2.
func cost(op Op) int {
	switch op {
	case OpMul:
		return 3
	case OpDiv, OpRem:
		return 12
	case OpLoad, OpStore, OpSpillLd, OpSpillSt:
		return 4
	case OpBr:
		return 2
	}
	return 1
}

func b2i(b bool) int64 {
	if b {
		return 1
	}
	return 0
}

func evalBin(op Op, a, b int64) int64 {
	switch op {
	case OpAdd:
		return a + b
	case OpSub:
		return a - b
	case OpMul:
		return a * b
	case OpDiv:
		if b == 0 || (a == -1<<63 && b == -1) {
			return 0
		}
		return a / b
	case OpRem:
		if b == 0 || (a == -1<<63 && b == -1) {
			return 0
		}
		return a % b
	case OpAnd:
		return a & b
	case OpOr:
		return a | b
	case OpXor:
		return a ^ b
	case OpShl:
		return a << (uint64(b) & 63)
	case OpShr:
		return a >> (uint64(b) & 63)
	case OpLt:
		return b2i(a < b)
	case OpLe:
		return b2i(a <= b)
	case OpEq:
		return b2i(a == b)
	case OpNe:
		return b2i(a != b)
	}
	panic("evalBin: not a binary op")
}

// Run executes f with the given arguments. nregs is the register-file size:
// f.NumRegs for the reference interpretation (unbounded virtual registers),
// or K for allocated code. Reading an unset `arg` yields 0.
func Run(f *Function, args []int64, maxSteps int) (*Result, error) {
	regs := make([]int64, f.NumRegs)
	slots := make([]int64, f.Slots)
	res := &Result{}
	bi, ii := 0, 0
	val := func(o Operand) int64 {
		if o.Imm {
			return o.Val
		}
		return regs[o.Reg]
	}
	for {
		if res.Stats.Steps >= maxSteps {
			return res, ErrStepLimit
		}
		in := &f.Blocks[bi].Instrs[ii]
		res.Stats.Steps++
		res.Stats.Cycles += cost(in.Op)
		ii++
		switch {
		case in.Op.IsBinary():
			regs[in.Dst] = evalBin(in.Op, val(in.Args[0]), val(in.Args[1]))
			continue
		}
		switch in.Op {
		case OpConst:
			regs[in.Dst] = in.Args[0].Val
		case OpMov:
			regs[in.Dst] = val(in.Args[0])
			res.Stats.Moves++
		case OpArg:
			n := int(in.Args[0].Val)
			if n < len(args) {
				regs[in.Dst] = args[n]
			} else {
				regs[in.Dst] = 0
			}
		case OpLoad:
			regs[in.Dst] = res.Mem[val(in.Args[0])&(MemWords-1)]
			res.Stats.MemOps++
		case OpStore:
			res.Mem[val(in.Args[0])&(MemWords-1)] = val(in.Args[1])
			res.Stats.MemOps++
		case OpPrint:
			res.Output = append(res.Output, val(in.Args[0]))
		case OpSpillLd:
			s := int(in.Args[0].Val)
			if s < 0 || s >= len(slots) {
				return res, fmt.Errorf("spill slot %d out of range", s)
			}
			regs[in.Dst] = slots[s]
			res.Stats.SpillLoads++
		case OpSpillSt:
			s := int(in.Args[0].Val)
			if s < 0 || s >= len(slots) {
				return res, fmt.Errorf("spill slot %d out of range", s)
			}
			slots[s] = val(in.Args[1])
			res.Stats.SpillStores++
		case OpBr:
			if val(in.Args[0]) != 0 {
				bi = in.Targets[0]
			} else {
				bi = in.Targets[1]
			}
			ii = 0
		case OpJmp:
			bi, ii = in.Targets[0], 0
		case OpRet:
			res.Ret = val(in.Args[0])
			return res, nil
		default:
			return res, fmt.Errorf("cannot execute %s", in.Op)
		}
	}
}

// Equivalent compares two results' observable behaviour (return, output, memory).
func Equivalent(a, b *Result) error {
	if a.Ret != b.Ret {
		return fmt.Errorf("return value differs: %d vs %d", a.Ret, b.Ret)
	}
	if len(a.Output) != len(b.Output) {
		return fmt.Errorf("print count differs: %d vs %d", len(a.Output), len(b.Output))
	}
	for i := range a.Output {
		if a.Output[i] != b.Output[i] {
			return fmt.Errorf("print #%d differs: %d vs %d", i, a.Output[i], b.Output[i])
		}
	}
	for i := range a.Mem {
		if a.Mem[i] != b.Mem[i] {
			return fmt.Errorf("memory[%d] differs: %d vs %d", i, a.Mem[i], b.Mem[i])
		}
	}
	return nil
}
