class FerruleError(Exception):
    """Any user-facing failure (bad input object, link error, syntax error)."""


class AsmError(FerruleError):
    def __init__(self, msg, line=None, file=None, source=None):
        self.line, self.file, self.bare, self.source = line, file, msg, source
        loc = f"{file or '<asm>'}:{line}: " if line is not None else (f"{file}: " if file else "")
        snippet = f"\n    {source.strip()}" if source and source.strip() else ""
        super().__init__(f"{loc}{msg}{snippet}")


class LinkError(FerruleError):
    pass
