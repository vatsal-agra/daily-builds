"""Byte-addressable little-endian memory shared by both simulators."""

from __future__ import annotations

from . import isa


class Memory:
    def __init__(self, size_bytes: int = 1 << 20):
        self.size = size_bytes
        self.data = bytearray(size_bytes)

    def _check(self, addr: int, width: int) -> None:
        if addr < 0 or addr + width > self.size:
            raise IndexError(f"memory access out of range: addr=0x{addr:x} width={width} size=0x{self.size:x}")

    def load_byte(self, addr: int, signed: bool) -> int:
        self._check(addr, 1)
        v = self.data[addr]
        return isa.sign_extend(v, 8) if signed else v

    def load_half(self, addr: int, signed: bool) -> int:
        self._check(addr, 2)
        v = self.data[addr] | (self.data[addr + 1] << 8)
        return isa.sign_extend(v, 16) if signed else v

    def load_word(self, addr: int) -> int:
        self._check(addr, 4)
        v = (
            self.data[addr]
            | (self.data[addr + 1] << 8)
            | (self.data[addr + 2] << 16)
            | (self.data[addr + 3] << 24)
        )
        return v

    def store_byte(self, addr: int, value: int) -> None:
        self._check(addr, 1)
        self.data[addr] = value & 0xFF

    def store_half(self, addr: int, value: int) -> None:
        self._check(addr, 2)
        v = value & 0xFFFF
        self.data[addr] = v & 0xFF
        self.data[addr + 1] = (v >> 8) & 0xFF

    def store_word(self, addr: int, value: int) -> None:
        self._check(addr, 4)
        v = value & 0xFFFFFFFF
        self.data[addr] = v & 0xFF
        self.data[addr + 1] = (v >> 8) & 0xFF
        self.data[addr + 2] = (v >> 16) & 0xFF
        self.data[addr + 3] = (v >> 24) & 0xFF

    def load_word_signed_view(self) -> None:  # pragma: no cover - not used
        raise NotImplementedError

    def snapshot(self) -> bytes:
        return bytes(self.data)


class RegisterFile:
    """32 general-purpose registers; x0 is hardwired to zero."""

    def __init__(self):
        self.regs = [0] * 32

    def read(self, idx: int) -> int:
        return 0 if idx == 0 else isa.to_u32(self.regs[idx])

    def write(self, idx: int, value: int) -> None:
        if idx != 0:
            self.regs[idx] = isa.to_u32(value)

    def snapshot(self) -> tuple:
        return tuple(self.regs)
