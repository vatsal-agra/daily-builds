package sable

import "fmt"

// The register VM executes allocated machine code. It enforces the calling
// convention by *poisoning* every caller-saved register (and both scratch
// registers) when a call returns, and by checking that callee-saved registers
// come back unchanged — so an allocator bug cannot hide behind lucky values.

const poison int64 = 0x5A5A5A5A5A5A5A5A

// VMStats are dynamic counters from one execution.
type VMStats struct {
	Instrs      int64 // executed instructions (fallthrough jumps are free)
	Cycles      int64 // weighted by the cost model below
	SpillLoads  int64 // executed ld
	SpillStores int64 // executed st
	Calls       int64
	Moves       int64
}

// Image is a fully compiled module.
type Image struct {
	Funcs  []*MFunc
	ByName map[string]*MFunc
	Target Target
	Alg    Alg
	Stats  map[string]AllocStats
}

func aluCycles(op Op) int64 {
	switch op {
	case OpMul:
		return 3
	case OpDiv, OpMod:
		return 12
	}
	return 1
}

// RunProgram executes main(). fuel bounds executed instructions.
func RunProgram(p *Image, fuel int64) (Outcome, VMStats) {
	vm := &vm{p: p, fuel: fuel, regs: make([]int64, p.Target.NumPhys())}
	var out Outcome
	func() {
		defer func() {
			if r := recover(); r != nil {
				tp, ok := r.(trapPanic)
				if !ok {
					panic(r)
				}
				out = Outcome{Output: vm.out, Trap: tp.kind}
			}
		}()
		vm.call(p.ByName["main"], nil)
		out = Outcome{Output: vm.out, Ret: vm.ret}
	}()
	out.Steps = vm.st.Instrs
	return out, vm.st
}

type vm struct {
	p     *Image
	regs  []int64
	out   []int64
	ret   int64
	args  []int64 // outgoing arguments being assembled
	fuel  int64
	depth int
	st    VMStats
}

func (v *vm) val(o Opd) int64 {
	if o.K == OImm {
		return o.V
	}
	return v.regs[o.V]
}

func (v *vm) tick(cycles int64) {
	v.st.Instrs++
	v.st.Cycles += cycles
	v.fuel--
	if v.fuel < 0 {
		trap(TrapFuel)
	}
}

func (v *vm) call(f *MFunc, args []int64) {
	v.depth++
	if v.depth > MaxDepth {
		trap(TrapStack)
	}
	t := v.p.Target
	frame := make([]int64, f.NSlots)
	// remember callee-saved registers to verify the convention on return
	saved := append([]int64(nil), v.regs[t.Caller:t.K]...)
	b := f.Blocks[0]
	idx := map[*MBlock]int{}
	for i, blk := range f.Blocks {
		idx[blk] = i
	}
	for {
		var next *MBlock
		if i := idx[b]; i+1 < len(f.Blocks) {
			next = f.Blocks[i+1]
		}
		var goTo *MBlock
		for k := range b.Instrs {
			in := &b.Instrs[k]
			switch in.Op {
			case MLi:
				v.tick(1)
				v.regs[in.D.V] = in.A.V
			case MMov:
				v.tick(1)
				v.st.Moves++
				v.regs[in.D.V] = v.val(in.A)
			case MBin:
				v.tick(aluCycles(in.Alu))
				v.regs[in.D.V] = EvalBin(opSym[in.Alu], v.val(in.A), v.val(in.B))
			case MUn:
				v.tick(1)
				v.regs[in.D.V] = EvalUn(opSym[in.Alu], v.val(in.A))
			case MParam:
				v.tick(1)
				v.regs[in.D.V] = args[in.Idx]
			case MArg:
				v.tick(1)
				for len(v.args) <= in.Idx {
					v.args = append(v.args, 0)
				}
				v.args[in.Idx] = v.val(in.A)
			case MCall:
				v.tick(5)
				v.st.Calls++
				callee := v.p.ByName[in.Callee]
				if callee == nil {
					panic("VM: unknown callee " + in.Callee)
				}
				a := append([]int64(nil), v.args[:callee.NParams]...)
				v.call(callee, a)
				for r := 0; r < t.Caller; r++ {
					v.regs[r] = poison
				}
				v.regs[t.Scratch0()], v.regs[t.Scratch1()] = poison, poison
			case MGetRet:
				v.tick(1)
				v.regs[in.D.V] = v.ret
			case MSetRet:
				v.tick(1)
				v.ret = v.val(in.A)
			case MPrint:
				v.tick(1)
				v.out = append(v.out, v.val(in.A))
			case MLd:
				v.tick(4)
				v.st.SpillLoads++
				v.regs[in.D.V] = frame[in.Slot]
			case MSt:
				v.tick(4)
				v.st.SpillStores++
				frame[in.Slot] = v.val(in.A)
			case MRet:
				v.tick(1)
				if in.A.K != ONone {
					v.ret = v.val(in.A)
				}
				for r := t.Caller; r < t.K; r++ {
					if v.regs[r] != saved[r-t.Caller] {
						panic(fmt.Sprintf("VM: %s returned with callee-saved r%d clobbered", f.Name, r))
					}
				}
				v.depth--
				return
			case MJmp:
				if in.T != next {
					v.tick(1)
				}
				goTo = in.T
			case MBr:
				v.tick(1)
				if v.val(in.A) != 0 {
					goTo = in.T
				} else {
					goTo = in.F
					if in.T != next && in.F != next {
						v.tick(1) // the trailing jmp
					}
				}
			}
		}
		if goTo == nil {
			panic("VM: fell off the end of block in " + f.Name)
		}
		b = goTo
	}
}
