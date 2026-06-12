"""Thompson construction: AST → Pike-VM program.

The program is a list of instructions; each instruction is also an NFA state,
so the same structure drives the VM, the DFA builder, and the visualizer.

Instruction ops:
  char(ranges, label)  consume one char in `ranges`, go to pc+1
  split(x, y)          epsilon to x (preferred) and y
  jmp(x)               epsilon to x
  save(slot, label)    epsilon to pc+1, recording input position in `slot`
  assert(kind)         epsilon to pc+1 if assertion holds: ^ $ b B
  match                accept
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple

from . import parser as P
from .lexer import RegexCompileError

MAX_PROGRAM = 20_000


@dataclass
class Inst:
    op: str
    x: int = -1
    y: int = -1
    slot: int = -1
    kind: str = ""
    ranges: Tuple[Tuple[int, int], ...] = ()
    label: str = ""

    def succs(self):
        """Epsilon successors (empty for char/match)."""
        if self.op == "split":
            return (self.x, self.y)
        if self.op == "jmp":
            return (self.x,)
        if self.op in ("save", "assert"):
            return (self.x,)
        return ()


class _Builder:
    def __init__(self):
        self.prog = []

    def emit(self, inst):
        if len(self.prog) >= MAX_PROGRAM:
            raise RegexCompileError(
                f"compiled program exceeds {MAX_PROGRAM} states; "
                "reduce repetition counts")
        self.prog.append(inst)
        return len(self.prog) - 1

    # ---- per-node compilation; each leaves the program "falling through"
    # to the next emitted instruction.

    def compile(self, node):
        if isinstance(node, (P.Lit, P.CharClass, P.Dot)):
            label = _node_label(node)
            self.emit(Inst("char", ranges=node.ranges(), label=label))
        elif isinstance(node, P.Anchor):
            i = self.emit(Inst("assert", kind=node.kind))
            self.prog[i].x = i + 1
        elif isinstance(node, P.Concat):
            for part in node.parts:
                self.compile(part)
        elif isinstance(node, P.Group):
            if node.index is None:
                self.compile(node.child)
            else:
                i = self.emit(Inst("save", slot=2 * node.index,
                                   label=f"({node.index}"))
                self.prog[i].x = i + 1
                self.compile(node.child)
                j = self.emit(Inst("save", slot=2 * node.index + 1,
                                   label=f"){node.index}"))
                self.prog[j].x = j + 1
        elif isinstance(node, P.Alt):
            self._alt(node.branches)
        elif isinstance(node, P.Repeat):
            self._repeat(node)
        else:  # pragma: no cover
            raise RegexCompileError(f"unknown AST node {node!r}")

    def _alt(self, branches):
        jumps = []
        for k, br in enumerate(branches):
            last = k == len(branches) - 1
            if not last:
                sp = self.emit(Inst("split"))
                self.prog[sp].x = sp + 1
            self.compile(br)
            if not last:
                jumps.append(self.emit(Inst("jmp")))
                self.prog[sp].y = len(self.prog)
        end = len(self.prog)
        for j in jumps:
            self.prog[j].x = end

    def _repeat(self, node):
        lo, hi, lazy, child = node.lo, node.hi, node.lazy, node.child
        for _ in range(lo):
            self.compile(child)
        if hi is None:
            # star (or the unbounded tail of {m,})
            sp = self.emit(Inst("split"))
            self.compile(child)
            j = self.emit(Inst("jmp", x=sp))
            end = j + 1
            if lazy:
                self.prog[sp].x, self.prog[sp].y = end, sp + 1
            else:
                self.prog[sp].x, self.prog[sp].y = sp + 1, end
        else:
            # (hi - lo) nested optional copies: a{2,4} = aa(a(a)?)?
            splits = []
            for _ in range(hi - lo):
                sp = self.emit(Inst("split"))
                splits.append(sp)
                self.compile(child)
            end = len(self.prog)
            for sp in splits:
                if lazy:
                    self.prog[sp].x, self.prog[sp].y = end, sp + 1
                else:
                    self.prog[sp].x, self.prog[sp].y = sp + 1, end


def _node_label(node):
    if isinstance(node, P.Lit):
        return _pretty_char(node.ch)
    if isinstance(node, P.Dot):
        return "."
    return node.label


def _pretty_char(ch):
    specials = {"\n": "\\n", "\t": "\\t", "\r": "\\r", "\f": "\\f",
                "\v": "\\v", "\x08": "\\b", "\0": "\\0", " ": "␣"}
    if ch in specials:
        return specials[ch]
    cp = ord(ch)
    if cp < 32 or cp == 127:
        return f"\\x{cp:02x}"
    if 0xD800 <= cp <= 0xDFFF or cp > 0xFFFF and not ch.isprintable():
        return f"U+{cp:04X}"
    return ch


def format_ranges(ranges):
    """Human-readable label for a set of codepoint ranges, e.g. 'a-z 0-9'."""
    if not ranges:
        return "∅"
    if ranges == ((0, 0x10FFFF),):
        return "any"
    parts = []
    for lo, hi in ranges:
        if lo == hi:
            parts.append(_pretty_char(chr(lo)))
        elif hi >= 0x10FFFF:
            parts.append(f"{_pretty_char(chr(lo))}-∞")
        else:
            parts.append(f"{_pretty_char(chr(lo))}-{_pretty_char(chr(hi))}")
    return " ".join(parts)


def compile_pattern(pattern):
    """Compile a pattern string. Returns (program, ngroups)."""
    ast, ngroups = P.parse(pattern)
    b = _Builder()
    i = b.emit(Inst("save", slot=0, label="(0"))
    b.prog[i].x = i + 1
    b.compile(ast)
    j = b.emit(Inst("save", slot=1, label=")0"))
    b.prog[j].x = j + 1
    b.emit(Inst("match"))
    return b.prog, ngroups


def char_in_ranges(cp, ranges):
    """Binary search: is codepoint cp inside disjoint sorted ranges?"""
    lo, hi = 0, len(ranges) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        a, b = ranges[mid]
        if cp < a:
            hi = mid - 1
        elif cp > b:
            lo = mid + 1
        else:
            return True
    return False
