"""Error types. Parse errors carry the offending source and a character position."""


class TempoError(ValueError):
    """Base class for every error Tempo raises on bad input."""

    def __init__(self, message, source=None, pos=None):
        self.message = message
        self.source = source
        self.pos = pos
        super().__init__(self._render())

    def _render(self):
        if self.source is None or self.pos is None:
            return self.message
        src = self.source.replace("\n", " ")
        return f"{self.message}\n  {src}\n  {' ' * self.pos}^"


class RRuleError(TempoError):
    pass


class CronError(TempoError):
    pass


class ICSError(TempoError):
    pass


class NLError(TempoError):
    pass
