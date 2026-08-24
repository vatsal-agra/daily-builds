import unittest

from silicon.assembler import assemble, AssemblerError
from silicon import isa


class TestAssembler(unittest.TestCase):
    def test_simple_r_type(self):
        prog = assemble("add t0, t1, t2\n")
        self.assertEqual(len(prog.words), 1)
        d = isa.decode(prog.words[0])
        self.assertEqual(d.mnemonic, "add")

    def test_labels_and_branch_offset(self):
        src = "start:\n  addi t0, t0, 1\n  j start\n"
        prog = assemble(src)
        self.assertEqual(prog.labels["start"], 0)
        d = isa.decode(prog.words[1])
        self.assertEqual(d.mnemonic, "jal")
        self.assertEqual(d.imm, -4)  # jump back to address 0 from address 4

    def test_comments_and_blank_lines_ignored(self):
        src = "# a comment\n\n  nop  # trailing comment\n; semicolon comment\n"
        prog = assemble(src)
        self.assertEqual(len(prog.words), 1)

    def test_duplicate_label_raises(self):
        with self.assertRaises(AssemblerError):
            assemble("foo:\n nop\nfoo:\n nop\n")

    def test_unknown_mnemonic_raises_with_line_number(self):
        with self.assertRaises(AssemblerError) as ctx:
            assemble("nop\nbogusinstr t0, t1\n")
        self.assertEqual(ctx.exception.line_no, 2)

    def test_unresolved_label_error_has_line_number(self):
        # regression: this used to lose its line number entirely
        with self.assertRaises(AssemblerError) as ctx:
            assemble("j nosuchlabel\n")
        self.assertEqual(ctx.exception.line_no, 1)

    def test_unknown_register_raises(self):
        with self.assertRaises(AssemblerError):
            assemble("add t0, bogus, t1\n")

    def test_out_of_range_immediate_raises(self):
        with self.assertRaises(AssemblerError):
            assemble("addi t0, t0, 5000\n")

    def test_mem_operand_out_of_range_raises(self):
        with self.assertRaises(AssemblerError):
            assemble("sw t0, 2048(t1)\n")

    # ---- pseudo-instructions ----

    def test_li_small_immediate_is_one_word(self):
        prog = assemble("li t0, 42\n")
        self.assertEqual(len(prog.words), 1)
        d = isa.decode(prog.words[0])
        self.assertEqual((d.mnemonic, d.imm), ("addi", 42))

    def test_li_large_immediate_is_two_words(self):
        prog = assemble("li t0, 123456\n")
        self.assertEqual(len(prog.words), 2)
        d0 = isa.decode(prog.words[0])
        d1 = isa.decode(prog.words[1])
        self.assertEqual(d0.mnemonic, "lui")
        self.assertEqual(d1.mnemonic, "addi")

    def test_li_negative_large_immediate_round_trips(self):
        # exercise via the functional simulator since li's correctness is
        # about the *value ending up in the register*, not the encoding shape
        from silicon.functional_sim import FunctionalSimulator
        for val in (-2147483648, 2147483647, -1000000, 1000000, 0, -1):
            prog = assemble(f"li t0, {val}\nsw t0, 0(x0)\necall\n")
            sim = FunctionalSimulator(prog)
            sim.run()
            self.assertEqual(isa.to_s32(sim.mem.load_word(0)), val, msg=f"li {val}")

    def test_mv_not_neg(self):
        prog = assemble("mv t0, t1\nnot t0, t1\nneg t0, t1\n")
        mns = [isa.decode(w).mnemonic for w in prog.words]
        self.assertEqual(mns, ["addi", "xori", "sub"])

    def test_j_jr_ret_call(self):
        src = "call foo\nj bar\nbar:\nfoo:\njr t0\nret\n"
        prog = assemble(src)
        mns = [isa.decode(w).mnemonic for w in prog.words]
        self.assertEqual(mns, ["jal", "jal", "jalr", "jalr"])
        # `call` uses ra as the link register
        self.assertEqual(isa.decode(prog.words[0]).rd, isa.reg_num("ra"))
        # `ret` is exactly `jalr x0, ra, 0`
        d = isa.decode(prog.words[3])
        self.assertEqual((d.rd, d.rs1, d.imm), (0, isa.reg_num("ra"), 0))

    def test_beqz_bnez(self):
        src = "beqz t0, target\nbnez t0, target\ntarget:\n"
        prog = assemble(src)
        d0, d1 = isa.decode(prog.words[0]), isa.decode(prog.words[1])
        self.assertEqual((d0.mnemonic, d0.rs2), ("beq", 0))
        self.assertEqual((d1.mnemonic, d1.rs2), ("bne", 0))

    def test_mem_operand_syntax(self):
        prog = assemble("lw t0, -4(t1)\nsw t0, 8(t1)\n")
        d0, d1 = isa.decode(prog.words[0]), isa.decode(prog.words[1])
        self.assertEqual((d0.mnemonic, d0.imm, d0.rs1), ("lw", -4, isa.reg_num("t1")))
        self.assertEqual((d1.mnemonic, d1.imm, d1.rs1), ("sw", 8, isa.reg_num("t1")))


if __name__ == "__main__":
    unittest.main()
