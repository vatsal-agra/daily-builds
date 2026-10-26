"""High-level facade: one grammar, every parsing strategy."""
from __future__ import annotations

from typing import Dict, List, Optional

from .analysis import Analysis
from .earley import EarleyParser, EarleyResult
from .grammar import Grammar, load_grammar
from .lexer import Lexer, Token
from .lr import METHODS, LRParser, LRTable, TraceRow, build_table
from .tree import Node

ALL_METHODS = METHODS + ("earley", "ll1")


class Language:
    """A compiled grammar. Tables are built lazily and cached per method."""

    def __init__(self, source: str, ebnf_style: str = "left"):
        self.source, self.ebnf_style = source, ebnf_style
        self._ll1_twin: Optional["Language"] = None
        self.grammar: Grammar = load_grammar(source, ebnf_style)
        self.analysis = Analysis(self.grammar)
        self.lexer = Lexer(self.grammar)
        self._tables: Dict[str, LRTable] = {}

    @classmethod
    def from_file(cls, path: str, **kw) -> "Language":
        with open(path, encoding="utf-8") as f:
            return cls(f.read(), **kw)

    def ll1_language(self) -> "Language":
        """The same grammar with right-recursive EBNF helpers (left-recursive ones can never be LL(1))."""
        if self.ebnf_style == "right":
            return self
        if self._ll1_twin is None:
            self._ll1_twin = Language(self.source, "right")
        return self._ll1_twin

    def table(self, method: str = "lalr") -> LRTable:
        if method not in self._tables:
            self._tables[method] = build_table(self.grammar, method, self.analysis)
        return self._tables[method]

    def tokenize(self, text: str) -> List[Token]:
        return self.lexer.tokenize(text)

    def parse(self, text: str, method: str = "lalr", trace: Optional[List[TraceRow]] = None) -> Node:
        """Parse ``text`` and return one parse tree. Raises LexError / ParseError."""
        toks = self.tokenize(text)
        if method in METHODS:
            return LRParser(self.table(method)).parse(toks, trace)
        if method == "earley":
            res = EarleyParser(self.grammar, self.analysis).parse(toks)
            return res.trees(1)[0]
        if method == "ll1":
            from .ll1 import LL1Parser
            twin = self.ll1_language()
            return LL1Parser(twin.grammar, twin.analysis).parse(twin.tokenize(text), trace)
        raise ValueError(f"unknown method {method!r}; choose from {ALL_METHODS}")

    def earley(self, text: str) -> EarleyResult:
        return EarleyParser(self.grammar, self.analysis).parse(self.tokenize(text))
