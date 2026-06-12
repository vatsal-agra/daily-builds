"""Differential fuzzer: random patterns + inputs, our engine vs Python's re.

Compares search/match/fullmatch spans+groups, findall, and finditer spans,
plus DFA≡NFA fullmatch equivalence for DFA-compatible patterns.  Pattern
generation avoids quantifying nullable subexpressions (a Pike VM and a
backtracker legitimately disagree there — see REVIEW.md).
"""

import random
import re

ALPHABET = "aab bc01_"
LEAVES = list(ALPHABET) + ["\\d", "\\w", "\\s", "."]
QUANTS = ["*", "+", "?", "{1,3}", "{2}", "*?", "+?", "??"]
ANCHORS = ["\\b", "\\B", "^", "$"]


def gen_pattern(rng, depth=3):
    """Returns (pattern, nullable)."""
    r = rng.random()
    if depth <= 0 or r < 0.35:
        leaf = rng.choice(LEAVES)
        return (re.escape(leaf) if len(leaf) == 1 else leaf), False
    if r < 0.50:
        a, na = gen_pattern(rng, depth - 1)
        b, nb = gen_pattern(rng, depth - 1)
        return a + b, na and nb
    if r < 0.62:
        a, na = gen_pattern(rng, depth - 1)
        b, nb = gen_pattern(rng, depth - 1)
        return f"(?:{a}|{b})", na or nb
    if r < 0.72:
        a, na = gen_pattern(rng, depth - 1)
        return f"({a})", na
    if r < 0.92:
        a, na = gen_pattern(rng, depth - 1)
        if na:
            return a, na
        q = rng.choice(QUANTS)
        return f"(?:{a}){q}", q[0] in "*?"
    a, na = gen_pattern(rng, depth - 1)
    return rng.choice(ANCHORS) + a, na


def run_fuzz(n=2000, seed=None, depth=3, max_text=8, verbose=False):
    """Returns (n_checked, list_of_diff_descriptions)."""
    from . import compile as rx_compile
    rng = random.Random(seed)
    diffs = []
    checked = 0
    while checked < n:
        pat, _ = gen_pattern(rng, depth)
        text = "".join(rng.choice(ALPHABET)
                       for _ in range(rng.randint(0, max_text)))
        try:
            ref = re.compile(pat, re.ASCII)
        except re.error:
            continue
        mine = rx_compile(pat)
        checked += 1
        for mode in ("search", "match", "fullmatch"):
            rm = getattr(ref, mode)(text)
            mm = getattr(mine, mode)(text)
            rs = (rm.span(), rm.groups()) if rm else None
            ms = (mm.span(), mm.groups()) if mm else None
            if rs != ms:
                diffs.append(f"{mode} {pat!r} on {text!r}: re={rs} ours={ms}")
        if mine.findall(text) != ref.findall(text):
            diffs.append(f"findall {pat!r} on {text!r}")
        if [m.span() for m in mine.finditer(text)] != \
                [m.span() for m in ref.finditer(text)]:
            diffs.append(f"finditer {pat!r} on {text!r}")
        if "\\b" not in pat and "\\B" not in pat:
            nfa_v = mine.fullmatch(text) is not None
            if mine.dfa().fullmatch(text) != nfa_v:
                diffs.append(f"DFA≠NFA {pat!r} on {text!r}")
        if verbose and checked % 500 == 0:
            print(f"  …{checked}/{n} patterns, {len(diffs)} diffs")
        if len(diffs) >= 20:
            break
    return checked, diffs
