"""RegexLab: a from-scratch regex engine (parser → NFA → Pike VM → DFA)
with an interactive visualizer.  Public API mirrors the stdlib `re` module
on the supported subset (ASCII class semantics, no backreferences)."""

from .lexer import RegexError, RegexSyntaxError, RegexCompileError
from .nfa import compile_pattern
from .vm import Match, run

__all__ = ["compile", "Pattern", "Match",
           "RegexError", "RegexSyntaxError", "RegexCompileError"]


class Pattern:
    def __init__(self, pattern):
        self.pattern = pattern
        self.prog, self.ngroups = compile_pattern(pattern)
        self._nslots = 2 * (self.ngroups + 1)
        self._dfa = None

    # ---- NFA engine -------------------------------------------------
    def match(self, text, pos=0):
        return self._run(text, pos, "match")

    def fullmatch(self, text, pos=0):
        return self._run(text, pos, "fullmatch")

    def search(self, text, pos=0):
        return self._run(text, pos, "search")

    def _run(self, text, pos, mode, observer=None, ban_empty_at=None):
        saves = run(self.prog, self._nslots, text, pos, mode, observer,
                    ban_empty_at)
        return None if saves is None else Match(self, text, saves)

    def finditer(self, text):
        """Non-overlapping matches, left to right.  Implements re's
        must-advance rule: after an empty match at p, the next match may
        not be empty at p again (but may be empty further right)."""
        pos = 0
        ban = None
        while pos <= len(text):
            m = self._run(text, pos, "search", ban_empty_at=ban)
            if m is None:
                return
            yield m
            ban = m.end() if m.end() == m.start() else None
            pos = m.end()

    def findall(self, text):
        out = []
        for m in self.finditer(text):
            if self.ngroups == 0:
                out.append(m.group())
            elif self.ngroups == 1:
                out.append(m.group(1) or "")
            else:
                out.append(tuple(g if g is not None else ""
                                 for g in m.groups()))
        return out

    # ---- DFA engine -------------------------------------------------
    def dfa(self, minimize=True):
        """Compiled (optionally minimized) DFA for this pattern.
        Raises RegexCompileError if the pattern uses \\b/\\B."""
        from .dfa import DFA
        if self._dfa is None or self._dfa.minimized != minimize:
            self._dfa = DFA(self.prog, minimize=minimize)
        return self._dfa

    def __repr__(self):
        return f"rxlab.compile({self.pattern!r})"


def compile(pattern):
    return Pattern(pattern)
