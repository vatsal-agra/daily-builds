"""Server-backed browser front end for Cosmac.

Same architecture as this repo's other interactive builds (Gambit's chess
board, Impulse's physics sandbox, Formulate's spreadsheet): the CHIP-8
machine runs *only* on the server, in a single background thread. The
browser holds no emulator logic at all -- it renders whatever state the
server pushes over Server-Sent Events and POSTs back key/control events.
This is what makes the debugger trustworthy: the state you're looking at
in the browser is a direct read of the same `Chip8`/`Debugger` objects
the CLI debugger and the test suite drive.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .assembler import assemble, AssemblerError
from .cpu import Chip8, Quirks
from .debugger import Debugger
from .disassembler import disassemble_range

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(os.path.dirname(HERE), "web")
PROGRAMS_DIR = os.path.join(os.path.dirname(HERE), "programs")

DEFAULT_SPEED_HZ = 700
FRAME_HZ = 60


def _pack_display(display: bytes) -> str:
    """Bit-pack the 2048-pixel display (1 byte/pixel) into hex (256 bytes)."""
    out = bytearray(256)
    for i, pixel in enumerate(display):
        if pixel:
            out[i // 8] |= 0x80 >> (i % 8)
    return out.hex()


class Emulator:
    def __init__(self) -> None:
        self.cpu = Chip8()
        self.dbg = Debugger(self.cpu)
        self.lock = threading.RLock()
        self.running = False
        self.speed_hz = DEFAULT_SPEED_HZ
        self.loaded_program = "(none)"
        self.subscribers: list[queue.Queue] = []
        self.subscribers_lock = threading.Lock()
        self.last_error: "str | None" = None
        self._stop = False
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    # -- loading ------------------------------------------------------

    def load_bytes(self, program: bytes, name: str) -> None:
        with self.lock:
            self.cpu = Chip8(quirks=self.dbg.cpu.quirks)
            self.dbg = Debugger(self.cpu, cycles_per_timer_tick=self.dbg.cycles_per_timer_tick)
            self.cpu.load(program)
            self.loaded_program = name
            self.running = False
            self.last_error = None

    def load_named_program(self, name: str) -> None:
        safe = os.path.basename(name)
        path = os.path.join(PROGRAMS_DIR, safe + ".asm")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no such program '{safe}'")
        with open(path) as f:
            source = f.read()
        self.load_bytes(assemble(source), safe)

    def assemble_and_load(self, source: str) -> None:
        program = assemble(source)  # AssemblerError propagates to caller
        self.load_bytes(program, "(custom)")

    # -- run loop -------------------------------------------------------

    def _run_loop(self) -> None:
        period = 1.0 / FRAME_HZ
        while not self._stop:
            start = time.monotonic()
            with self.lock:
                if self.running and not self.cpu.halted:
                    cycles = max(1, self.speed_hz // FRAME_HZ)
                    for _ in range(cycles):
                        if self.cpu.halted or self.cpu.waiting_for_key is not None:
                            break
                        if self.cpu.pc in self.dbg.breakpoints:
                            self.running = False
                            break
                        try:
                            self.dbg.step()
                        except Exception as exc:  # noqa: BLE001 - surfaced to UI
                            self.running = False
                            self.last_error = str(exc)
                            break
                frame = self._snapshot()
            self._broadcast(frame)
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, period - elapsed))

    def stop(self) -> None:
        self._stop = True

    # -- state export -----------------------------------------------------

    def _snapshot(self) -> dict:
        cpu = self.cpu
        disasm = [
            {"address": d.address, "text": d.mnemonic}
            for d in disassemble_range(
                bytes(cpu.memory),
                max(0x200, cpu.pc - 8),
                min(len(cpu.memory), cpu.pc + 16),
            )
        ]
        return {
            "display": _pack_display(bytes(cpu.display)),
            "v": list(cpu.v),
            "i": cpu.i,
            "pc": cpu.pc,
            "sp": len(cpu.stack),
            "stack": list(cpu.stack),
            "dt": cpu.delay_timer,
            "st": cpu.sound_timer,
            "cycles": cpu.cycles,
            "halted": cpu.halted,
            "waiting_for_key": cpu.waiting_for_key,
            "running": self.running,
            "sound_playing": cpu.sound_playing,
            "loaded_program": self.loaded_program,
            "breakpoints": sorted(self.dbg.breakpoints),
            "disasm": disasm,
            "last_error": self.last_error,
            "speed_hz": self.speed_hz,
            "quirks": {
                "shift_uses_vy": cpu.quirks.shift_uses_vy,
                "load_store_increments_i": cpu.quirks.load_store_increments_i,
                "jump_offset_uses_vx": cpu.quirks.jump_offset_uses_vx,
            },
        }

    def _broadcast(self, frame: dict) -> None:
        payload = json.dumps(frame)
        with self.subscribers_lock:
            subscribers = list(self.subscribers)
        dead = []
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        if dead:
            with self.subscribers_lock:
                for q in dead:
                    if q in self.subscribers:
                        self.subscribers.remove(q)

    # -- actions ------------------------------------------------------

    def key_event(self, key: int, down: bool) -> None:
        with self.lock:
            if down:
                self.cpu.key_down(key)
            else:
                self.cpu.key_up(key)

    def control(self, action: str) -> None:
        with self.lock:
            if action == "run":
                self.running = True
                self.last_error = None
            elif action == "pause":
                self.running = False
            elif action == "step":
                self.running = False
                if not self.cpu.halted:
                    try:
                        self.dbg.step()
                    except Exception as exc:  # noqa: BLE001
                        self.last_error = str(exc)
            elif action == "reset":
                self.cpu.reset()
                self.running = False
                self.last_error = None
            else:
                raise ValueError(f"unknown action '{action}'")

    def set_breakpoint(self, address: int, set_: bool) -> None:
        with self.lock:
            if set_:
                self.dbg.set_breakpoint(address)
            else:
                self.dbg.clear_breakpoint(address)

    def set_speed(self, hz: int) -> None:
        with self.lock:
            self.speed_hz = max(10, min(200_000, hz))

    def set_quirks(self, **kwargs) -> None:
        with self.lock:
            current = self.cpu.quirks
            self.cpu.quirks = Quirks(
                shift_uses_vy=kwargs.get("shift_uses_vy", current.shift_uses_vy),
                load_store_increments_i=kwargs.get(
                    "load_store_increments_i", current.load_store_increments_i
                ),
                jump_offset_uses_vx=kwargs.get(
                    "jump_offset_uses_vx", current.jump_offset_uses_vx
                ),
            )

    def snapshot_state(self) -> dict:
        with self.lock:
            return self.cpu.snapshot()

    def restore_state(self, state: dict) -> None:
        with self.lock:
            self.cpu.restore(state)
            self.running = False


def list_programs() -> list[str]:
    if not os.path.isdir(PROGRAMS_DIR):
        return []
    return sorted(
        f[:-4] for f in os.listdir(PROGRAMS_DIR) if f.endswith(".asm")
    )


def make_handler(emu: Emulator):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Cosmac/1.0"

        def log_message(self, fmt, *args):  # quiet by default
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path, content_type):
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            elif parsed.path == "/programs":
                self._send_json({"programs": list_programs()})
            elif parsed.path == "/program_source":
                qs = parse_qs(parsed.query)
                name = os.path.basename(qs.get("name", [""])[0])
                path = os.path.join(PROGRAMS_DIR, name + ".asm")
                if not os.path.isfile(path):
                    self._send_json({"error": "not found"}, 404)
                    return
                with open(path) as f:
                    self._send_json({"source": f.read()})
            elif parsed.path == "/stream":
                self._handle_stream()
            else:
                self._send_json({"error": "not found"}, 404)

        def _handle_stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q: "queue.Queue[str]" = queue.Queue(maxsize=4)
            with emu.subscribers_lock:
                emu.subscribers.append(q)
            try:
                while True:
                    payload = q.get()
                    chunk = f"data: {payload}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with emu.subscribers_lock:
                    if q in emu.subscribers:
                        emu.subscribers.remove(q)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                body = self._read_json()
                if parsed.path == "/load":
                    emu.load_named_program(body["name"])
                    self._send_json({"ok": True})
                elif parsed.path == "/assemble":
                    emu.assemble_and_load(body["source"])
                    self._send_json({"ok": True})
                elif parsed.path == "/key":
                    emu.key_event(int(body["key"]), bool(body["down"]))
                    self._send_json({"ok": True})
                elif parsed.path == "/control":
                    emu.control(body["action"])
                    self._send_json({"ok": True})
                elif parsed.path == "/breakpoint":
                    emu.set_breakpoint(int(body["address"]), bool(body["set"]))
                    self._send_json({"ok": True})
                elif parsed.path == "/speed":
                    emu.set_speed(int(body["hz"]))
                    self._send_json({"ok": True})
                elif parsed.path == "/quirks":
                    emu.set_quirks(**body)
                    self._send_json({"ok": True})
                elif parsed.path == "/save_state":
                    self._send_json({"state": emu.snapshot_state()})
                elif parsed.path == "/load_state":
                    emu.restore_state(body["state"])
                    self._send_json({"ok": True})
                else:
                    self._send_json({"error": "not found"}, 404)
            except AssemblerError as exc:
                self._send_json({"error": str(exc)}, 400)
            except (KeyError, ValueError, FileNotFoundError) as exc:
                self._send_json({"error": str(exc)}, 400)

    return Handler


def run_server(host: str = "127.0.0.1", port: int = 8880) -> None:
    emu = Emulator()
    server = ThreadingHTTPServer((host, port), make_handler(emu))
    print(f"Cosmac running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        emu.stop()
        server.shutdown()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8880
    run_server(port=port)
