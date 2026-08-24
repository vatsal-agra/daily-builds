"""Sequential 'golden model' simulator: fetch, decode, execute, writeback
one instruction fully before starting the next. No pipelining, no hazards
(there's nothing to hazard against), no branch prediction (the next PC is
just computed). This is the ground-truth reference the pipelined simulator
is checked against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import alu, isa
from .assembler import AssembledProgram
from .memory import Memory, RegisterFile


class SimulatorTrap(Exception):
    """Raised for a real runtime fault (illegal instruction, misaligned
    access, out-of-range memory access) -- distinct from normal ecall halt.
    """


@dataclass
class RetiredInstruction:
    pc: int
    word: int
    mnemonic: str
    text: str = ""


class FunctionalSimulator:
    def __init__(self, program: AssembledProgram, mem_size: int = 1 << 20):
        self.mem = Memory(mem_size)
        self.regs = RegisterFile()
        for i, word in enumerate(program.words):
            self.mem.store_word(program.base_address + 4 * i, word)
        self.pc = program.base_address
        self.program = program
        self.halted = False
        self.instret = 0
        self.trace: List[RetiredInstruction] = []

    def step(self) -> None:
        if self.halted:
            return
        if self.pc % 4 != 0:
            raise SimulatorTrap(f"misaligned PC 0x{self.pc:x}")
        word = self.mem.load_word(self.pc)
        d = isa.decode(word)
        next_pc = self.pc + 4

        if d.mnemonic == "ecall":
            self.halted = True
            self.trace.append(RetiredInstruction(self.pc, word, "ecall"))
            self.instret += 1
            return

        rs1v = self.regs.read(d.rs1) if d.uses_rs1() else 0
        rs2v = self.regs.read(d.rs2) if d.uses_rs2() else 0

        if d.fmt == "R":
            self.regs.write(d.rd, alu.alu_op(d.mnemonic, rs1v, rs2v))
        elif d.mnemonic in isa.I_ALU_TYPE:
            self.regs.write(d.rd, alu.alu_op(d.mnemonic, rs1v, isa.to_u32(d.imm)))
        elif d.mnemonic in isa.LOAD_TYPE:
            addr = isa.to_u32(rs1v + d.imm)
            if d.mnemonic == "lb":
                val = self.mem.load_byte(addr, signed=True)
            elif d.mnemonic == "lbu":
                val = self.mem.load_byte(addr, signed=False)
            elif d.mnemonic == "lh":
                val = self.mem.load_half(addr, signed=True)
            elif d.mnemonic == "lhu":
                val = self.mem.load_half(addr, signed=False)
            else:  # lw
                val = self.mem.load_word(addr)
            self.regs.write(d.rd, isa.to_u32(val))
        elif d.mnemonic in isa.STORE_TYPE:
            addr = isa.to_u32(rs1v + d.imm)
            if d.mnemonic == "sb":
                self.mem.store_byte(addr, rs2v)
            elif d.mnemonic == "sh":
                self.mem.store_half(addr, rs2v)
            else:  # sw
                self.mem.store_word(addr, rs2v)
        elif d.mnemonic in isa.BRANCH_TYPE:
            if alu.branch_taken(d.mnemonic, rs1v, rs2v):
                next_pc = isa.to_u32(self.pc + d.imm)
        elif d.mnemonic == "jal":
            self.regs.write(d.rd, isa.to_u32(self.pc + 4))
            next_pc = isa.to_u32(self.pc + d.imm)
        elif d.mnemonic == "jalr":
            target = isa.to_u32((rs1v + d.imm)) & ~1
            self.regs.write(d.rd, isa.to_u32(self.pc + 4))
            next_pc = target
        elif d.mnemonic == "lui":
            self.regs.write(d.rd, isa.to_u32(d.imm))
        elif d.mnemonic == "auipc":
            self.regs.write(d.rd, isa.to_u32(self.pc + d.imm))
        else:
            raise SimulatorTrap(f"unhandled mnemonic {d.mnemonic!r}")

        text = self.program.text.get((self.pc - self.program.base_address) // 4, d.mnemonic)
        self.trace.append(RetiredInstruction(self.pc, word, d.mnemonic, text))
        self.instret += 1
        self.pc = next_pc

    def run(self, max_steps: int = 2_000_000) -> int:
        steps = 0
        while not self.halted and steps < max_steps:
            self.step()
            steps += 1
        if not self.halted:
            raise SimulatorTrap(f"program did not halt (ecall) within {max_steps} steps")
        return steps

    def state_fingerprint(self) -> tuple:
        """Architectural state used to cross-check against the pipeline
        simulator: register file + full memory image."""
        return (self.regs.snapshot(), bytes(self.mem.data))
