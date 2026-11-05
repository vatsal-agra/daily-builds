class FerruleError(Exception):
    """Any user-facing failure (bad input object, link error, syntax error)."""


class AsmError(FerruleError):
    def __init__(self, msg, line=None, file=None):
        self.line, self.file, self.bare = line, file, msg
        loc = f"{file or '<asm>'}:{line}: " if line is not None else ""
        super().__init__(f"{loc}{msg}")


class LinkError(FerruleError):
    pass
