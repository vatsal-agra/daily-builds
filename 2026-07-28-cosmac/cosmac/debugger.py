"""An interactive debugger around a `Chip8` instance.

`Debugger` is the reusable core (breakpoints, step, run, inspection) used
by both the CLI REPL in this file and the browser front end's server. The
CLI REPL is a thin `cmd`-less loop so it stays easy to drive from tests
(feed it a list of commands) as well as a real terminal.
"""
from __future__ import annotations

import sys

from .cpu import Chip8, Chip8Error
from .disassembler import disassemble_range


class Debugger:
    def __init__(self, cpu: Chip8, cycles_per_timer_tick: int = 9):
        self.cpu = cpu
        self.breakpoints: set[int] = set()
        self.running = False
        # How many `step()` calls happen per 60Hz timer tick when
        # free-running, i.e. the emulated CPU speed. 9 cycles/tick @ 60Hz
        # timers is ~540Hz, a typical "feels right" CHIP-8 speed.
        self.cycles_per_timer_tick = cycles_per_timer_tick
        self._tick_counter = 0

    # -- breakpoints ------------------------------------------------------

    def set_breakpoint(self, address: int) -> None:
        self.breakpoints.add(address & 0xFFF)

    def clear_breakpoint(self, address: int) -> None:
        self.breakpoints.discard(address & 0xFFF)

    def clear_all_breakpoints(self) -> None:
        self.breakpoints.clear()

    # -- execution ----------------------------------------------------------

    def step(self) -> None:
        """Execute exactly one CPU instruction and keep timers in sync."""
        self.cpu.step()
        self._tick_counter += 1
        if self._tick_counter >= self.cycles_per_timer_tick:
            self._tick_counter = 0
            self.cpu.tick_timers()

    def run_until_stop(self, max_cycles: int = 2_000_000) -> str:
        """Step until a breakpoint, a halt, or `max_cycles` is reached.

        Returns a short reason string: "breakpoint", "halted", or
        "max_cycles". Used by both the CLI `run` command and tests that
        need a program to run to a known stopping point.
        """
        for _ in range(max_cycles):
            if self.cpu.halted:
                return "halted"
            if self.cpu.pc in self.breakpoints:
                return "breakpoint"
            try:
                self.step()
            except Chip8Error:
                return "halted"
        return "max_cycles"

    # -- inspection -----------------------------------------------------

    def registers_text(self) -> str:
        cpu = self.cpu
        rows = []
        for i in range(0, 16, 4):
            rows.append(
                "  ".join(f"V{j:X}=0x{cpu.v[j]:02X}" for j in range(i, i + 4))
            )
        rows.append(f"I=0x{cpu.i:03X}  PC=0x{cpu.pc:03X}  SP={len(cpu.stack)}")
        rows.append(f"DT={cpu.delay_timer:3d}  ST={cpu.sound_timer:3d}  cycles={cpu.cycles}")
        if cpu.stack:
            rows.append("stack: " + " ".join(f"0x{a:03X}" for a in cpu.stack))
        if cpu.waiting_for_key is not None:
            rows.append(f"** waiting for keypress into V{cpu.waiting_for_key:X} **")
        return "\n".join(rows)

    def disassembly_around_pc(self, before: int = 4, after: int = 8) -> str:
        cpu = self.cpu
        start = max(0x200, cpu.pc - before * 2)
        end = min(len(cpu.memory), cpu.pc + after * 2)
        lines = []
        for decoded in disassemble_range(bytes(cpu.memory), start, end):
            marker = "-> " if decoded.address == cpu.pc else "   "
            bp = "*" if decoded.address in self.breakpoints else " "
            lines.append(f"{marker}{bp}0x{decoded.address:03X}: {decoded.mnemonic}")
        return "\n".join(lines)

    def memory_hex_dump(self, start: int, length: int = 128) -> str:
        cpu = self.cpu
        lines = []
        for row in range(start, min(start + length, len(cpu.memory)), 16):
            chunk = cpu.memory[row:row + 16]
            hexed = " ".join(f"{b:02X}" for b in chunk)
            lines.append(f"0x{row:03X}: {hexed}")
        return "\n".join(lines)

    def display_ascii(self) -> str:
        rows = self.cpu.display_rows()
        return "\n".join("".join("#" if px else "." for px in row) for row in rows)


