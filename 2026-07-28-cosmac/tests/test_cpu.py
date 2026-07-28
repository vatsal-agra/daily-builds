"""Unit tests for every CHIP-8 opcode family, exercised directly through
`Chip8._execute` against hand-computed expected state."""
import unittest

from cosmac.cpu import Chip8, Chip8Error, Quirks, FONT_BASE, PROGRAM_START


def run_one(cpu: Chip8, opcode: int) -> None:
    cpu.memory[cpu.pc] = (opcode >> 8) & 0xFF
    cpu.memory[cpu.pc + 1] = opcode & 0xFF
    cpu.step()


class TestControlFlow(unittest.TestCase):
    def test_jp(self):
        cpu = Chip8()
        run_one(cpu, 0x1300)
        self.assertEqual(cpu.pc, 0x300)

    def test_call_ret(self):
        cpu = Chip8()
        run_one(cpu, 0x2300)
        self.assertEqual(cpu.pc, 0x300)
        self.assertEqual(cpu.stack, [PROGRAM_START + 2])
        run_one(cpu, 0x00EE)
        self.assertEqual(cpu.pc, PROGRAM_START + 2)
        self.assertEqual(cpu.stack, [])

    def test_call_stack_overflow(self):
        cpu = Chip8()
        for _ in range(16):
            run_one(cpu, 0x2300)
            cpu.pc = 0x300  # re-point so each CALL pushes a fresh return addr
        with self.assertRaises(Chip8Error):
            run_one(cpu, 0x2300)

    def test_ret_empty_stack(self):
        cpu = Chip8()
        with self.assertRaises(Chip8Error):
            run_one(cpu, 0x00EE)

    def test_sys_is_noop(self):
        cpu = Chip8()
        run_one(cpu, 0x0123)
        self.assertEqual(cpu.pc, PROGRAM_START + 2)

    def test_cls(self):
        cpu = Chip8()
        cpu.display[5] = 1
        run_one(cpu, 0x00E0)
        self.assertFalse(any(cpu.display))


