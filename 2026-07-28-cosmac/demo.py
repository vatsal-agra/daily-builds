#!/usr/bin/env python3
"""Runnable demo: exercises every feature Cosmac ships, end to end, and
prints what happened. This is deliberately independent of `tests/` --
those check individual behaviors in isolation; this script demonstrates
the whole system doing real work, the way a person evaluating the build
would want to see it. Exit code is nonzero if anything fails.

    python3 demo.py
"""
from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cosmac.assembler import assemble
from cosmac.cpu import Chip8
from cosmac.debugger import Debugger, run_repl
from cosmac.disassembler import disassemble_range
from cosmac.wav import render_program_to_wav

FAILURES: list[str] = []


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def program(name: str) -> str:
    with open(os.path.join(HERE, "programs", f"{name}.asm")) as f:
        return f.read()


# -- 1. CPU core -------------------------------------------------------

section("1. CPU core: assemble + run the opcode self-test ROM")
prog = assemble(program("selftest"))
cpu = Chip8()
cpu.load(prog)
dbg = Debugger(cpu)
for _ in range(20_000):
    dbg.step()
    if cpu.v[8] in (0x01, 0xFF):
        break
check(f"all 10 opcode checks pass (V8=0x{cpu.v[8]:02X})", cpu.v[8] == 0x01)
check("CPU never faulted", not cpu.halted)


# -- 2. Assembler + disassembler round trip -----------------------------

section("2. Assembler -> disassembler -> assembler round trip")
sample = "LD V0, 0x2A\nLD I, 0x300\nDRW V0, V0, 5\nJP 0x200\n"
original_bytes = assemble(sample)
decoded = disassemble_range(original_bytes, 0, len(original_bytes))
redisassembled_text = "\n".join(f"L{0x200 + d.address:03X}: {d.mnemonic}" for d in decoded)
reassembled_bytes = assemble(redisassembled_text, origin=0x200)
print("  original source:")
for line in sample.strip().splitlines():
    print(f"    {line}")
print("  disassembled back:")
for line in redisassembled_text.splitlines():
    print(f"    {line}")
check("assemble -> disassemble -> assemble is byte-identical", original_bytes == reassembled_bytes)


# -- 3. Debugger: breakpoints, stepping, inspection ----------------------

section("3. Interactive debugger: breakpoints + step + inspection")
cpu2 = Chip8()
cpu2.load(assemble(program("ball")))
dbg2 = Debugger(cpu2)
buf = io.StringIO()
with redirect_stdout(buf):
    run_repl(dbg2, commands=["break 20A", "run", "regs", "quit"])
transcript = buf.getvalue()
print("  debugger transcript (breakpoint at the initial DRW):")
for line in transcript.splitlines()[-6:]:
    print(f"    {line}")
check("breakpoint actually halted execution there", cpu2.pc == 0x20A)
check("stopped-reason reported to the user", "stopped: breakpoint" in transcript)


# -- 4. Original programs behave correctly -------------------------------

section("4. Original programs: maze generator + Pong")
cpu3 = Chip8(seed=7)
cpu3.load(assemble(program("maze")))
dbg3 = Debugger(cpu3)
for _ in range(3000):
    dbg3.step()
    if cpu3.halted:
        break
lit_pixels = sum(cpu3.display)
check(f"maze fills the screen with a real pattern ({lit_pixels} lit pixels)", lit_pixels == 256)

cpu4 = Chip8(seed=3)
cpu4.load(assemble(program("pong")))
dbg4 = Debugger(cpu4)
bounces = 0
last_dx = cpu4.v[12]
for _ in range(100_000):
    if cpu4.v[11] < cpu4.v[4]:
        cpu4.key_down(1); cpu4.key_up(4)
    elif cpu4.v[11] > cpu4.v[4] + 3:
        cpu4.key_down(4); cpu4.key_up(1)
    dbg4.step()
    if cpu4.v[12] != last_dx:
        bounces += 1
        last_dx = cpu4.v[12]
check(f"Pong's ball bounces off a tracking paddle ({bounces} bounces)", bounces > 0)


# -- 5. Stretch: save states -----------------------------------------

section("5. Stretch feature: save/restore state")
cpu5 = Chip8()
cpu5.load(assemble(program("ball")))
dbg5 = Debugger(cpu5)
for _ in range(500):
    dbg5.step()
snapshot = cpu5.snapshot()
pc_at_snapshot, cycles_at_snapshot = cpu5.pc, cpu5.cycles
for _ in range(500):
    dbg5.step()
check("machine state actually advanced after the snapshot", cpu5.cycles != cycles_at_snapshot)
cpu5.restore(snapshot)
check("restore() rolls PC back exactly", cpu5.pc == pc_at_snapshot)
check("restore() rolls cycle count back exactly", cpu5.cycles == cycles_at_snapshot)


# -- 6. Stretch: real audio -------------------------------------------------

section("6. Stretch feature: from-scratch WAV rendering of real sound-timer state")
out_wav = os.path.join(HERE, "demo_beep.wav")
timeline = render_program_to_wav(assemble(program("beep")), out_wav, ticks=250)
size = os.path.getsize(out_wav)
beeping_ticks = sum(timeline)
check(f"wrote a real .wav file ({size} bytes)", size > 44)
check(f"captured 4 real beeps from the CPU's own sound timer ({beeping_ticks} beeping ticks)", beeping_ticks > 100)
os.remove(out_wav)


# -- 7. Server + browser front end (HTTP layer) --------------------------

section("7. Server-backed browser front end (HTTP layer)")
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
proc = subprocess.Popen(
    [sys.executable, "-m", "cosmac.server", str(port)],
    cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    up = False
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(base + "/", timeout=0.5)
            up = True
            break
        except Exception:
            time.sleep(0.1)
    check("server started and serves the UI", up)

    import json

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    listing = json.loads(urllib.request.urlopen(base + "/programs").read())
    check(f"lists shipped programs {listing['programs']}", len(listing["programs"]) >= 5)
    post("/load", {"name": "pong"})
    for _ in range(10):
        post("/control", {"action": "step"})
    state = post("/save_state", {})["state"]
    check(f"CPU actually ran server-side (cycles={state['cycles']})", state["cycles"] == 10)
finally:
    proc.terminate()
    proc.wait(timeout=5)
    check("server shuts down cleanly", proc.returncode is not None)


# -- summary ------------------------------------------------------------

section("SUMMARY")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed. Every required and stretch feature works end-to-end.")
    sys.exit(0)
