"""Longest-match lexer generated from a Grammar's token table."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .grammar import END, Grammar


class LexError(Exception):
    def __init__(self, msg, line, col):
        self.line, self.col = line, col
        super().__init__(f"{line}:{col}: {msg}")


@dataclass(frozen=True)
class Token:
    type: str
    text: str
    line: int = 0
    col: int = 0
    pos: int = 0

    def __repr__(self):
        return f"Token({self.type}, {self.text!r}, {self.line}:{self.col})"


class Lexer:
    """Tries every pattern at each position and takes the longest match; ties go to
    literals (so keyword ``'if'`` beats an identifier regex), then to declaration order."""

    def __init__(self, grammar: Grammar):
        self.skips = [re.compile(s) for s in grammar.skips]
        self.rules = []  # (priority, type, compiled-or-literal)
        for name, rx in grammar.token_regex.items():
            self.rules.append((1, name, re.compile(rx), None))
        for name, text in grammar.literals.items():
            if name not in grammar.token_regex:
                self.rules.append((0, name, None, text))

    def tokenize(self, text: str) -> List[Token]:
        out: List[Token] = []
        pos, line, col, n = 0, 1, 1, len(text)
        while pos < n:
            best_len, best = 0, None
            for sk in self.skips:
                m = sk.match(text, pos)
                if m and m.end() - pos > best_len:
                    best_len, best = m.end() - pos, None
            skip_len = best_len
            for prio, name, rx, lit in self.rules:
                if lit is not None:
                    ln = len(lit) if text.startswith(lit, pos) else 0
                else:
                    m = rx.match(text, pos)
                    ln = (m.end() - pos) if m else 0
                if ln > best_len or (ln == best_len and ln > 0 and best is not None and prio < best[0]):
                    best_len, best = ln, (prio, name)
            if best_len == 0:
                snippet = text[pos:pos + 10].split("\n")[0]
                raise LexError(f"unexpected character {text[pos]!r} (near {snippet!r})", line, col)
            if best is not None:
                out.append(Token(best[1], text[pos:pos + best_len], line, col, pos))
            chunk = text[pos:pos + best_len]
            nl = chunk.count("\n")
            if nl:
                line += nl; col = len(chunk) - chunk.rfind("\n")
            else:
                col += best_len
            pos += best_len
        out.append(Token(END, "", line, col, n))
        return out
