"""Assembler tests: known-encoding checks, error handling, and the
assemble -> disassemble -> reassemble round trip for every shipped
program plus a synthetic sweep of every instruction form."""
import glob
import os
import unittest

from cosmac.assembler import assemble, AssemblerError
from cosmac.disassembler import disassemble_range

PROGRAMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "programs")


def reassemble_from_bytes(program: bytes, origin: int = 0x200) -> bytes:
    """disassemble(program) then assemble the result back to bytes."""
    lines = ["; roundtrip"]
    for decoded in disassemble_range(program, 0, len(program)):
        lines.append(f"L{origin + decoded.address:03X}: {decoded.mnemonic}")
    return assemble("\n".join(lines), origin=origin)


class TestKnownEncodings(unittest.TestCase):
    def test_basic_opcodes(self):
        src = """
            CLS
            RET
            JP 0x300
            CALL 0x300
        """
        prog = assemble(src)
        self.assertEqual(prog, bytes([0x00, 0xE0, 0x00, 0xEE, 0x13, 0x00, 0x23, 0x00]))

    def test_registers_and_immediates(self):
        prog = assemble("LD V3, 0x42\nADD V3, 5\nSE V3, VA")
        self.assertEqual(prog, bytes([0x63, 0x42, 0x73, 0x05, 0x53, 0xA0]))

    def test_labels_forward_and_backward(self):
        src = """
        start:
            JP loop
        loop:
            LD V0, 1
            JP start
        """
        prog = assemble(src)
        # start=0x200 (JP loop), loop=0x202 (LD V0,1), then JP start=0x200
        self.assertEqual(prog[0:2], bytes([0x12, 0x02]))
        self.assertEqual(prog[4:6], bytes([0x12, 0x00]))

    def test_db_dw_and_string(self):
        prog = assemble('DB 1, 2, 0xFF\nDW 0x1234\nDB "hi"')
        self.assertEqual(prog, bytes([1, 2, 0xFF, 0x12, 0x34, ord("h"), ord("i")]))

    def test_hex_and_dollar_numbers(self):
        prog = assemble("LD V0, 0x10\nLD V1, $10")
        self.assertEqual(prog, bytes([0x60, 0x10, 0x61, 0x10]))

    def test_comments_and_blank_lines(self):
        prog = assemble("; a comment\n\nCLS  ; trailing comment\n# also a comment\n")
        self.assertEqual(prog, bytes([0x00, 0xE0]))

    def test_case_insensitive_mnemonics_and_registers(self):
        prog = assemble("ld v0, 0x10\ncls")
        self.assertEqual(prog, bytes([0x60, 0x10, 0x00, 0xE0]))

    def test_all_ld_forms(self):
        cases = {
            "LD I, 0x123": bytes([0xA1, 0x23]),
            "LD V0, DT": bytes([0xF0, 0x07]),
            "LD V0, K": bytes([0xF0, 0x0A]),
            "LD DT, V0": bytes([0xF0, 0x15]),
            "LD ST, V0": bytes([0xF0, 0x18]),
            "LD F, V0": bytes([0xF0, 0x29]),
            "LD B, V0": bytes([0xF0, 0x33]),
            "LD [I], V3": bytes([0xF3, 0x55]),
            "LD V3, [I]": bytes([0xF3, 0x65]),
            "LD V0, V1": bytes([0x80, 0x10]),
        }
        for src, expected in cases.items():
            self.assertEqual(assemble(src), expected, src)

    def test_shift_ops_encode_vy_explicitly(self):
        self.assertEqual(assemble("SHR V1, V2"), bytes([0x81, 0x26]))
        self.assertEqual(assemble("SHL V1, V2"), bytes([0x81, 0x2E]))
        self.assertEqual(assemble("SHR V1"), bytes([0x81, 0x06]))  # Vy defaults to 0

    def test_drw(self):
        self.assertEqual(assemble("DRW V1, V2, 5"), bytes([0xD1, 0x25]))


class TestAssemblerErrors(unittest.TestCase):
    def test_unknown_mnemonic(self):
        with self.assertRaises(AssemblerError):
            assemble("NOPE V0, 1")

    def test_bad_register(self):
        with self.assertRaises(AssemblerError):
            assemble("LD VG, 1")

    def test_byte_out_of_range(self):
        with self.assertRaises(AssemblerError):
            assemble("LD V0, 300")

    def test_duplicate_label(self):
        with self.assertRaises(AssemblerError):
            assemble("foo: CLS\nfoo: RET")

    def test_undefined_label(self):
        with self.assertRaises(AssemblerError):
            assemble("JP nowhere")

    def test_error_reports_line_number(self):
        try:
            assemble("CLS\nNOPE")
        except AssemblerError as exc:
            self.assertEqual(exc.line_no, 2)
        else:
            self.fail("expected AssemblerError")


class TestRoundTrip(unittest.TestCase):
    """assemble(source) -> disassemble -> assemble again must reproduce
    byte-identical output, for every real program this repo ships."""

    def test_all_shipped_programs_round_trip(self):
        asm_files = sorted(glob.glob(os.path.join(PROGRAMS_DIR, "*.asm")))
        self.assertGreaterEqual(len(asm_files), 5, "expected at least 5 shipped programs")
        for path in asm_files:
            with open(path) as f:
                source = f.read()
            original = assemble(source)
            reassembled = reassemble_from_bytes(original)
            self.assertEqual(
                original, reassembled,
                f"{os.path.basename(path)}: disassemble -> reassemble mismatch",
            )

    def test_round_trip_over_every_instruction_form(self):
        src = """
        start:
            CLS
            RET
            SYS 0x123
            JP start
            CALL start
            SE V0, 0x42
            SE V0, V1
            SNE V0, 0x42
            SNE V0, V1
            LD V0, 0x42
            ADD V0, 0x42
            LD V0, V1
            OR V0, V1
            AND V0, V1
            XOR V0, V1
            ADD V0, V1
            SUB V0, V1
            SHR V0, V1
            SUBN V0, V1
            SHL V0, V1
            LD I, 0x345
            JP V0, 0x345
            RND V0, 0x42
            DRW V0, V1, 0xA
            SKP V0
            SKNP V0
            LD V0, DT
            LD V0, K
            LD DT, V0
            LD ST, V0
            ADD I, V0
            LD F, V0
            LD B, V0
            LD [I], V0
            LD V0, [I]
        """
        original = assemble(src)
        reassembled = reassemble_from_bytes(original)
        self.assertEqual(original, reassembled)

    def test_round_trip_is_bit_exact_over_data_bytes_too(self):
        # DB bytes that happen to look like arbitrary opcodes must still
        # round-trip byte-for-byte even though the disassembler has no
        # way to know they're data, not code.
        original = bytes([0xFF, 0xFF, 0x00, 0x00, 0x12, 0x34, 0xAB, 0xCD])
        reassembled = reassemble_from_bytes(original)
        self.assertEqual(original, reassembled)


if __name__ == "__main__":
    unittest.main()
