"""Line breaking: Knuth--Plass total-fit, greedy first-fit, and a brute oracle.

The total-fit algorithm models breaking a paragraph as finding a shortest path
through a graph whose nodes are *feasible breakpoints*.  The cost of an edge from
break *a* to break *b* is the **demerits** of the line they bound, a function of
how badly the line's spaces must stretch or shrink (badness), the penalty of the
break, whether two flagged (hyphenated) breaks are adjacent, and whether two
visually mismatched lines are adjacent (fitness).  Dynamic programming over an
*active node* list finds the globally minimal-demerit set of breaks in close to
linear time.

References: D. E. Knuth and M. F. Plass, "Breaking Paragraphs into Lines",
*Software: Practice and Experience* 11 (1981); D. E. Knuth, *Digital
Typography*, ch. 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from .model import INFINITY, Box, Glue, Penalty, is_legal_breakpoint

# Demerit tuning constants (TeX defaults, adapted).
LINE_PENALTY = 10          # alpha: added to badness before squaring
FLAGGED_DEMERIT = 3000     # gamma: two hyphenated lines in a row
FITNESS_DEMERIT = 3000     # rho: two adjacent lines of very different fitness
INF_BAD = 1e12             # stand-in for an infeasible (overfull) line


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #

@dataclass
class Line:
    """A single laid-out line: the items it covers and its spacing."""

    start: int            # first item index on the line
    end: int              # breakpoint item index (exclusive of trailing glue)
    ratio: float          # adjustment ratio r (>0 stretched, <0 shrunk)
    natural_width: float  # natural width of the line's content
    target_width: float   # the measure this line was set to
    badness: float
    fitness: int          # fitness class 0..3
    flagged: bool         # did this line end on a flagged (hyphen) break?
    forced: bool          # did this line end on a forced break?


@dataclass
class Breaking:
    """The outcome of breaking a paragraph."""

    breaks: List[int]          # breakpoint item indices, in order
    lines: List[Line]
    total_demerits: float
    method: str
    feasible: bool             # False if any line was overfull/underfull-forced


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #

def fitness_class(r: float) -> int:
    """Map an adjustment ratio to one of four fitness classes.

    0 = tight, 1 = decent, 2 = loose, 3 = very loose.
    """
    if r < -0.5:
        return 0
    if r <= 0.5:
        return 1
    if r <= 1.0:
        return 2
    return 3


def badness(r: float) -> float:
    """Badness of a line with adjustment ratio ``r``: 100*|r|^3."""
    return 100.0 * abs(r) ** 3


def _measure(font_unused=None):
    pass


class _Sums:
    __slots__ = ("width", "stretch", "shrink")

    def __init__(self, width=0.0, stretch=0.0, shrink=0.0):
        self.width = width
        self.stretch = stretch
        self.shrink = shrink


# --------------------------------------------------------------------------- #
# Knuth--Plass total-fit
# --------------------------------------------------------------------------- #

@dataclass
class _Node:
    """An active breakpoint node in the dynamic program."""

    position: int       # item index of this breakpoint
    line: int           # line number ending at this breakpoint
    fitness: int        # fitness class of the line ending here
    totals: _Sums       # running sums just after this break (leading glue skipped)
    demerits: float     # total demerits of the best path to here
    ratio: float        # adjustment ratio of the line ending here
    previous: Optional["_Node"]


def _line_length(line_lengths: Sequence[float], line_index: int) -> float:
    if line_index < len(line_lengths):
        return line_lengths[line_index]
    return line_lengths[-1]


def break_paragraph(
    items: List[object],
    measure,
    *,
    tolerance: float = 100.0,
    line_penalty: float = LINE_PENALTY,
    flagged_demerit: float = FLAGGED_DEMERIT,
    fitness_demerit: float = FITNESS_DEMERIT,
    looseness: int = 0,
    escalate: bool = True,
) -> Breaking:
    """Break ``items`` into lines minimizing total demerits (Knuth--Plass).

    ``measure`` is either a single number (every line the same width) or a list
    of per-line widths.  ``tolerance`` is the maximum allowed badness for a
    feasible line (TeX's \\tolerance).  ``looseness`` nudges the chosen number of
    lines (negative = fewer, positive = more), if a path of that length exists.

    If ``escalate`` is true and the requested tolerance admits no all-feasible
    breaking (some line would be overfull), the tolerance is raised
    geometrically until a feasible solution is found or a hard cap is reached,
    matching the spirit of TeX's second pass.  This guarantees usable output for
    narrow measures rather than overfull lines.
    """
    result = _break_once(items, measure, tolerance, line_penalty,
                         flagged_demerit, fitness_demerit, looseness)
    if escalate and not result.feasible:
        tol = tolerance
        while not result.feasible and tol < 1e7:
            tol *= 4.0
            result = _break_once(items, measure, tol, line_penalty,
                                 flagged_demerit, fitness_demerit, looseness)
    return result


def _break_once(
    items: List[object],
    measure,
    tolerance: float,
    line_penalty: float,
    flagged_demerit: float,
    fitness_demerit: float,
    looseness: int,
) -> Breaking:
    """One Knuth--Plass pass at a fixed tolerance (see :func:`break_paragraph`)."""
    line_lengths = [float(measure)] if isinstance(measure, (int, float)) else list(measure)
    if not line_lengths:
        raise ValueError("measure must be a positive number or non-empty list")

    # Active node list starts with a single node at the paragraph start.
    active: List[_Node] = [
        _Node(position=0, line=0, fitness=1, totals=_Sums(),
              demerits=0.0, ratio=0.0, previous=None)
    ]

    running = _Sums()  # running sums of everything seen so far

    def totals_after(b: int) -> _Sums:
        """Running sums after breakpoint ``b``, discarding glue that follows it."""
        s = _Sums(running.width, running.stretch, running.shrink)
        i = b
        n = len(items)
        while i < n:
            it = items[i]
            if it.is_box:
                break
            if it.is_glue:
                s.width += it.width
                s.stretch += it.stretch
                s.shrink += it.shrink
            elif it.is_penalty and it.penalty <= -INFINITY and i > b:
                break
            i += 1
        return s

    def consider(b: int) -> None:
        """Inner loop: evaluate breaking at item index ``b`` from every active node."""
        item = items[b]
        forced = item.is_penalty and item.penalty <= -INFINITY
        break_penalty = item.penalty if item.is_penalty else 0.0
        break_flagged = bool(item.is_penalty and item.flagged)
        extra_width = item.width if item.is_penalty else 0.0

        # Best candidate per fitness class feeding into b.
        best = [None, None, None, None]      # _Node predecessors
        best_dem = [float("inf")] * 4
        best_ratio = [0.0] * 4

        # Best *infeasible* candidate (least demerits), kept only to re-seed an
        # emergency break if the active list would otherwise empty.
        inf_prev = None
        inf_dem = float("inf")
        inf_ratio = 0.0
        inf_fc = 1

        a_index = 0
        while a_index < len(active):
            a = active[a_index]
            line_idx = a.line  # line being formed (0-based) ends at b
            L = (running.width - a.totals.width) + extra_width
            avail = _line_length(line_lengths, line_idx)

            if L < avail:
                Y = running.stretch - a.totals.stretch
                r = (avail - L) / Y if Y > 1e-9 else INF_BAD
            elif L > avail:
                Z = running.shrink - a.totals.shrink
                r = (avail - L) / Z if Z > 1e-9 else -INF_BAD
            else:
                r = 0.0

            # Deactivate nodes that can never reach a feasible later break: a
            # line that is already overfull (r < -1) or that we are forced to
            # break here.
            remove = (r < -1.0) or forced
            if remove:
                active.pop(a_index)
            else:
                a_index += 1

            b_badness = badness(r) if r > -1.0 else INF_BAD
            infeasible = (r < -1.0) or (b_badness > tolerance)

            if infeasible and not forced:
                # Track this as a possible emergency edge, then skip it.
                cand = a.demerits + (LINE_PENALTY + min(b_badness, INF_BAD)) ** 2
                if cand < inf_dem:
                    inf_dem = cand
                    inf_prev = a
                    inf_ratio = r  # true ratio (may be < -1: overfull)
                    inf_fc = fitness_class(max(r, -1.0))
                continue

            # --- demerits for the line a -> b ---
            lp = line_penalty + b_badness
            if break_penalty >= 0 and break_penalty < INFINITY:
                d = lp * lp + break_penalty * break_penalty
            elif break_penalty > -INFINITY:
                d = lp * lp - break_penalty * break_penalty
            else:  # forced break
                d = lp * lp
            # Flagged: penalize two hyphenated breaks in a row.
            if break_flagged and _node_flagged(a, items):
                d += flagged_demerit
            fc = fitness_class(r)
            if abs(fc - a.fitness) > 1:
                d += fitness_demerit
            total = a.demerits + d

            if total < best_dem[fc]:
                best_dem[fc] = total
                best[fc] = a
                best_ratio[fc] = r

        # Create new active nodes (one per fitness class with a candidate).
        added_feasible = False
        if any(b_node is not None for b_node in best):
            t = totals_after(b)
            for fc in range(4):
                if best[fc] is None:
                    continue
                new = _Node(
                    position=b,
                    line=best[fc].line + 1,
                    fitness=fc,
                    totals=t,
                    demerits=best_dem[fc],
                    ratio=best_ratio[fc],
                    previous=best[fc],
                )
                active.append(new)
                added_feasible = True

        # Emergency re-seed: if the active list has emptied (every node was
        # deactivated and none produced a feasible line) and we still have text
        # to set, force a break from the least-demerit infeasible candidate so
        # the algorithm always terminates rather than dropping words. This
        # mirrors TeX's emergency pass; such a line is flagged infeasible
        # (overfull/underfull) in the result.
        if not active and not added_feasible and inf_prev is not None:
            t = totals_after(b)
            active.append(_Node(
                position=b,
                line=inf_prev.line + 1,
                fitness=inf_fc,
                totals=t,
                demerits=inf_dem + INF_BAD,  # mark this path as costly/infeasible
                ratio=inf_ratio,
                previous=inf_prev,
            ))

    # --- main loop over items ---
    n = len(items)
    for b in range(n):
        item = items[b]
        if item.is_box:
            running.width += item.width
        elif item.is_glue:
            if is_legal_breakpoint(items, b):
                consider(b)
            running.width += item.width
            running.stretch += item.stretch
            running.shrink += item.shrink
        elif item.is_penalty:
            if is_legal_breakpoint(items, b):
                consider(b)
        if not active:
            # Should not happen: the emergency re-seed keeps at least one node
            # alive whenever text remains. Guard against a logic error.
            raise InfeasibleParagraph(
                "no feasible breaking found; internal active list emptied"
            )

    # Choose the active node ending the paragraph with least demerits, honoring
    # looseness if requested.
    best_node = _choose_active(active, looseness)
    breaks, lines = _reconstruct(best_node, items, line_lengths)
    feasible = all(l.badness < INF_BAD for l in lines)
    return Breaking(breaks=breaks, lines=lines,
                    total_demerits=best_node.demerits, method="knuth-plass",
                    feasible=feasible)


class InfeasibleParagraph(Exception):
    pass


def _node_flagged(node: _Node, items) -> bool:
    if node.position <= 0:
        return False
    it = items[node.position]
    return bool(it.is_penalty and it.flagged)


def _choose_active(active: List[_Node], looseness: int) -> _Node:
    best = min(active, key=lambda nd: nd.demerits)
    if looseness == 0:
        return best
    # Find a node whose line count differs from best by the desired looseness
    # (closest match) with least demerits.
    target = best.line + looseness
    candidates = sorted(active, key=lambda nd: (abs(nd.line - target), nd.demerits))
    return candidates[0]


def _reconstruct(node: _Node, items, line_lengths):
    chain = []
    cur = node
    while cur is not None:
        chain.append(cur)
        cur = cur.previous
    chain.reverse()  # chain[0] is the start node (position 0)

    breaks = [nd.position for nd in chain[1:]]
    lines: List[Line] = []
    for li in range(1, len(chain)):
        a = chain[li - 1]
        b = chain[li]
        start = a.position
        end = b.position
        natural = _natural_width(items, start, end)
        avail = _line_length(line_lengths, li - 1)
        r = b.ratio
        item = items[end] if end < len(items) else None
        flagged = bool(item is not None and item.is_penalty and item.flagged)
        forced = bool(item is not None and item.is_penalty and item.penalty <= -INFINITY)
        lines.append(Line(
            start=start, end=end, ratio=r, natural_width=natural,
            target_width=avail, badness=badness(r) if r > -1.0 else INF_BAD,
            fitness=b.fitness, flagged=flagged, forced=forced,
        ))
    return breaks, lines


def _natural_width(items, start, end) -> float:
    """Natural width of the content between breakpoints start..end.

    Leading glue after ``start`` is discarded; the penalty width at ``end`` (a
    hyphen) is included.
    """
    w = 0.0
    i = start
    # skip leading discardable glue at line start
    while i < end and items[i].is_glue:
        i += 1
    while i < end:
        it = items[i]
        if it.is_box:
            w += it.width
        elif it.is_glue:
            w += it.width
        i += 1
    if end < len(items) and items[end].is_penalty:
        w += items[end].width
    return w


# --------------------------------------------------------------------------- #
# Greedy first-fit (for comparison)
# --------------------------------------------------------------------------- #

def greedy_break(items: List[object], measure) -> Breaking:
    """First-fit greedy line breaking: break at the last glue that still fits.

    This is what naive word processors do.  It never looks ahead, so it tends to
    leave lines that must stretch a lot followed by lines that barely fit.
    """
    line_lengths = [float(measure)] if isinstance(measure, (int, float)) else list(measure)
    breaks: List[int] = []
    lines: List[Line] = []

    n = len(items)
    legal = [i for i in range(n) if is_legal_breakpoint(items, i)]

    start = 0
    line_idx = 0
    idx = 0  # pointer into ``legal``
    while idx < len(legal):
        # Skip breakpoints at or before the current line start.
        while idx < len(legal) and legal[idx] <= start:
            idx += 1
        if idx >= len(legal):
            break
        avail = _line_length(line_lengths, line_idx)

        # Walk forward over legal breaks, keeping the furthest one that still
        # fits; stop at the first overflow or a forced break.
        chosen = None
        j = idx
        while j < len(legal):
            bp = legal[j]
            forced = items[bp].is_penalty and items[bp].penalty <= -INFINITY
            w = _natural_width(items, start, bp)
            if w <= avail:
                chosen = bp
                if forced:
                    break  # fits and ends the paragraph
                j += 1
            else:
                if chosen is None:
                    # Even the first option overflows (an unbreakable long word
                    # or a final line that cannot be shortened): take it overfull.
                    chosen = bp
                break

        if chosen is None:
            break
        forced_here = items[chosen].is_penalty and items[chosen].penalty <= -INFINITY
        _emit_greedy_line(items, breaks, lines, start, chosen, avail, line_idx, line_lengths)
        if forced_here:
            break
        start = chosen
        line_idx += 1

    total = sum(_line_demerits(l) for l in lines)
    feasible = all(l.badness < INF_BAD for l in lines)
    return Breaking(breaks=breaks, lines=lines, total_demerits=total,
                    method="greedy", feasible=feasible)


def _emit_greedy_line(items, breaks, lines, start, end, avail, line_idx, line_lengths):
    natural = _natural_width(items, start, end)
    Y, Z = _stretch_shrink(items, start, end)
    if natural < avail:
        r = (avail - natural) / Y if Y > 1e-9 else INF_BAD
    elif natural > avail:
        r = (avail - natural) / Z if Z > 1e-9 else -INF_BAD
    else:
        r = 0.0
    item = items[end] if end < len(items) else None
    flagged = bool(item is not None and item.is_penalty and item.flagged)
    forced = bool(item is not None and item.is_penalty and item.penalty <= -INFINITY)
    breaks.append(end)
    lines.append(Line(start=start, end=end, ratio=r, natural_width=natural,
                      target_width=avail, badness=badness(r) if r > -1.0 else INF_BAD,
                      fitness=fitness_class(r), flagged=flagged, forced=forced))


def _stretch_shrink(items, start, end):
    Y = Z = 0.0
    i = start
    while i < end and items[i].is_glue:
        i += 1
    while i < end:
        it = items[i]
        if it.is_glue:
            Y += it.stretch
            Z += it.shrink
        i += 1
    return Y, Z


def _line_demerits(l: Line) -> float:
    if l.badness >= INF_BAD:
        return INF_BAD
    lp = LINE_PENALTY + l.badness
    return lp * lp


# --------------------------------------------------------------------------- #
# Shared edge scorer (single source of truth for the demerit model)
# --------------------------------------------------------------------------- #

def _edge_ratio(items, a, b, line_lengths, line_idx):
    natural = _natural_width(items, a, b)
    Y, Z = _stretch_shrink(items, a, b)
    avail = _line_length(line_lengths, line_idx)
    if natural < avail:
        r = (avail - natural) / Y if Y > 1e-9 else INF_BAD
    elif natural > avail:
        r = (avail - natural) / Z if Z > 1e-9 else -INF_BAD
    else:
        r = 0.0
    return r


def _edge_demerits(items, a, b, line_idx, prev_fitness, prev_flagged,
                   line_lengths, tolerance):
    """Demerits of the line from break ``a`` to break ``b``.

    Returns ``(demerits, fitness, flagged, ratio)`` or ``None`` if the edge is
    infeasible (overfull, or over-tolerance and not forced).  This is the single
    demerit model used by Knuth--Plass, the brute-force oracle, and scoring.
    """
    r = _edge_ratio(items, a, b, line_lengths, line_idx)
    item = items[b]
    forced = item.is_penalty and item.penalty <= -INFINITY
    if r < -1.0 and not forced:
        return None
    b_bad = badness(r) if r > -1.0 else INF_BAD
    if b_bad > tolerance and not forced:
        return None
    bp = item.penalty if item.is_penalty else 0.0
    lp = LINE_PENALTY + b_bad
    if 0 <= bp < INFINITY:
        d = lp * lp + bp * bp
    elif bp > -INFINITY:
        d = lp * lp - bp * bp
    else:
        d = lp * lp
    flg = bool(item.is_penalty and item.flagged)
    if flg and prev_flagged:
        d += FLAGGED_DEMERIT
    fc = fitness_class(r)
    if abs(fc - prev_fitness) > 1:
        d += FITNESS_DEMERIT
    return d, fc, flg, r


def evaluate_breaks(items, breaks, measure, *, tolerance: float = 1e12) -> Breaking:
    """Score an explicit break sequence under the full demerit model.

    Lets any breaker's output (e.g. greedy's) be compared to Knuth--Plass on the
    exact same cost function.  Overfull/over-tolerance lines contribute INF_BAD
    so they dominate, marking the result infeasible.
    """
    line_lengths = [float(measure)] if isinstance(measure, (int, float)) else list(measure)
    lines: List[Line] = []
    total = 0.0
    prev_fitness = 1
    prev_flagged = False
    a = 0
    for li, b in enumerate(breaks):
        res = _edge_demerits(items, a, b, li, prev_fitness, prev_flagged,
                             line_lengths, tolerance)
        if res is None:
            # Infeasible line: score it with INF_BAD so it is clearly bad.
            r = _edge_ratio(items, a, b, line_lengths, li)
            d = INF_BAD
            fc = fitness_class(max(r, -1.0))
            flg = bool(items[b].is_penalty and items[b].flagged)
        else:
            d, fc, flg, r = res
        total += d
        item = items[b]
        lines.append(Line(
            start=a, end=b, ratio=r, natural_width=_natural_width(items, a, b),
            target_width=_line_length(line_lengths, li),
            badness=badness(r) if r > -1.0 else INF_BAD,
            fitness=fc, flagged=flg,
            forced=bool(item.is_penalty and item.penalty <= -INFINITY),
        ))
        prev_fitness, prev_flagged = fc, flg
        a = b
    feasible = all(l.badness < INF_BAD for l in lines)
    return Breaking(breaks=list(breaks), lines=lines, total_demerits=total,
                    method="evaluated", feasible=feasible)


# --------------------------------------------------------------------------- #
# Brute-force optimal oracle (verification only — exponential)
# --------------------------------------------------------------------------- #

def brute_force_break(items: List[object], measure, *, tolerance: float = 1e9):
    """Exhaustively minimise total demerits over all feasible break subsets.

    Used as a differential oracle for small paragraphs: the Knuth--Plass DP must
    return the same minimal total demerits this returns.  Exponential in the
    number of optional breakpoints, so only use it on short inputs.
    """
    line_lengths = [float(measure)] if isinstance(measure, (int, float)) else list(measure)
    n = len(items)
    legal = [i for i in range(n) if is_legal_breakpoint(items, i)]
    forced_end = n - 1  # final forced break index
    optional = [i for i in legal if not (items[i].is_penalty and items[i].penalty <= -INFINITY)]

    best = {"dem": float("inf"), "breaks": None}

    def recurse(a, chosen, acc, line_idx, prev_fitness, prev_flagged):
        if acc >= best["dem"]:
            return
        # Option: break at the final forced break, closing the paragraph.
        res = _edge_demerits(items, a, forced_end, line_idx, prev_fitness,
                             prev_flagged, line_lengths, tolerance)
        if res is not None:
            d, fc, flg, r = res
            total = acc + d
            if total < best["dem"]:
                best["dem"] = total
                best["breaks"] = chosen + [forced_end]
        # Option: take some optional break strictly after a and before the end.
        for b in optional:
            if b <= a or b >= forced_end:
                continue
            res = _edge_demerits(items, a, b, line_idx, prev_fitness,
                                 prev_flagged, line_lengths, tolerance)
            if res is None:
                continue
            d, fc, flg, r = res
            recurse(b, chosen + [b], acc + d, line_idx + 1, fc, flg)

    recurse(0, [], 0.0, 0, 1, False)
    return best["dem"], best["breaks"]
