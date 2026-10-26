import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
EX = os.path.join(ROOT, "examples")

from parsimony.api import Language  # noqa: E402
from parsimony.lexer import Token  # noqa: E402


def example(name: str, **kw) -> Language:
    return Language.from_file(os.path.join(EX, name), **kw)


def toks(types):
    """Token list from terminal names (for grammars with literal-only terminals)."""
    return [Token(t, t.strip("'"), 1, i + 1) for i, t in enumerate(types)] + [Token("$end", "", 1, len(types) + 1)]
