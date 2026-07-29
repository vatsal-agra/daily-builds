"""An independent verification oracle for the x86-64 encoder: shell out
to the box's real `objdump` and parse what it says the raw bytes decode
to. objdump shares no code with ember.asm -- if the encoder has a bug
that makes it emit the wrong instruction while still confidently
labeling it correctly in its own internal bookkeeping, this is what
catches it, the same way Graft/Strata/Palimpsest cross-checked their
from-scratch VCS object encodings against the real `git` binary rather
than trusting their own round-trip tests alone.
"""

import re
import subprocess
import tempfile
import os
from dataclasses import dataclass
from typing import List

from .errors import EmberRuntimeError

# objdump's `-D` output is tab-delimited: "  <offset>:\t<space-padded hex
# bytes>\t<mnemonic>" -- the hex-bytes field is padded to a fixed column
# width with trailing spaces (not just one space between byte pairs), so
# the byte group must be "hex digits and spaces" rather than a strict
# "byte, optional single space" repeat.
_LINE_RE = re.compile(r"^\s*([0-9a-f]+):\t([0-9a-f ]+)\t?(.*)$")


@dataclass(frozen=True)
class DisasmInsn:
    offset: int
    raw_bytes: bytes
    text: str  # e.g. "add    rax,rcx" (objdump's Intel-syntax rendering)

    @property
    def mnemonic(self) -> str:
        return self.text.split()[0] if self.text.split() else ""


def objdump_available() -> bool:
    try:
        subprocess.run(["objdump", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def disassemble(code: bytes) -> List[DisasmInsn]:
    """Run the real objdump over raw machine code bytes (no ELF/object
    file framing -- `-b binary -m i386:x86-64`) and parse its Intel-syntax
    output into a list of DisasmInsn."""
    fd, path = tempfile.mkstemp(suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(code)
        proc = subprocess.run(
            ["objdump", "-D", "-b", "binary", "-m", "i386:x86-64", "-M", "intel", path],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise EmberRuntimeError(f"objdump failed: {proc.stderr.strip()}")
        return _parse(proc.stdout)
    finally:
        os.unlink(path)


def _parse(objdump_output: str) -> List[DisasmInsn]:
    insns = []
    pending_offset = None
    pending_bytes = b""
    pending_text = None
    for line in objdump_output.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        offset = int(m.group(1), 16)
        raw = bytes.fromhex(m.group(2).replace(" ", ""))
        text = m.group(3).strip()
        if text:
            # flush any previous instruction whose byte listing wrapped
            # across multiple lines (objdump wraps long encodings, e.g.
            # movabs's 10-byte form, onto a continuation line with no
            # mnemonic column)
            if pending_text is not None:
                insns.append(DisasmInsn(pending_offset, pending_bytes, pending_text))
            pending_offset, pending_bytes, pending_text = offset, raw, text
        else:
            pending_bytes += raw
    if pending_text is not None:
        insns.append(DisasmInsn(pending_offset, pending_bytes, pending_text))
    return insns


def format_listing(code: bytes) -> str:
    """Human-readable `offset: bytes    mnemonic` listing, used by the
    CLI's `disasm` command and the HTML report."""
    lines = []
    for insn in disassemble(code):
        hexbytes = insn.raw_bytes.hex(" ")
        lines.append(f"{insn.offset:6d}:  {hexbytes:<24s} {insn.text}")
    return "\n".join(lines)
