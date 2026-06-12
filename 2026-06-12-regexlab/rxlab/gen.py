"""Sample generator: produce random strings that match a pattern.

Walks the AST making random choices, then *verifies* each candidate with the
engine (fullmatch) — anchors and word boundaries can make naive generation
produce non-matches (e.g. `a\\bb` is unsatisfiable), so candidates that fail
verification are rejected and retried.  Deterministic per seed.
"""

import random

from . import Pattern
from . import parser as P
from .lexer import RegexCompileError

MAX_REPEAT_SAMPLE = 4   # cap for unbounded quantifiers
PRINTABLE = [(32, 126)]  # preferred codepoints when a class allows them


def _intersect(ranges, pref):
    out = []
    for lo, hi in ranges:
        for plo, phi in pref:
            a, b = max(lo, plo), min(hi, phi)
            if a <= b:
                out.append((a, b))
    return out


def _pick_from(ranges, rng):
    nice = _intersect(ranges, PRINTABLE)
    pool = nice if nice else list(ranges)
    weights = [hi - lo + 1 for lo, hi in pool]
    lo, hi = rng.choices(pool, weights=weights)[0]
    return chr(rng.randint(lo, hi))


def _emit(node, rng, out):
    if isinstance(node, P.Lit):
        out.append(node.ch)
    elif isinstance(node, (P.CharClass, P.Dot)):
        ranges = node.ranges()
        if not ranges:
            raise RegexCompileError("class matches no characters")
        out.append(_pick_from(ranges, rng))
    elif isinstance(node, P.Anchor):
        pass  # contributes no characters; verification handles satisfiability
    elif isinstance(node, P.Concat):
        for part in node.parts:
            _emit(part, rng, out)
    elif isinstance(node, P.Alt):
        _emit(rng.choice(node.branches), rng, out)
    elif isinstance(node, P.Group):
        _emit(node.child, rng, out)
    elif isinstance(node, P.Repeat):
        hi = node.hi if node.hi is not None \
            else node.lo + rng.randint(0, MAX_REPEAT_SAMPLE)
        hi = min(hi, node.lo + MAX_REPEAT_SAMPLE)
        for _ in range(rng.randint(node.lo, max(node.lo, hi))):
            _emit(node.child, rng, out)


def generate(pattern, n=10, seed=None, max_attempts_per_sample=50):
    """Generate up to n distinct-ish verified matching strings.
    Returns (samples, n_rejected).  Raises RegexCompileError if the pattern
    appears unsatisfiable (every candidate failed verification)."""
    ast, _ = P.parse(pattern)
    pat = Pattern(pattern)
    rng = random.Random(seed)
    samples, rejected = [], 0
    seen = set()
    for _ in range(n):
        got = None
        for _attempt in range(max_attempts_per_sample):
            out = []
            _emit(ast, rng, out)
            cand = "".join(out)
            if cand in seen:  # only collect distinct samples
                continue
            if pat.fullmatch(cand) is not None:
                got = cand
                break
            rejected += 1
        if got is None:
            if not samples:
                raise RegexCompileError(
                    f"could not generate a matching string for {pattern!r} "
                    f"after {max_attempts_per_sample} attempts — the pattern "
                    "may be unsatisfiable (e.g. contradictory anchors)")
            break  # pattern has fewer than n distinct (likely) matches
        seen.add(got)
        samples.append(got)
    return samples, rejected
