"""Error types for the Coil language.

Three phases can fail: lexing/parsing (SyntaxError-ish), compiling, and running.
Each error carries a source line so the CLI/REPL can render a helpful message.
"""


class CoilError(Exception):
    """Base class for all Coil errors."""

    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col

    def render(self, source=None, filename="<input>"):
        """Render a human-readable, optionally source-annotated message."""
        loc = filename
        if self.line is not None:
            loc += f":{self.line}"
            if self.col is not None:
                loc += f":{self.col}"
        out = [f"{self.kind} at {loc}: {self.message}"]
        if source is not None and self.line is not None:
            lines = source.splitlines()
            if 1 <= self.line <= len(lines):
                src_line = lines[self.line - 1]
                out.append(f"  {self.line:>4} | {src_line}")
                if self.col is not None:
                    caret_pad = " " * (self.col - 1)
                    out.append(f"       | {caret_pad}^")
        return "\n".join(out)

    kind = "error"


class LexError(CoilError):
    kind = "syntax error"


class ParseError(CoilError):
    kind = "syntax error"


class CompileError(CoilError):
    kind = "compile error"


class RuntimeCoilError(CoilError):
    """Raised during VM execution. May carry a call-stack traceback."""

    kind = "runtime error"

    def __init__(self, message, line=None, traceback_frames=None):
        super().__init__(message, line=line)
        self.traceback_frames = traceback_frames or []

    def render(self, source=None, filename="<input>"):
        out = ["runtime error: " + self.message]
        if self.traceback_frames:
            out.append("traceback (most recent call last):")
            for frame_name, frame_line in self.traceback_frames:
                where = f"{filename}:{frame_line}" if frame_line is not None else filename
                out.append(f"  in {frame_name} ({where})")
                if source is not None and frame_line is not None:
                    lines = source.splitlines()
                    if 1 <= frame_line <= len(lines):
                        out.append(f"      {lines[frame_line - 1].strip()}")
        return "\n".join(out)
