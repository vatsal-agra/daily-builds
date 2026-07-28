"""A from-scratch CHIP-8 interpreter core.

Implements the full 35-opcode CHIP-8 instruction set as specified for the
original 1977 RCA COSMAC VIP interpreter: 4KB memory, 16 general-purpose
8-bit registers (V0-VF), a 16-bit index register (I), a 16-bit program
counter, a 16-level call stack, 60Hz delay/sound timers, a 64x32
monochrome XOR-drawn display, and a 16-key hex keypad.

Two historically-real "quirk" behaviors diverged between the original
COSMAC VIP interpreter and later reimplementations (Chip-48/SCHIP, and
most emulators written after ~1990). Both are configurable here via
`Quirks` so the same core can run programs written against either
convention -- see `set_quirks()`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

MEMORY_SIZE = 4096
PROGRAM_START = 0x200
DISPLAY_WIDTH = 64
DISPLAY_HEIGHT = 32
STACK_SIZE = 16
NUM_REGISTERS = 16
NUM_KEYS = 16
FONT_BASE = 0x50
FONT_CHAR_BYTES = 5

# Standard CHIP-8 hex digit font, 5 bytes (8x5 pixels) per glyph.
FONT_SET = bytes([
    0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
    0x20, 0x60, 0x20, 0x20, 0x70,  # 1
    0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
    0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
    0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
    0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
    0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
    0xF0, 0x10, 0x20, 0x40, 0x40,  # 7
    0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
    0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
    0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
    0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
    0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
    0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
    0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
    0xF0, 0x80, 0xF0, 0x80, 0x80,  # F
])


class Chip8Error(Exception):
    """Raised for genuine machine faults (stack over/underflow, bad opcode)."""


@dataclass
class Quirks:
    """Toggle points where real-world CHIP-8 interpreters disagreed.

    shift_uses_vy:
        True (original COSMAC VIP): `8XY6`/`8XYE` set Vx = Vy, THEN shift.
        False (Chip-48/SCHIP and most modern interpreters): Vy is ignored;
        Vx is shifted in place.

    load_store_increments_i:
        True (original COSMAC VIP): `FX55`/`FX65` leave I = I + X + 1
        after the transfer.
        False (Chip-48/SCHIP): I is left unchanged.

    jump_offset_uses_vx:
        True (Chip-48/SCHIP "BXNN"): `BNNN` jumps to NNN + Vx, where X is
        the high nibble of NNN.
        False (original COSMAC VIP "BNNN"): jumps to NNN + V0.
    """

    shift_uses_vy: bool = True
    load_store_increments_i: bool = True
    jump_offset_uses_vx: bool = False


@dataclass
class Chip8:
    quirks: Quirks = field(default_factory=Quirks)
    seed: "int | None" = None

    def __post_init__(self) -> None:
        self.memory = bytearray(MEMORY_SIZE)
        self.memory[FONT_BASE:FONT_BASE + len(FONT_SET)] = FONT_SET
        self.v = [0] * NUM_REGISTERS
        self.i = 0
        self.pc = PROGRAM_START
        self.stack: list[int] = []
        self.delay_timer = 0
        self.sound_timer = 0
        self.display = bytearray(DISPLAY_WIDTH * DISPLAY_HEIGHT)
        self.keys = [False] * NUM_KEYS
        self.waiting_for_key: "int | None" = None
        self.rng = random.Random(self.seed)
        self.cycles = 0
        self.halted = False
        self.last_error: "str | None" = None
        self._draw_happened = False
        # The exact bytes/origin last passed to `load()`, kept so `reset()`
        # can restore the machine to that original program rather than to
        # whatever now happens to sit in memory -- a running program can
        # write anywhere via FX55/DXYN/self-modifying code, so "current
        # memory contents" and "the program that was loaded" are not the
        # same thing once execution has started.
        if not hasattr(self, "_loaded_program"):
            self._loaded_program: "bytes | None" = None
            self._loaded_origin = PROGRAM_START

    # -- program loading ------------------------------------------------

    def load(self, program: bytes, origin: int = PROGRAM_START) -> None:
        if origin + len(program) > MEMORY_SIZE:
            raise Chip8Error(
                f"program of {len(program)} bytes at 0x{origin:03X} "
                f"overruns {MEMORY_SIZE}-byte memory"
            )
        self.memory[origin:origin + len(program)] = program
        self.pc = origin
        self._loaded_program = bytes(program)
        self._loaded_origin = origin

    def reset(self) -> None:
        program, origin = self._loaded_program, self._loaded_origin
        self.__post_init__()
        if program is not None:
            self.memory[origin:origin + len(program)] = program
            self.pc = origin
            self._loaded_program = program
            self._loaded_origin = origin

    # -- input ------------------------------------------------------------

    def key_down(self, key: int) -> None:
        self._check_key(key)
        self.keys[key] = True
        if self.waiting_for_key is not None:
            self.v[self.waiting_for_key] = key
            self.waiting_for_key = None
            self.pc = (self.pc + 2) & 0xFFF

    def key_up(self, key: int) -> None:
        self._check_key(key)
        self.keys[key] = False

    @staticmethod
    def _check_key(key: int) -> None:
        if not 0 <= key < NUM_KEYS:
            raise ValueError(f"key {key} out of range 0..{NUM_KEYS - 1}")

    # -- timers -------------------------------------------------------------

    def tick_timers(self) -> None:
        """Advance the 60Hz delay/sound timers by one tick each."""
        if self.delay_timer > 0:
            self.delay_timer -= 1
        if self.sound_timer > 0:
            self.sound_timer -= 1

    @property
    def sound_playing(self) -> bool:
        return self.sound_timer > 0

    # -- fetch/decode/execute ------------------------------------------------

    def step(self) -> None:
        """Execute exactly one instruction (a no-op while awaiting a key)."""
        if self.halted:
            return
        if self.waiting_for_key is not None:
            return
        if self.pc + 1 >= MEMORY_SIZE:
            raise Chip8Error(f"program counter 0x{self.pc:03X} out of bounds")

        opcode = (self.memory[self.pc] << 8) | self.memory[self.pc + 1]
        self._draw_happened = False
        try:
            self._execute(opcode)
        except Chip8Error as exc:
            self.halted = True
            self.last_error = str(exc)
            raise
        self.cycles += 1

    def _execute(self, opcode: int) -> None:
        nnn = opcode & 0x0FFF
        n = opcode & 0x000F
        x = (opcode & 0x0F00) >> 8
        y = (opcode & 0x00F0) >> 4
        kk = opcode & 0x00FF
        group = (opcode & 0xF000) >> 12

        # Default: advance past this instruction. Jumps/calls/skips
        # override `next_pc` before returning.
        next_pc = (self.pc + 2) & 0xFFF

        if opcode == 0x00E0:                       # CLS
            for i in range(len(self.display)):
                self.display[i] = 0
        elif opcode == 0x00EE:                      # RET
            if not self.stack:
                raise Chip8Error("RET with empty call stack")
            next_pc = self.stack.pop()
        elif group == 0x0:                          # 0NNN SYS addr (ignored)
            pass
        elif group == 0x1:                          # JP addr
            next_pc = nnn
        elif group == 0x2:                          # CALL addr
            if len(self.stack) >= STACK_SIZE:
                raise Chip8Error("CALL with call stack already at 16 levels")
            self.stack.append(next_pc)
            next_pc = nnn
        elif group == 0x3:                          # SE Vx, byte
            if self.v[x] == kk:
                next_pc = (next_pc + 2) & 0xFFF
        elif group == 0x4:                          # SNE Vx, byte
            if self.v[x] != kk:
                next_pc = (next_pc + 2) & 0xFFF
        elif group == 0x5 and n == 0:                # SE Vx, Vy
            if self.v[x] == self.v[y]:
                next_pc = (next_pc + 2) & 0xFFF
        elif group == 0x6:                          # LD Vx, byte
            self.v[x] = kk
        elif group == 0x7:                          # ADD Vx, byte
            self.v[x] = (self.v[x] + kk) & 0xFF
        elif group == 0x8:
            self._execute_8xy(x, y, n)
        elif group == 0x9 and n == 0:                # SNE Vx, Vy
            if self.v[x] != self.v[y]:
                next_pc = (next_pc + 2) & 0xFFF
        elif group == 0xA:                          # LD I, addr
            self.i = nnn
        elif group == 0xB:                          # JP V0, addr
            base = self.v[x] if self.quirks.jump_offset_uses_vx else self.v[0]
            next_pc = (nnn + base) & 0xFFF
        elif group == 0xC:                          # RND Vx, byte
            self.v[x] = self.rng.randint(0, 255) & kk
        elif group == 0xD:                          # DRW Vx, Vy, nibble
            self._draw_sprite(x, y, n)
        elif group == 0xE and kk == 0x9E:            # SKP Vx
            if self.keys[self.v[x] & 0xF]:
                next_pc = (next_pc + 2) & 0xFFF
        elif group == 0xE and kk == 0xA1:            # SKNP Vx
            if not self.keys[self.v[x] & 0xF]:
                next_pc = (next_pc + 2) & 0xFFF
        elif group == 0xF:
            next_pc = self._execute_fx(x, kk, next_pc)
        else:
            raise Chip8Error(f"unknown opcode 0x{opcode:04X} at 0x{self.pc:03X}")

        self.pc = next_pc & 0xFFF

    def _execute_8xy(self, x: int, y: int, n: int) -> None:
        vx, vy = self.v[x], self.v[y]
        if n == 0x0:
            self.v[x] = vy
        elif n == 0x1:
            self.v[x] = vx | vy
        elif n == 0x2:
            self.v[x] = vx & vy
        elif n == 0x3:
            self.v[x] = vx ^ vy
        elif n == 0x4:
            total = vx + vy
            self.v[x] = total & 0xFF
            self.v[0xF] = 1 if total > 0xFF else 0
        elif n == 0x5:
            self.v[x] = (vx - vy) & 0xFF
            self.v[0xF] = 1 if vx >= vy else 0
        elif n == 0x6:
            source = vy if self.quirks.shift_uses_vy else vx
            self.v[x] = (source >> 1) & 0xFF
            self.v[0xF] = source & 0x1
        elif n == 0x7:
            self.v[x] = (vy - vx) & 0xFF
            self.v[0xF] = 1 if vy >= vx else 0
        elif n == 0xE:
            source = vy if self.quirks.shift_uses_vy else vx
            self.v[x] = (source << 1) & 0xFF
            self.v[0xF] = (source >> 7) & 0x1
        else:
            raise Chip8Error(f"unknown 8XY_ opcode variant 0x{n:X}")

    def _execute_fx(self, x: int, kk: int, next_pc: int) -> int:
        if kk == 0x07:                               # LD Vx, DT
            self.v[x] = self.delay_timer
        elif kk == 0x0A:                              # LD Vx, K
            self.waiting_for_key = x
            return self.pc                            # re-execute until keypress
        elif kk == 0x15:                              # LD DT, Vx
            self.delay_timer = self.v[x]
        elif kk == 0x18:                              # LD ST, Vx
            self.sound_timer = self.v[x]
        elif kk == 0x1E:                              # ADD I, Vx
            total = self.i + self.v[x]
            self.v[0xF] = 1 if total > 0xFFF else 0
            self.i = total & 0xFFF
        elif kk == 0x29:                              # LD F, Vx
            self.i = (FONT_BASE + (self.v[x] & 0xF) * FONT_CHAR_BYTES) & 0xFFF
        elif kk == 0x33:                              # LD B, Vx
            value = self.v[x]
            self.memory[self.i] = value // 100
            self.memory[(self.i + 1) & 0xFFF] = (value // 10) % 10
            self.memory[(self.i + 2) & 0xFFF] = value % 10
        elif kk == 0x55:                              # LD [I], Vx
            for offset in range(x + 1):
                self.memory[(self.i + offset) & 0xFFF] = self.v[offset]
            if self.quirks.load_store_increments_i:
                self.i = (self.i + x + 1) & 0xFFF
        elif kk == 0x65:                              # LD Vx, [I]
            for offset in range(x + 1):
                self.v[offset] = self.memory[(self.i + offset) & 0xFFF]
            if self.quirks.load_store_increments_i:
                self.i = (self.i + x + 1) & 0xFFF
        else:
            raise Chip8Error(f"unknown FX__ opcode variant 0x{kk:02X}")
        return next_pc

    def _draw_sprite(self, x: int, y: int, n: int) -> None:
        origin_x = self.v[x] % DISPLAY_WIDTH
        origin_y = self.v[y] % DISPLAY_HEIGHT
        self.v[0xF] = 0
        for row in range(n):
            sprite_byte = self.memory[(self.i + row) & 0xFFF]
            py = (origin_y + row) % DISPLAY_HEIGHT
            for bit in range(8):
                if not (sprite_byte & (0x80 >> bit)):
                    continue
                px = (origin_x + bit) % DISPLAY_WIDTH
                idx = py * DISPLAY_WIDTH + px
                if self.display[idx]:
                    self.v[0xF] = 1
                self.display[idx] ^= 1
        self._draw_happened = True

    # -- introspection --------------------------------------------------

    def display_rows(self) -> list[bytes]:
        """Return the display as a list of DISPLAY_HEIGHT row byte-strings."""
        return [
            bytes(self.display[r * DISPLAY_WIDTH:(r + 1) * DISPLAY_WIDTH])
            for r in range(DISPLAY_HEIGHT)
        ]

    def display_nonblank(self) -> bool:
        return any(self.display)

    def snapshot(self) -> dict:
        return {
            "memory": bytes(self.memory).hex(),
            "v": list(self.v),
            "i": self.i,
            "pc": self.pc,
            "stack": list(self.stack),
            "delay_timer": self.delay_timer,
            "sound_timer": self.sound_timer,
            "display": bytes(self.display).hex(),
            "keys": list(self.keys),
            "waiting_for_key": self.waiting_for_key,
            "cycles": self.cycles,
            "halted": self.halted,
            "quirks": {
                "shift_uses_vy": self.quirks.shift_uses_vy,
                "load_store_increments_i": self.quirks.load_store_increments_i,
                "jump_offset_uses_vx": self.quirks.jump_offset_uses_vx,
            },
        }

    def restore(self, state: dict) -> None:
        self.memory = bytearray.fromhex(state["memory"])
        self.v = list(state["v"])
        self.i = state["i"]
        self.pc = state["pc"]
        self.stack = list(state["stack"])
        self.delay_timer = state["delay_timer"]
        self.sound_timer = state["sound_timer"]
        self.display = bytearray.fromhex(state["display"])
        self.keys = list(state["keys"])
        self.waiting_for_key = state["waiting_for_key"]
        self.cycles = state["cycles"]
        self.halted = state["halted"]
        q = state.get("quirks")
        if q:
            self.quirks = Quirks(**q)
