import unittest

from silicon.assembler import assemble
from silicon.functional_sim import FunctionalSimulator, SimulatorTrap
from silicon import isa


def run(src: str) -> FunctionalSimulator:
    sim = FunctionalSimulator(assemble(src))
    sim.run()
    return sim


class TestArithmetic(unittest.TestCase):
    def test_add_sub(self):
        sim = run("li t0, 10\nli t1, 3\nadd t2, t0, t1\nsub t3, t0, t1\necall\n")
        self.assertEqual(sim.regs.read(isa.reg_num("t2")), 13)
        self.assertEqual(sim.regs.read(isa.reg_num("t3")), 7)

    def test_signed_comparison_slt(self):
        sim = run("li t0, -5\nli t1, 3\nslt t2, t0, t1\nslt t3, t1, t0\necall\n")
        self.assertEqual(sim.regs.read(isa.reg_num("t2")), 1)  # -5 < 3
        self.assertEqual(sim.regs.read(isa.reg_num("t3")), 0)  # 3 < -5 is false

    def test_unsigned_comparison_sltu(self):
        # -1 as unsigned is huge, so sltu(t1, t0) should be true (3 < 0xFFFFFFFF)
        sim = run("li t0, -1\nli t1, 3\nsltu t2, t1, t0\necall\n")
        self.assertEqual(sim.regs.read(isa.reg_num("t2")), 1)

    def test_shifts(self):
        sim = run("li t0, -8\nsrli t1, t0, 1\nsrai t2, t0, 1\nslli t3, t0, 2\necall\n")
        # logical shift right of a negative number brings in a 0 (huge unsigned result)
        self.assertEqual(sim.regs.read(isa.reg_num("t1")), (0xFFFFFFF8) >> 1)
        # arithmetic shift right preserves sign: -8 >> 1 == -4
        self.assertEqual(isa.to_s32(sim.regs.read(isa.reg_num("t2"))), -4)
        self.assertEqual(isa.to_s32(sim.regs.read(isa.reg_num("t3"))), -32)

    def test_x0_always_zero(self):
        sim = run("addi x0, x0, 123\necall\n")
        self.assertEqual(sim.regs.read(0), 0)

    def test_overflow_wraps_mod_2_32(self):
        sim = run("li t0, 2147483647\nli t1, 1\nadd t2, t0, t1\necall\n")
        self.assertEqual(isa.to_s32(sim.regs.read(isa.reg_num("t2"))), -2147483648)


class TestMemory(unittest.TestCase):
    def test_word_store_load_round_trip(self):
        sim = run("li t0, -123456\nsw t0, 100(x0)\nlw t1, 100(x0)\necall\n")
        self.assertEqual(isa.to_s32(sim.regs.read(isa.reg_num("t1"))), -123456)

    def test_byte_sign_and_zero_extension(self):
        sim = run("li t0, -1\nsb t0, 0(x0)\nlb t1, 0(x0)\nlbu t2, 0(x0)\necall\n")
        self.assertEqual(isa.to_s32(sim.regs.read(isa.reg_num("t1"))), -1)     # sign-extended 0xFF
        self.assertEqual(sim.regs.read(isa.reg_num("t2")), 255)               # zero-extended

    def test_half_sign_and_zero_extension(self):
        sim = run("li t0, -1\nsh t0, 0(x0)\nlh t1, 0(x0)\nlhu t2, 0(x0)\necall\n")
        self.assertEqual(isa.to_s32(sim.regs.read(isa.reg_num("t1"))), -1)
        self.assertEqual(sim.regs.read(isa.reg_num("t2")), 65535)

    def test_store_only_touches_its_own_width(self):
        # store a full -1 word, then overwrite just the low byte -- the
        # upper 3 bytes must survive untouched
        sim = run("li t0, -1\nsw t0, 0(x0)\nli t1, 0\nsb t1, 0(x0)\nlw t2, 0(x0)\necall\n")
        self.assertEqual(sim.mem.load_word(0), 0xFFFFFF00)


class TestControlFlow(unittest.TestCase):
    def test_branch_taken_and_not_taken(self):
        sim = run("li t0, 5\nli t1, 5\nbeq t0, t1, eq\nli t2, 111\nj end\neq:\nli t2, 222\nend:\necall\n")
        self.assertEqual(sim.regs.read(isa.reg_num("t2")), 222)

    def test_loop_sum(self):
        src = """
        li t0, 0
        li t1, 1
        li t2, 11
        loop:
        beq t1, t2, done
        add t0, t0, t1
        addi t1, t1, 1
        j loop
        done:
        ecall
        """
        sim = run(src)
        self.assertEqual(sim.regs.read(isa.reg_num("t0")), 55)  # 1+2+...+10

    def test_jal_jalr_function_call(self):
        src = """
        li a0, 4
        call double
        j end
        double:
        add a0, a0, a0
        ret
        end:
        ecall
        """
        sim = run(src)
        self.assertEqual(sim.regs.read(isa.reg_num("a0")), 8)

    def test_jalr_clears_lsb(self):
        # jump to an odd target -- jalr must clear bit 0 before jumping
        src = """
        li t0, 13
        jalr ra, t0, 0
        li t1, 999
        ecall
        target_area_nop_pad:
        nop
        nop
        nop
        ecall
        """
        sim = run(src)
        # t1 must NOT have been set to 999: the jump landed at address 12
        # (13 & ~1), skipping over the `li t1, 999` at address 8.
        self.assertEqual(sim.regs.read(isa.reg_num("t1")), 0)

    def test_lui_auipc(self):
        sim = run("lui t0, 1\nauipc t1, 0\necall\n")
        self.assertEqual(sim.regs.read(isa.reg_num("t0")), 1 << 12)
        self.assertEqual(sim.regs.read(isa.reg_num("t1")), 4)  # auipc's own pc


class TestTraps(unittest.TestCase):
    def test_misaligned_pc_traps(self):
        sim = FunctionalSimulator(assemble("nop\necall\n"))
        sim.pc = 1  # force a misaligned fetch (a real jalr could produce this if it didn't clear the LSB)
        with self.assertRaises(SimulatorTrap):
            sim.step()

    def test_does_not_halt_traps(self):
        prog = assemble("loop:\nj loop\n")
        sim = FunctionalSimulator(prog)
        with self.assertRaises(SimulatorTrap):
            sim.run(max_steps=100)


if __name__ == "__main__":
    unittest.main()