class TestSkipsAndLoads(unittest.TestCase):
    def test_se_byte_skips_on_equal(self):
        cpu = Chip8()
        cpu.v[0] = 0x42
        run_one(cpu, 0x3042)
        self.assertEqual(cpu.pc, PROGRAM_START + 4)

    def test_se_byte_no_skip_on_unequal(self):
        cpu = Chip8()
        cpu.v[0] = 0x41
        run_one(cpu, 0x3042)
        self.assertEqual(cpu.pc, PROGRAM_START + 2)

    def test_sne_byte(self):
        cpu = Chip8()
        cpu.v[0] = 0x41
        run_one(cpu, 0x4042)
        self.assertEqual(cpu.pc, PROGRAM_START + 4)

    def test_se_registers(self):
        cpu = Chip8()
        cpu.v[0] = cpu.v[1] = 7
        run_one(cpu, 0x5010)
        self.assertEqual(cpu.pc, PROGRAM_START + 4)

    def test_sne_registers(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 7, 8
        run_one(cpu, 0x9010)
        self.assertEqual(cpu.pc, PROGRAM_START + 4)

    def test_ld_byte(self):
        cpu = Chip8()
        run_one(cpu, 0x60AB)
        self.assertEqual(cpu.v[0], 0xAB)

    def test_add_byte_no_flag(self):
        cpu = Chip8()
        cpu.v[0] = 0xFF
        run_one(cpu, 0x7002)  # ADD does NOT set VF, unlike 8XY4
        self.assertEqual(cpu.v[0], 0x01)
        self.assertEqual(cpu.v[0xF], 0)

    def test_ld_i(self):
        cpu = Chip8()
        run_one(cpu, 0xA345)
        self.assertEqual(cpu.i, 0x345)

    def test_jp_v0(self):
        cpu = Chip8()
        cpu.v[0] = 0x10
        run_one(cpu, 0xB300)
        self.assertEqual(cpu.pc, 0x310)

    def test_rnd_masks_with_byte(self):
        cpu = Chip8(seed=1)
        run_one(cpu, 0xC000)  # RND V0, 0x00 -> always 0 regardless of draw
        self.assertEqual(cpu.v[0], 0)
        run_one(cpu, 0xC1FF)
        self.assertTrue(0 <= cpu.v[1] <= 255)


class TestArithmetic(unittest.TestCase):
    def test_or(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 0xF0, 0x0F
        run_one(cpu, 0x8011)
        self.assertEqual(cpu.v[0], 0xFF)

    def test_and(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 0xFF, 0x0F
        run_one(cpu, 0x8012)
        self.assertEqual(cpu.v[0], 0x0F)

    def test_xor(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 0xFF, 0x0F
        run_one(cpu, 0x8013)
        self.assertEqual(cpu.v[0], 0xF0)

    def test_add_with_carry(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 0xFF, 0x02
        run_one(cpu, 0x8014)
        self.assertEqual(cpu.v[0], 0x01)
        self.assertEqual(cpu.v[0xF], 1)

    def test_add_without_carry(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 0x01, 0x02
        run_one(cpu, 0x8014)
        self.assertEqual(cpu.v[0], 0x03)
        self.assertEqual(cpu.v[0xF], 0)

    def test_sub_no_borrow(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 5, 2
        run_one(cpu, 0x8015)
        self.assertEqual(cpu.v[0], 3)
        self.assertEqual(cpu.v[0xF], 1)

    def test_sub_with_borrow(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 2, 5
        run_one(cpu, 0x8015)
        self.assertEqual(cpu.v[0], (2 - 5) & 0xFF)
        self.assertEqual(cpu.v[0xF], 0)

    def test_subn(self):
        cpu = Chip8()
        cpu.v[0], cpu.v[1] = 2, 5
        run_one(cpu, 0x8017)  # Vx = Vy - Vx
        self.assertEqual(cpu.v[0], 3)
        self.assertEqual(cpu.v[0xF], 1)

    def test_shr_legacy_uses_vy(self):
        cpu = Chip8(quirks=Quirks(shift_uses_vy=True))
        cpu.v[0], cpu.v[1] = 0x00, 0x03
        run_one(cpu, 0x8016)
        self.assertEqual(cpu.v[0], 0x01)
        self.assertEqual(cpu.v[0xF], 1)  # LSB of Vy (0x03) was 1

    def test_shr_modern_uses_vx(self):
        cpu = Chip8(quirks=Quirks(shift_uses_vy=False))
        cpu.v[0], cpu.v[1] = 0x03, 0xFF
        run_one(cpu, 0x8016)
        self.assertEqual(cpu.v[0], 0x01)  # shifted its own value, ignoring Vy
        self.assertEqual(cpu.v[0xF], 1)

    def test_shl_legacy_uses_vy(self):
        cpu = Chip8(quirks=Quirks(shift_uses_vy=True))
        cpu.v[0], cpu.v[1] = 0x00, 0x81
        run_one(cpu, 0x801E)
        self.assertEqual(cpu.v[0], 0x02)
        self.assertEqual(cpu.v[0xF], 1)  # MSB of Vy (0x81) was 1


class TestMemoryOps(unittest.TestCase):
    def test_add_i(self):
        cpu = Chip8()
        cpu.i, cpu.v[0] = 0x0FFE, 0x02
        run_one(cpu, 0xF01E)
        self.assertEqual(cpu.i, 0x000)  # wraps at 12 bits
        self.assertEqual(cpu.v[0xF], 1)

    def test_add_i_no_overflow(self):
        cpu = Chip8()
        cpu.i, cpu.v[0] = 0x100, 0x02
        run_one(cpu, 0xF01E)
        self.assertEqual(cpu.i, 0x102)
        self.assertEqual(cpu.v[0xF], 0)

    def test_ld_f_font_address(self):
        cpu = Chip8()
        cpu.v[0] = 0xA
        run_one(cpu, 0xF029)
        self.assertEqual(cpu.i, FONT_BASE + 0xA * 5)

    def test_bcd(self):
        cpu = Chip8()
        cpu.v[0] = 156
        cpu.i = 0x400
        run_one(cpu, 0xF033)
        self.assertEqual(list(cpu.memory[0x400:0x403]), [1, 5, 6])

    def test_bcd_zero(self):
        cpu = Chip8()
        cpu.v[0] = 0
        cpu.i = 0x400
        run_one(cpu, 0xF033)
        self.assertEqual(list(cpu.memory[0x400:0x403]), [0, 0, 0])

    def test_store_load_legacy_increments_i(self):
        cpu = Chip8(quirks=Quirks(load_store_increments_i=True))
        cpu.v[0], cpu.v[1], cpu.v[2] = 1, 2, 3
        cpu.i = 0x400
        run_one(cpu, 0xF255)  # LD [I], V2 -- stores V0..V2
        self.assertEqual(list(cpu.memory[0x400:0x403]), [1, 2, 3])
        self.assertEqual(cpu.i, 0x403)

        cpu2 = Chip8(quirks=Quirks(load_store_increments_i=False))
        cpu2.v[0], cpu2.v[1], cpu2.v[2] = 1, 2, 3
        cpu2.i = 0x400
        run_one(cpu2, 0xF255)
        self.assertEqual(cpu2.i, 0x400)  # modern quirk: I unchanged

    def test_store_load_roundtrip(self):
        cpu = Chip8()
        for r in range(16):
            cpu.v[r] = r * 7 & 0xFF
        cpu.i = 0x500
        run_one(cpu, 0xFF55)
        for r in range(16):
            cpu.v[r] = 0
        cpu.i = 0x500
        run_one(cpu, 0xFF65)
        for r in range(16):
            self.assertEqual(cpu.v[r], r * 7 & 0xFF)


class TestTimersAndKeys(unittest.TestCase):
    def test_delay_timer_read_write(self):
        cpu = Chip8()
        cpu.v[0] = 30
        run_one(cpu, 0xF015)
        self.assertEqual(cpu.delay_timer, 30)
        run_one(cpu, 0xF107)
        self.assertEqual(cpu.v[1], 30)

    def test_timer_ticks_down_at_own_rate(self):
        cpu = Chip8()
        cpu.delay_timer = 3
        cpu.tick_timers()
        cpu.tick_timers()
        self.assertEqual(cpu.delay_timer, 1)
        cpu.tick_timers()
        cpu.tick_timers()
        self.assertEqual(cpu.delay_timer, 0)  # never goes negative

    def test_sound_timer_and_sound_playing(self):
        cpu = Chip8()
        self.assertFalse(cpu.sound_playing)
        cpu.v[0] = 5
        run_one(cpu, 0xF018)
        self.assertTrue(cpu.sound_playing)

    def test_skp_sknp(self):
        cpu = Chip8()
        cpu.v[0] = 0x5
        cpu.keys[0x5] = True
        run_one(cpu, 0xE09E)  # SKP -- pressed, should skip
        self.assertEqual(cpu.pc, PROGRAM_START + 4)

        cpu2 = Chip8()
        cpu2.v[0] = 0x5
        run_one(cpu2, 0xE0A1)  # SKNP -- not pressed, should skip
        self.assertEqual(cpu2.pc, PROGRAM_START + 4)

    def test_fx0a_blocks_until_keypress(self):
        cpu = Chip8()
        run_one(cpu, 0xF00A)
        self.assertEqual(cpu.waiting_for_key, 0)
        for _ in range(5):
            cpu.step()  # step() is a no-op while waiting
        self.assertEqual(cpu.waiting_for_key, 0)
        self.assertEqual(cpu.cycles, 1)  # only the FX0A itself counted
        cpu.key_down(0x7)
        self.assertIsNone(cpu.waiting_for_key)
        self.assertEqual(cpu.v[0], 0x7)
        self.assertEqual(cpu.pc, PROGRAM_START + 2)

    def test_key_out_of_range_rejected(self):
        cpu = Chip8()
        with self.assertRaises(ValueError):
            cpu.key_down(16)


class TestDisplay(unittest.TestCase):
    def test_draw_sets_pixels_and_no_collision(self):
        cpu = Chip8()
        cpu.i = 0x400
        cpu.memory[0x400] = 0xFF
        cpu.v[0], cpu.v[1] = 0, 0
        run_one(cpu, 0xD011)
        self.assertEqual(list(cpu.display[0:8]), [1] * 8)
        self.assertEqual(cpu.v[0xF], 0)

    def test_draw_xor_and_collision_flag(self):
        cpu = Chip8()
        cpu.i = 0x400
        cpu.memory[0x400] = 0xFF
        cpu.v[0], cpu.v[1] = 0, 0
        run_one(cpu, 0xD011)
        run_one(cpu, 0xD011)  # drawing the same sprite again erases it
        self.assertEqual(list(cpu.display[0:8]), [0] * 8)
        self.assertEqual(cpu.v[0xF], 1)  # collision was detected

    def test_draw_wraps_around_screen_edges(self):
        cpu = Chip8()
        cpu.i = 0x400
        cpu.memory[0x400] = 0x80  # single leftmost pixel
        cpu.v[0], cpu.v[1] = 63, 31
        run_one(cpu, 0xD011)
        self.assertEqual(cpu.display[31 * 64 + 63], 1)  # drawn at (63,31), no wrap needed here

        cpu2 = Chip8()
        cpu2.i = 0x400
        cpu2.memory[0x400] = 0xFF  # 8 pixels wide starting at x=60 -> wraps
        cpu2.v[0], cpu2.v[1] = 60, 0
        run_one(cpu2, 0xD011)
        for x in (60, 61, 62, 63, 0, 1, 2, 3):
            self.assertEqual(cpu2.display[x], 1, f"expected pixel set at x={x}")

    def test_draw_position_wraps_via_modulo(self):
        cpu = Chip8()
        cpu.i = 0x400
        cpu.memory[0x400] = 0x80
        cpu.v[0], cpu.v[1] = 64 + 5, 32 + 3  # out-of-range coords wrap via % width/height
        run_one(cpu, 0xD011)
        self.assertEqual(cpu.display[3 * 64 + 5], 1)


class TestErrors(unittest.TestCase):
    def test_unknown_opcode_halts_and_records_error(self):
        cpu = Chip8()
        with self.assertRaises(Chip8Error):
            run_one(cpu, 0xFFFF)  # 0xFF is not a valid FX__ variant
        self.assertTrue(cpu.halted)
        self.assertIsNotNone(cpu.last_error)
        # further steps are inert once halted
        cpu.step()
        self.assertEqual(cpu.cycles, 0)

    def test_load_overrun_raises(self):
        cpu = Chip8()
        with self.assertRaises(Chip8Error):
            cpu.load(bytes(5000))


class TestSnapshotRestore(unittest.TestCase):
    def test_snapshot_restore_roundtrip(self):
        cpu = Chip8(seed=3)
        cpu.load(bytes([0x60, 0x05, 0xA1, 0x00]))
        cpu.step()
        cpu.step()
        cpu.delay_timer = 12
        state = cpu.snapshot()

        cpu2 = Chip8()
        cpu2.restore(state)
        self.assertEqual(cpu2.v[0], cpu.v[0])
        self.assertEqual(cpu2.i, cpu.i)
        self.assertEqual(cpu2.pc, cpu.pc)
        self.assertEqual(cpu2.delay_timer, 12)
        self.assertEqual(bytes(cpu2.memory), bytes(cpu.memory))

    def test_reset_keeps_program_clears_state(self):
        cpu = Chip8()
        cpu.load(bytes([0x60, 0x05]))
        cpu.v[3] = 99
        cpu.step()
        cpu.reset()
        self.assertEqual(cpu.v[0], 0)
        self.assertEqual(cpu.v[3], 0)
        self.assertEqual(cpu.pc, PROGRAM_START)
        self.assertEqual(cpu.memory[PROGRAM_START], 0x60)

    def test_reset_discards_runtime_writes_beyond_the_original_program(self):
        # Regression test: reset() used to copy whatever bytes currently
        # sat in memory[PROGRAM_START:] rather than the bytes originally
        # passed to load(), so any runtime write past the program's own
        # length (store-registers-to-memory, a sprite DMA target, etc.)
        # would survive a reset and get replayed as if it were code.
        program = bytes([0x60, 0x05])  # LD V0, 0x05  (2 bytes)
        cpu = Chip8()
        cpu.load(program)
        # simulate the running program writing far past its own bytes,
        # the way FX55 or self-modifying code would
        scratch_addr = PROGRAM_START + 100
        cpu.memory[scratch_addr] = 0xAA
        cpu.memory[scratch_addr + 1] = 0xBB

        cpu.reset()

        self.assertEqual(bytes(cpu.memory[PROGRAM_START:PROGRAM_START + len(program)]), program)
        self.assertEqual(cpu.memory[scratch_addr], 0)
        self.assertEqual(cpu.memory[scratch_addr + 1], 0)

    def test_reset_before_any_load_is_a_harmless_noop(self):
        cpu = Chip8()
        cpu.v[0] = 5
        cpu.reset()  # never loaded a program -- must not raise
        self.assertEqual(cpu.v[0], 0)
        self.assertEqual(cpu.pc, PROGRAM_START)


if __name__ == "__main__":
    unittest.main()