HELP_TEXT = """\
Cosmac debugger commands:
  step [n]          execute n instructions (default 1)
  run               run until a breakpoint or halt
  break <addr>      set a breakpoint (hex, e.g. break 200 or break 0x200)
  clear <addr>      clear a breakpoint
  breakpoints       list active breakpoints
  regs              show registers/timers/stack
  disasm            show disassembly around PC
  mem <addr> [len]  hex-dump memory
  display           show the 64x32 display as ASCII art
  reset             reset the machine (keeps loaded program)
  quit              exit the debugger
"""


def _parse_addr(token: str) -> int:
    # Addresses are always hex here, matching every address this debugger
    # ever prints (disassembly, registers, breakpoints all read "0x2A4").
    # The "0x" prefix is optional -- `int(x, 16)` already accepts it -- but
    # a bare digit-only token like "200" must still mean hex 0x200, not
    # decimal 200, or it silently disagrees with the disassembly on screen.
    return int(token.strip(), 16)


def run_repl(dbg: Debugger, commands: "list[str] | None" = None) -> None:
    """Run the interactive REPL. If `commands` is given, run them instead
    of reading from stdin (used by tests and non-interactive drivers)."""
    source = iter(commands) if commands is not None else None

    def next_line() -> "str | None":
        if source is not None:
            return next(source, None)
        try:
            return input("cosmac> ")
        except EOFError:
            return None

    print(HELP_TEXT)
    while True:
        line = next_line()
        if line is None:
            break
        parts = line.strip().split()
        if not parts:
            continue
        cmd, *args = parts
        try:
            if cmd in ("quit", "exit"):
                break
            elif cmd == "step":
                n = int(args[0]) if args else 1
                for _ in range(n):
                    dbg.step()
                print(dbg.disassembly_around_pc(before=1, after=1))
            elif cmd == "run":
                reason = dbg.run_until_stop()
                print(f"stopped: {reason}")
                print(dbg.disassembly_around_pc(before=1, after=1))
            elif cmd == "break":
                addr = _parse_addr(args[0])
                dbg.set_breakpoint(addr)
                print(f"breakpoint set at 0x{addr:03X}")
            elif cmd == "clear":
                dbg.clear_breakpoint(_parse_addr(args[0]))
            elif cmd == "breakpoints":
                print(", ".join(f"0x{a:03X}" for a in sorted(dbg.breakpoints)) or "(none)")
            elif cmd == "regs":
                print(dbg.registers_text())
            elif cmd == "disasm":
                print(dbg.disassembly_around_pc())
            elif cmd == "mem":
                addr = _parse_addr(args[0])
                length = int(args[1]) if len(args) > 1 else 128
                print(dbg.memory_hex_dump(addr, length))
            elif cmd == "display":
                print(dbg.display_ascii())
            elif cmd == "reset":
                dbg.cpu.reset()
                print("reset.")
            elif cmd == "help":
                print(HELP_TEXT)
            else:
                print(f"unknown command '{cmd}' (try 'help')")
        except (Chip8Error, ValueError, IndexError) as exc:
            print(f"error: {exc}")


def main(argv: "list[str] | None" = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m cosmac.debugger <program.ch8|program.asm>")
        raise SystemExit(2)

    path = argv[0]
    cpu = Chip8()
    if path.endswith(".asm"):
        from .assembler import assemble
        with open(path) as f:
            program = assemble(f.read())
    else:
        with open(path, "rb") as f:
            program = f.read()
    cpu.load(program)
    dbg = Debugger(cpu)
    run_repl(dbg)


if __name__ == "__main__":
    main()
