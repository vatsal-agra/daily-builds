"""Scanner and error types for the RegexLab pattern parser."""


class RegexError(Exception):
    """Base class for all RegexLab errors."""


class RegexSyntaxError(RegexError):
    """Malformed pattern. Carries the offending position."""

    def __init__(self, message, pos):
        super().__init__(f"{message} at position {pos}")
        self.message = message
        self.pos = pos


class RegexCompileError(RegexError):
    """Pattern is syntactically valid but cannot be compiled (e.g. too large)."""


class Scanner:
    """Character-level cursor over a pattern string."""

    def __init__(self, text):
        self.text = text
        self.pos = 0

    def eof(self):
        return self.pos >= len(self.text)

    def peek(self, ahead=0):
        i = self.pos + ahead
        return self.text[i] if i < len(self.text) else ""

    def next(self):
        ch = self.text[self.pos]
        self.pos += 1
        return ch

    def accept(self, ch):
        if not self.eof() and self.text[self.pos] == ch:
            self.pos += 1
            return True
        return False

    def error(self, message, pos=None):
        raise RegexSyntaxError(message, self.pos if pos is None else pos)
