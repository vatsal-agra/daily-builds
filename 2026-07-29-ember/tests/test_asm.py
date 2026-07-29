import unittest
from ember.asm import (
    Assembler, RAX, RCX, RDX, R8, R9, R10, R11, RBP,
    CC_L, CC_E,
)
from ember.disasm import disassemble, objdump_available


@unittest.skipUnless(objdump_available(), "objdump not available on this system")
class TestAsmAgainstObjdump(unittest.TestCase):
    """Every instruction the encoder can emit, independently re-decoded by
    the box's real objdump -- a tool that shares no code with ember.asm,
    so this catches encoding bugs a self-consistency check alone can't."""

    def _mnemonics(self, asm: Assembler):
        asm.resolve()
        return [(i.mnemonic, i.text) for i in disassemble(bytes(asm.buf))]

    def test_movabs_and_arithmetic(self):
        a = Assembler()
        a.movabs(RAX, 42)
        a.movabs(RCX, 7)
        a.add_rr(RAX, RCX)
        a.sub_rr(RAX, RCX)
        a.imul_rr(RAX, RCX)
        a.ret()
        mnems = [m for m, _ in self._mnemonics(a)]
        self.assertEqual(mnems, ["movabs", "movabs", "add", "sub", "imul", "ret"])

    def test_high_registers_r8_r9(self):
        a = Assembler()
        a.movabs(R8, 100)
        a.movabs(R9, 5)
        a.add_rr(R8, R9)
        a.push(R8)
        a.pop(R9)
        a.ret()
        texts = [t for _, t in self._mnemonics(a)]
        self.assertTrue(any("r8" in t for t in texts))
        self.assertTrue(any("r9" in t for t in texts))

    def test_comparison_and_setcc(self):
        a = Assembler()
        a.movabs(RAX, 1)
        a.movabs(RCX, 2)
        a.cmp_rr(RAX, RCX)
        a.setcc(CC_L)
        a.movzx_al(RAX)
        a.ret()
        mnems = [m for m, _ in self._mnemonics(a)]
        self.assertIn("cmp", mnems)
        self.assertIn("setl", mnems)
        self.assertIn("movzx", mnems)

    def test_division_sequence(self):
        a = Assembler()
        a.movabs(RAX, 17)
        a.movabs(RCX, 5)
        a.cqo()
        a.idiv_r(RCX)
        a.ret()
        mnems = [m for m, _ in self._mnemonics(a)]
        self.assertIn("cqo", mnems)
        self.assertIn("idiv", mnems)

    def test_stack_slot_load_store(self):
        a = Assembler()
        a.store_slot(-8, RAX)
        a.load_slot(RDX, -8)
        a.ret()
        texts = [t for _, t in self._mnemonics(a)]
        self.assertTrue(any("rbp" in t and "0x8" in t for t in texts))

    def test_forward_jump_resolves_to_correct_target(self):
        a = Assembler()
        a.jmp("end")
        a.movabs(RAX, 999)  # should be skipped
        a.define_label("end")
        a.movabs(RAX, 1)
        a.ret()
        a.resolve()
        insns = disassemble(bytes(a.buf))
        jmp_insn = insns[0]
        # objdump prints the absolute target address for a rel32 jmp
        target_hex = jmp_insn.text.split()[-1]
        target = int(target_hex, 16)
        self.assertEqual(target, a.labels["end"])

    def test_backward_jump_for_a_loop(self):
        a = Assembler()
        a.define_label("top")
        a.movabs(RCX, 1)
        a.jmp("top")
        a.ret()
        mnems = [m for m, _ in self._mnemonics(a)]
        self.assertIn("jmp", mnems)

    def test_call_to_forward_label(self):
        a = Assembler()
        a.call("later")
        a.ret()
        a.define_label("later")
        a.movabs(RAX, 1)
        a.ret()
        a.resolve()
        insns = disassemble(bytes(a.buf))
        self.assertEqual(insns[0].mnemonic, "call")

    def test_error_cell_store_via_pointer(self):
        a = Assembler()
        a.movabs(R11, 0x1000)
        a.store_slot_abs_ptr(R11, 1)
        a.ret()
        mnems = [m for m, _ in self._mnemonics(a)]
        self.assertEqual(mnems, ["movabs", "mov", "ret"])


if __name__ == "__main__":
    unittest.main()
