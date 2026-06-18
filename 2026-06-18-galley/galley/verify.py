"""Verification helpers: round-trip integrity and whitespace-river detection."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .render import adjusted_glue


def reconstruct_words(items, breaking) -> List[str]:
    """Recover the word stream actually laid out by a breaking.

    Walks the items covered by the lines in order, joining boxes into words and
    flushing a word at each inter-word glue.  Hyphenation fragments (boxes with
    no glue between them) rejoin automatically; inserted hyphens are not part of
    any box, so they never appear.
    """
    if not breaking.lines:
        return []
    last_end = breaking.lines[-1].end
    words: List[str] = []
    cur = ""
    for i in range(0, last_end):
        it = items[i]
        if it.is_box:
            cur += it.text
        elif it.is_glue:
            if cur:
                words.append(cur)
                cur = ""
        # penalties contribute nothing to the word text
    if cur:
        words.append(cur)
    return words


def roundtrip_words(items, breaking, original_words) -> Tuple[bool, str]:
    """Check the breaking tiles the items and reproduces the word stream exactly."""
    lines = breaking.lines
    if not lines:
        return (len(original_words) == 0, "empty breaking")
    # 1. Lines must tile the item range contiguously.
    if lines[0].start != 0:
        return False, f"first line starts at {lines[0].start}, not 0"
    for a, b in zip(lines, lines[1:]):
        if a.end != b.start:
            return False, f"gap/overlap between lines: {a.end} != {b.start}"
    # 2. Word reconstruction must match.
    got = reconstruct_words(items, breaking)
    if got != list(original_words):
        # Find first divergence for a useful message.
        for idx, (g, o) in enumerate(zip(got, original_words)):
            if g != o:
                return False, f"word {idx}: got {g!r}, expected {o!r}"
        return False, (f"length differs: got {len(got)} words, "
                       f"expected {len(original_words)}")
    return True, "ok"


# --------------------------------------------------------------------------- #
# River detection
# --------------------------------------------------------------------------- #

def line_gap_centers(items, line, *, min_width: float = 0.0,
                     margin: float = 0.0) -> List[float]:
    """X centres of the inter-word spaces on a laid-out line.

    Only spaces at least ``min_width`` wide are returned, so a river is built
    from genuinely open gaps rather than tightly-set ones.
    """
    centers: List[float] = []
    x = margin
    i = line.start
    while i < line.end and items[i].is_glue:
        i += 1
    while i < line.end:
        it = items[i]
        if it.is_box:
            x += it.width
        elif it.is_glue:
            w = adjusted_glue(it.width, it.stretch, it.shrink, line.ratio)
            if w >= min_width - 1e-9:
                centers.append(x + w / 2.0)
            x += w
        i += 1
    return centers


def count_rivers(items, breaking, font, *, threshold: float = None,
                 min_length: int = 3) -> List[Dict]:
    """Detect vertical whitespace rivers spanning >= ``min_length`` lines.

    A river is a run of inter-word gaps in consecutive lines whose horizontal
    centres stay within ``threshold`` of each other — the classic typographic
    defect where the eye follows a pale channel down the column.  Gaps narrower
    than a natural space do not count, and the alignment threshold is tight
    (0.4 space-widths) so only real channels register.
    """
    if threshold is None:
        threshold = font.space_width * 0.4
    min_gap = font.space_width
    lines = breaking.lines
    gaps_per_line = [line_gap_centers(items, ln, min_width=min_gap) for ln in lines]

    # Active rivers: each is dict(x=current x, start_line, length, last_line)
    rivers: List[Dict] = []
    active: List[Dict] = []
    for li, gaps in enumerate(gaps_per_line):
        new_active: List[Dict] = []
        used = [False] * len(gaps)
        for riv in active:
            # Try to extend this river with the closest unused gap on this line.
            best_j, best_d = -1, threshold
            for j, gx in enumerate(gaps):
                if used[j]:
                    continue
                d = abs(gx - riv["x"])
                if d < best_d:
                    best_d, best_j = d, j
            if best_j >= 0:
                used[best_j] = True
                riv["x"] = (riv["x"] + gaps[best_j]) / 2.0
                riv["length"] += 1
                riv["end_line"] = li
                new_active.append(riv)
            else:
                if riv["length"] >= min_length:
                    rivers.append(riv)
        # Start new rivers from any gap not used to extend an existing one.
        for j, gx in enumerate(gaps):
            if not used[j]:
                new_active.append({"x": gx, "start_line": li,
                                   "end_line": li, "length": 1})
        active = new_active
    for riv in active:
        if riv["length"] >= min_length:
            rivers.append(riv)
    rivers.sort(key=lambda r: (-r["length"], r["start_line"]))
    return rivers
