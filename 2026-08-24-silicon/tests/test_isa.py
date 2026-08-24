import random
import unittest

from silicon import isa


class TestEncodeDecode(unittest.TestCase):
    def test_nop_matches_real_riscv_encoding(self):
        # The real-world RISC-V NOP is `addi x0, x0, 0` = 0x00000013.
        # This is a hard external anchor: if our encoder disagrees with
        # this well-known bit pattern, something is definitely wrong.
        self.assertEqual(isa.NOP_WORD, 0x00000013)

    def test_r_type_round_trip_fuzz(self):
        rng = random.Random(1)
        for mn in isa.R_TYPE:
            for _ in range(30):
                rd, rs1, rs2 = rng.randrange(32), rng.randrange(32), rng.randrange(32)
                d = isa.decode(isa.encode_r(mn, rd, rs1, rs2))
                self.assertEqual((d.mnemonic, d.rd, d.rs1, d.rs2), (mn, rd, rs1, rs2))
                self.assertEqual(d.fmt, "R")

    def test_i_alu_round_trip_fuzz(self):
        rng = random.Random(2)
        for mn in isa.I_ALU_TYPE:
            for _ in range(30):
                rd, rs1 = rng.randrange(32), rng.randrange(32)
                imm = rng.randrange(0, 32) if mn in isa.SHIFT_IMM_OPS else rng.randrange(-2048, 2048)
                d = isa.decode(isa.encode_i_alu(mn, rd, rs1, imm))
                self.assertEqual((d.mnemonic, d.rd, d.rs1, d.imm), (mn, rd, rs1, imm))

    def test_load_store_round_trip_fuzz(self):
        rng = random.Random(3)
        for mn in isa.LOAD_TYPE:
            for _ in range(30):
                rd, rs1, imm = rng.randrange(32), rng.randrange(32), rng.randrange(-2048, 2048)
                d = isa.decode(isa.encode_load(mn, rd, rs1, imm))
                self.assertEqual((d.mnemonic, d.rd, d.rs1, d.imm), (mn, rd, rs1, imm))
        for mn in isa.STORE_TYPE:
            for _ in range(30):
                rs1, rs2, imm = rng.randrange(32), rng.randrange(32), rng.randrange(-2048, 2048)
                d = isa.decode(isa.encode_store(mn, rs1, rs2, imm))
                self.assertEqual((d.mnemonic, d.rs1, d.rs2, d.imm), (mn, rs1, rs2, imm))

    def test_branch_round_trip_fuzz(self):
        rng = random.Random(4)
        for mn in isa.BRANCH_TYPE:
            for _ in range(30):
                rs1, rs2 = rng.randrange(32), rng.randrange(32)
                imm = rng.randrange(-4096, 4096) & ~1
                d = isa.decode(isa.encode_branch(mn, rs1, rs2, imm))
                self.assertEqual((d.mnemonic, d.rs1, d.rs2, d.imm), (mn, rs1, rs2, imm))

    def test_jal_jalr_round_trip_fuzz(self):
        rng = random.Random(5)
        for _ in range(60):
            rd = rng.randrange(32)
            imm = rng.randrange(-(1 << 20), 1 << 20) & ~1
            d = isa.decode(isa.encode_jal(rd, imm))
            self.assertEqual((d.mnemonic, d.rd, d.imm), ("jal", rd, imm))
        for _ in range(60):
            rd, rs1 = rng.randrange(32), rng.randrange(32)
            imm = rng.randrange(-2048, 2048)
            d = isa.decode(isa.encode_jalr(rd, rs1, imm))
            self.assertEqual((d.mnemonic, d.rd, d.rs1, d.imm), ("jalr", rd, rs1, imm))

    def test_lui_auipc_round_trip_fuzz(self):
        rng = random.Random(6)
        for _ in range(60):
            rd = rng.randrange(32)
            imm20 = rng.randrange(0, 1 << 20)
            d = isa.decode(isa.encode_lui(rd, imm20))
            self.assertEqual(d.mnemonic, "lui")
            self.assertEqual(d.rd, rd)
            self.assertEqual(d.imm, isa.to_s32(imm20 << 12))

    def test_ecall(self):
        d = isa.decode(isa.encode_ecall())
        self.assertEqual(d.mnemonic, "ecall")

    def test_illegal_opcode_raises(self):
        with self.assertRaises(ValueError):
            isa.decode(0x00000000)  # opcode 0 is not a valid RV32I opcode

    def test_signed_immediate_boundaries_rejected_correctly(self):
        # regression: an earlier bug accepted 2048..4095 as valid signed
        # 12-bit immediates (should only accept -2048..2047)
        isa.encode_i_alu("addi", 1, 2, 2047)
        isa.encode_i_alu("addi", 1, 2, -2048)
        with self.assertRaises(ValueError):
            isa.encode_i_alu("addi", 1, 2, 2048)
        with self.assertRaises(ValueError):
            isa.encode_i_alu("addi", 1, 2, -2049)

    def test_shamt_is_unsigned_0_to_31(self):
        isa.encode_i_alu("slli", 1, 2, 31)
        isa.encode_i_alu("slli", 1, 2, 0)
        with self.assertRaises(ValueError):
            isa.encode_i_alu("slli", 1, 2, 32)
        with self.assertRaises(ValueError):
            isa.encode_i_alu("slli", 1, 2, -1)

    def test_reg_num_and_name_are_inverses(self):
        for i in range(32):
            self.assertEqual(isa.reg_num(isa.reg_name(i)), i)
            self.assertEqual(isa.reg_num(f"x{i}"), i)

    def test_reg_num_rejects_unknown(self):
        with self.assertRaises(ValueError):
            isa.reg_num("bogus")


class TestSignExtend(unittest.TestCase):
    def test_sign_extend(self):
        self.assertEqual(isa.sign_extend(0b0111, 4), 7)
        self.assertEqual(isa.sign_extend(0b1000, 4), -8)
        self.assertEqual(isa.sign_extend(0xFFF, 12), -1)
        self.assertEqual(isa.sign_extend(0x7FF, 12), 2047)

    def test_to_s32_to_u32_round_trip(self):
        for v in (0, 1, -1, 2**31 - 1, -(2**31), 12345, -98765):
            self.assertEqual(isa.to_s32(isa.to_u32(v)), v)


if __name__ == "__main__":
    unittest.main()
