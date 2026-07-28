"""Render a CHIP-8 program's real sound-timer activity to a real 16-bit
PCM `.wav` file, from scratch -- no `wave` module, no synthesis library.

CHIP-8 sound is binary: "the sound timer is nonzero" means "beep at
whatever fixed tone the interpreter plays," nothing more expressive. This
module runs the actual CPU for a fixed number of 60Hz timer ticks,
records `cpu.sound_playing` at each tick (the *real* emulated state, not
a guess), and synthesizes a square wave everywhere that was true and
silence everywhere it wasn't.
"""
from __future__ import annotations

import struct

from .cpu import Chip8
from .debugger import Debugger

SAMPLE_RATE = 44100
TICK_HZ = 60
TONE_HZ = 440
AMPLITUDE = 9000  # headroom under int16 full scale (32767)


def capture_beep_timeline(dbg: Debugger, ticks: int) -> list[bool]:
    """Run `dbg` for `ticks` 60Hz timer ticks, recording sound state at
    each one. Stops early (returning a shorter list) if the CPU halts."""
    timeline = []
    for _ in range(ticks):
        if dbg.cpu.halted:
            break
        for _ in range(dbg.cycles_per_timer_tick):
            if dbg.cpu.halted:
                break
            dbg.step()
        timeline.append(dbg.cpu.sound_playing)
    return timeline


def synthesize_square_wave(
    beep_timeline: list[bool],
    sample_rate: int = SAMPLE_RATE,
    tick_hz: int = TICK_HZ,
    tone_hz: int = TONE_HZ,
    amplitude: int = AMPLITUDE,
) -> list[int]:
    """Turn a per-tick on/off timeline into signed 16-bit PCM samples."""
    samples_per_tick = sample_rate // tick_hz
    period_samples = sample_rate / tone_hz
    out: list[int] = []
    t = 0
    for active in beep_timeline:
        for _ in range(samples_per_tick):
            if active:
                phase = (t % period_samples) / period_samples
                out.append(amplitude if phase < 0.5 else -amplitude)
            else:
                out.append(0)
            t += 1
    return out


def write_wav(path: str, samples: list[int], sample_rate: int = SAMPLE_RATE) -> None:
    """Hand-write a mono 16-bit PCM `.wav`: the 44-byte RIFF/WAVE header
    (RIFF chunk, fmt subchunk, data subchunk) followed by little-endian
    int16 samples -- no `wave` module."""
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data = struct.pack(f"<{len(samples)}h", *samples)
    data_size = len(data)

    header = b"RIFF"
    header += struct.pack("<I", 36 + data_size)
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<I", 16)                # fmt subchunk size
    header += struct.pack("<H", 1)                  # PCM format
    header += struct.pack("<H", num_channels)
    header += struct.pack("<I", sample_rate)
    header += struct.pack("<I", byte_rate)
    header += struct.pack("<H", block_align)
    header += struct.pack("<H", bits_per_sample)
    header += b"data"
    header += struct.pack("<I", data_size)

    with open(path, "wb") as f:
        f.write(header)
        f.write(data)


def render_program_to_wav(program: bytes, out_path: str, ticks: int = 600) -> list[bool]:
    """Assemble/load-independent entry point: run `program` bytes on a
    fresh Chip8 for `ticks` timer ticks and write the resulting audio to
    `out_path`. Returns the captured beep timeline (useful for tests)."""
    cpu = Chip8()
    cpu.load(program)
    dbg = Debugger(cpu)
    timeline = capture_beep_timeline(dbg, ticks)
    samples = synthesize_square_wave(timeline)
    write_wav(out_path, samples)
    return timeline


def main(argv: "list[str] | None" = None) -> None:
    import sys
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("usage: python -m cosmac.wav <program.asm|program.ch8> <output.wav> [ticks]")
        raise SystemExit(2)

    src_path, out_path = argv[0], argv[1]
    ticks = int(argv[2]) if len(argv) > 2 else 600

    if src_path.endswith(".asm"):
        from .assembler import assemble
        with open(src_path) as f:
            program = assemble(f.read())
    else:
        with open(src_path, "rb") as f:
            program = f.read()

    timeline = render_program_to_wav(program, out_path, ticks)
    beeping_ticks = sum(timeline)
    print(
        f"wrote {out_path}: {len(timeline)/TICK_HZ:.2f}s "
        f"({beeping_ticks/TICK_HZ:.2f}s of that beeping)"
    )


if __name__ == "__main__":
    main()
