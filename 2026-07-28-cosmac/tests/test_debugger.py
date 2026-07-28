"""Tests for the CLI debugger: breakpoints, stepping, run-until-stop, and
state inspection. `_parse_addr` gets its own tests because a previous
version silently parsed bare-digit addresses as decimal while the help
text (and every address the debugger prints) is hex."""
import io
import unittest
from contextlib import redirect_stdout

from cosmac.cpu import Chip8, Chip8Error, PROGRAM_START
from cosmac.debugger import Debugger, _parse_addr, run_repl


class TestParseAddr(unittest.TestCase):
    def test_bare_digits_are_hex_not_decimal(self):
        self.assertEqual(_parse_addr("200"), 0x200)
        self.assertEqual(_parse_addr("2A4"), 0x2A4)

    def test_0x_prefix_accepted(self):
        self.assertEqual(_parse_addr("0x200"), 0x200)
        self.assertEqual(_parse_addr("0X2ab"), 0x2AB)


class TestBreakpoints(unittest.TestCase):
    def test_set_clear_breakpoints(self):
        cpu = Chip8()
        dbg = Debugger(cpu)
        dbg.set_breakpoint(0x210)
        dbg.set_breakpoint(0x300)
        self.assertEqual(dbg.breakpoints, {0x210, 0x300})
        dbg.clear_breakpoint(0x210)
        self.assertEqual(dbg.breakpoints, {0x300})
        dbg.clear_all_breakpoints()
        self.assertEqual(dbg.breakpoints, set())

    def test_run_until_stop_hits_breakpoint(self):
        # LD V0,1 ; LD V0,2 ; LD V0,3 -- breakpoint on the middle instruction
        cpu = Chip8()
        cpu.load(bytes([0x60, 0x01, 0x60, 0x02, 0x60, 0x03]))
        dbg = Debugger(cpu)
        dbg.set_breakpoint(PROGRAM_START + 2)
        reason = dbg.run_until_stop()
        self.assertEqual(reason, "breakpoint")
        self.assertEqual(cpu.pc, PROGRAM_START + 2)
        self.assertEqual(cpu.v[0], 1)  # only the first instruction ran

    def test_run_until_stop_hits_halt_on_bad_opcode(self):
        cpu = Chip8()
        cpu.load(bytes([0xFF, 0xFF]))
        dbg = Debugger(cpu)
        reason = dbg.run_until_stop()
        self.assertEqual(reason, "halted")
        self.assertTrue(cpu.halted)

    def test_run_until_stop_respects_max_cycles(self):
        cpu = Chip8()
        cpu.load(bytes([0x12, 0x00]))  # JP 0x200 -- infinite loop
        dbg = Debugger(cpu)
        reason = dbg.run_until_stop(max_cycles=50)
        self.assertEqual(reason, "max_cycles")
        self.assertEqual(cpu.cycles, 50)


class TestInspection(unittest.TestCase):
    def test_registers_text_reflects_state(self):
        cpu = Chip8()
        cpu.v[0] = 0x42
        cpu.i = 0x300
        cpu.delay_timer = 7
        dbg = Debugger(cpu)
        text = dbg.registers_text()
        self.assertIn("V0=0x42", text)
        self.assertIn("I=0x300", text)
        self.assertIn("DT=  7", text)

    def test_registers_text_shows_waiting_for_key(self):
        cpu = Chip8()
        cpu.load(bytes([0xF0, 0x0A]))  # LD V0, K
        dbg = Debugger(cpu)
        dbg.step()
        self.assertIn("waiting for keypress", dbg.registers_text())

    def test_disassembly_marks_pc_and_breakpoints(self):
        cpu = Chip8()
        cpu.load(bytes([0x00, 0xE0, 0x00, 0xEE]))
        dbg = Debugger(cpu)
        dbg.set_breakpoint(PROGRAM_START + 2)
        text = dbg.disassembly_around_pc()
        lines = text.splitlines()
        pc_line = next(l for l in lines if f"0x{PROGRAM_START:03X}" in l)
        self.assertTrue(pc_line.startswith("->"))
        bp_line = next(l for l in lines if f"0x{PROGRAM_START + 2:03X}" in l)
        self.assertIn("*", bp_line)

    def test_memory_hex_dump_shows_loaded_bytes(self):
        cpu = Chip8()
        cpu.load(bytes([0xDE, 0xAD, 0xBE, 0xEF]))
        dbg = Debugger(cpu)
        dump = dbg.memory_hex_dump(PROGRAM_START, 4)
        self.assertIn("DE AD BE EF", dump)

    def test_display_ascii_matches_pixel_state(self):
        cpu = Chip8()
        cpu.display[0] = 1
        dbg = Debugger(cpu)
        art = dbg.display_ascii()
        self.assertTrue(art.startswith("#"))


class TestReplDriver(unittest.TestCase):
    def _run(self, commands):
        cpu = Chip8()
        cpu.load(bytes([0x60, 0x2A, 0x00, 0xE0]))  # LD V0, 0x2A ; CLS
        dbg = Debugger(cpu)
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_repl(dbg, commands=commands)
        return dbg, buf.getvalue()

    def test_step_and_regs_commands(self):
        dbg, output = self._run(["step", "regs", "quit"])
        self.assertIn("V0=0x2A", output)
        self.assertEqual(dbg.cpu.cycles, 1)

    def test_break_command_uses_hex_addressing(self):
        dbg, output = self._run(["break 202", "breakpoints", "quit"])
        self.assertEqual(dbg.breakpoints, {0x202})
        self.assertIn("0x202", output)

    def test_unknown_command_reports_error_without_crashing(self):
        dbg, output = self._run(["bogus", "quit"])
        self.assertIn("unknown command", output)

    def test_reset_command(self):
        dbg, output = self._run(["step", "reset", "regs", "quit"])
        self.assertEqual(dbg.cpu.v[0], 0)
        self.assertEqual(dbg.cpu.pc, PROGRAM_START)


if __name__ == "__main__":
    unittest.main()
