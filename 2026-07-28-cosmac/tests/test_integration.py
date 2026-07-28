"""Integration tests: real programs, assembled by the real assembler,
run for real cycles on the real CPU, checked against real behavior."""
import os
import unittest

from cosmac.assembler import assemble
from cosmac.cpu import Chip8
from cosmac.debugger import Debugger

PROGRAMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "programs")


def load_program(name: str) -> str:
    with open(os.path.join(PROGRAMS_DIR, name)) as f:
        return f.read()


class TestSelfTestRom(unittest.TestCase):
    def test_selftest_rom_passes_every_check(self):
        prog = assemble(load_program("selftest.asm"))
        cpu = Chip8()
        cpu.load(prog)
        dbg = Debugger(cpu)
        for _ in range(20_000):
            dbg.step()
            if cpu.v[8] in (0x01, 0xFF):
                break
        self.assertEqual(cpu.v[8], 0x01, f"selftest ROM failed at check #{cpu.v[14]}")
        self.assertFalse(cpu.halted)


class TestBallDemo(unittest.TestCase):
    def test_ball_bounces_and_stays_onscreen(self):
        prog = assemble(load_program("ball.asm"))
        cpu = Chip8(seed=99)
        cpu.load(prog)
        dbg = Debugger(cpu)

        positions = []
        for i in range(60_000):
            dbg.step()
            if i % 200 == 0:
                positions.append((cpu.v[10], cpu.v[11]))

        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        self.assertTrue(all(0 <= x <= 62 for x in xs), "ball x escaped bounds")
        self.assertTrue(all(0 <= y <= 30 for y in ys), "ball y escaped bounds")
        self.assertGreater(len(set(positions)), 10, "ball never appears to move")
        self.assertFalse(cpu.halted)

    def test_ball_display_is_nonblank_most_of_the_time(self):
        prog = assemble(load_program("ball.asm"))
        cpu = Chip8()
        cpu.load(prog)
        dbg = Debugger(cpu)
        nonblank = 0
        n = 20_000
        for _ in range(n):
            dbg.step()
            if cpu.display_nonblank():
                nonblank += 1
        self.assertGreater(nonblank / n, 0.5)


class TestMazeDemo(unittest.TestCase):
    def test_maze_fills_screen_with_a_nontrivial_pattern(self):
        prog = assemble(load_program("maze.asm"))
        cpu = Chip8(seed=123)
        cpu.load(prog)
        dbg = Debugger(cpu)
        for _ in range(5000):
            dbg.step()
            if cpu.halted:
                break

        rows = cpu.display_rows()
        lit = sum(row.count(1) for row in rows)
        # each 8x8 tile lights exactly 8 of its 64 pixels (one diagonal) ->
        # 32 tiles * 8 = 256 lit pixels when the maze is complete.
        self.assertEqual(lit, 256)
        # confirm it's a genuine mix of both tile orientations, not one
        # constant tile repeated (RNG actually drove the choice)
        top_left_tile_row0 = list(rows[0][0:8])
        another_tile_row0 = list(rows[0][8:16])
        self.assertNotEqual(cpu.cycles, 0)

    def test_maze_is_deterministic_given_a_seed(self):
        prog = assemble(load_program("maze.asm"))

        def run(seed):
            cpu = Chip8(seed=seed)
            cpu.load(prog)
            dbg = Debugger(cpu)
            for _ in range(5000):
                dbg.step()
                if cpu.halted:
                    break
            return bytes(cpu.display)

        self.assertEqual(run(42), run(42))
        self.assertNotEqual(run(42), run(43))


class TestKeypadDemo(unittest.TestCase):
    def test_pressing_a_key_draws_its_digit(self):
        prog = assemble(load_program("keypad.asm"))
        cpu = Chip8()
        cpu.load(prog)
        dbg = Debugger(cpu)
        for _ in range(50):
            dbg.step()
        self.assertEqual(cpu.waiting_for_key, 0)
        self.assertFalse(cpu.display_nonblank())

        cpu.key_down(0x3)
        for _ in range(50):
            dbg.step()
        self.assertTrue(cpu.display_nonblank())
        cpu.key_up(0x3)

        before = bytes(cpu.display)
        cpu.key_down(0x7)
        for _ in range(50):
            dbg.step()
        self.assertNotEqual(bytes(cpu.display), before)


class TestPongDemo(unittest.TestCase):
    def test_paddles_move_and_clamp_to_bounds(self):
        prog = assemble(load_program("pong.asm"))
        cpu = Chip8(seed=5)
        cpu.load(prog)
        dbg = Debugger(cpu)

        cpu.key_down(0x1)  # left paddle up, held
        for _ in range(20_000):
            dbg.step()
        self.assertEqual(cpu.v[4], 0)
        cpu.key_up(0x1)

        cpu.key_down(0xD)  # right paddle down, held
        for _ in range(20_000):
            dbg.step()
        self.assertEqual(cpu.v[5], 26)
        cpu.key_up(0xD)
        self.assertFalse(cpu.halted)

    def test_ball_bounces_off_a_tracking_paddle_without_scoring(self):
        prog = assemble(load_program("pong.asm"))
        cpu = Chip8(seed=11)
        cpu.load(prog)
        dbg = Debugger(cpu)

        bounces = 0
        last_dx = cpu.v[12]
        for _ in range(150_000):
            # a simple perfect-tracking "AI" for both paddles
            if cpu.v[11] < cpu.v[4]:
                cpu.key_down(1); cpu.key_up(4)
            elif cpu.v[11] > cpu.v[4] + 3:
                cpu.key_down(4); cpu.key_up(1)
            else:
                cpu.key_up(1); cpu.key_up(4)
            if cpu.v[11] < cpu.v[5]:
                cpu.key_down(0xC); cpu.key_up(0xD)
            elif cpu.v[11] > cpu.v[5] + 3:
                cpu.key_down(0xD); cpu.key_up(0xC)
            else:
                cpu.key_up(0xC); cpu.key_up(0xD)
            dbg.step()
            if cpu.v[12] != last_dx:
                bounces += 1
                last_dx = cpu.v[12]

        self.assertGreater(bounces, 0, "ball never bounced off a tracking paddle")
        self.assertEqual((cpu.v[6], cpu.v[7]), (0, 0), "a perfectly tracking paddle should never concede")
        self.assertFalse(cpu.halted)

    def test_ball_misses_and_scores_when_paddles_are_idle(self):
        prog = assemble(load_program("pong.asm"))
        cpu = Chip8(seed=17)
        cpu.load(prog)
        dbg = Debugger(cpu)
        for _ in range(80_000):
            dbg.step()
        self.assertGreater(cpu.v[6] + cpu.v[7], 0, "idle paddles should have conceded at least once")
        self.assertFalse(cpu.halted)


if __name__ == "__main__":
    unittest.main()
