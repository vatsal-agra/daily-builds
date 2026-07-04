"""Myers O(ND) shortest-edit-script diff, and unified diff formatting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    tag: str  # 'equal' | 'delete' | 'insert'
    a_index: int  # index into a (meaningful for 'equal'/'delete')
    b_index: int  # index into b (meaningful for 'equal'/'insert')


def myers_diff(a: list[str], b: list[str]) -> list[Op]:
    """Return the minimal edit script turning `a` into `b`.

    Classic Myers O(ND) algorithm: find the shortest edit distance D by
    growing diagonals k = x - y one step at a time, recording each frontier
    so the actual path (not just the distance) can be walked back out.
    """
    n, m = len(a), len(b)
    max_d = n + m
    if max_d == 0:
        return []

    offset = max_d
    # trace[d][k+offset] = furthest x reached on diagonal k after d steps
    v = [0] * (2 * max_d + 1)
    trace: list[list[int]] = []

    def snake_end(d: int) -> tuple[int, int] | None:
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[k - 1 + offset] < v[k + 1 + offset]):
                x = v[k + 1 + offset]
            else:
                x = v[k - 1 + offset] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[k + offset] = x
            if x >= n and y >= m:
                return d, k
        return None

    found = None
    for d in range(0, max_d + 1):
        result = snake_end(d)
        trace.append(v.copy())
        if result is not None:
            found = result
            break

    if found is None:
        # a == b handled by max_d==0 above; unreachable otherwise.
        raise AssertionError("myers_diff: no path found")

    d_final, _k_final = found
    # Walk the trace backwards from (n, m) to (0, 0), then reverse.
    ops: list[Op] = []
    x, y = n, m
    for d in range(d_final, 0, -1):
        v_prev = trace[d - 1]
        k = x - y
        if k == -d or (k != d and v_prev[k - 1 + offset] < v_prev[k + 1 + offset]):
            prev_k = k + 1
        else:
            prev_k = k - 1
        prev_x = v_prev[prev_k + offset]
        prev_y = prev_x - prev_k

        while x > prev_x and y > prev_y:
            x -= 1
            y -= 1
            ops.append(Op("equal", x, y))

        if x == prev_x:
            y -= 1
            ops.append(Op("insert", x, y))
        else:
            x -= 1
            ops.append(Op("delete", x, y))

    while x > 0 and y > 0:
        x -= 1
        y -= 1
        ops.append(Op("equal", x, y))

    ops.reverse()
    return ops


def opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """Collapse a Myers edit script into (tag, a_start, a_end, b_start, b_end)
    runs, the same shape as difflib.SequenceMatcher.get_opcodes()."""
    ops = myers_diff(a, b)
    if not ops:
        return [("equal", 0, len(a), 0, len(b))] if a or b else []
    result = []
    cur_tag = None
    a_start = b_start = 0
    a_i = b_i = 0
    for op in ops:
        if op.tag != cur_tag:
            if cur_tag is not None:
                result.append((cur_tag, a_start, a_i, b_start, b_i))
            cur_tag = op.tag
            a_start, b_start = a_i, b_i
        if op.tag in ("equal", "delete"):
            a_i += 1
        if op.tag in ("equal", "insert"):
            b_i += 1
    result.append((cur_tag, a_start, a_i, b_start, b_i))
    # Merge adjacent delete+insert into replace, matching difflib semantics.
    merged: list[tuple[str, int, int, int, int]] = []
    i = 0
    while i < len(result):
        tag, as_, ae, bs, be = result[i]
        if (
            tag == "delete"
            and i + 1 < len(result)
            and result[i + 1][0] == "insert"
            and result[i + 1][1] == ae
        ):
            _, _, _, bs2, be2 = result[i + 1]
            merged.append(("replace", as_, ae, bs, be2))
            i += 2
        else:
            merged.append((tag, as_, ae, bs, be))
            i += 1
    return merged


def unified_diff(
    a: list[str],
    b: list[str],
    a_label: str = "a",
    b_label: str = "b",
    context: int = 3,
) -> str:
    """Format a unified diff (git/diff -u style) from two line lists.

    Lines are expected WITHOUT trailing newlines; a trailing newline is
    added to every emitted line except a final line that itself lacked one
    in the source (rendered with the standard `\\ No newline at end of file`
    marker), matching real diff/git output.
    """
    codes = opcodes(a, b)
    if all(tag == "equal" for tag, *_ in codes):
        return ""

    # Trim the leading/trailing all-equal runs down to `context` lines each,
    # then split any interior equal run longer than 2*context into two
    # hunk boundaries. This mirrors difflib's get_grouped_opcodes shape.
    codes = list(codes)
    if codes[0][0] == "equal":
        tag, i1, i2, j1, j2 = codes[0]
        codes[0] = (tag, max(i1, i2 - context), i2, max(j1, j2 - context), j2)
    if codes[-1][0] == "equal":
        tag, i1, i2, j1, j2 = codes[-1]
        codes[-1] = (tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context))

    nn = context + context
    groups: list[list[tuple[str, int, int, int, int]]] = []
    group: list[tuple[str, int, int, int, int]] = []
    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal" and i2 - i1 > nn:
            group.append((tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context)))
            groups.append(group)
            group = []
            i1, j1 = max(i1, i2 - context), max(j1, j2 - context)
        group.append((tag, i1, i2, j1, j2))
    if group and not (len(group) == 1 and group[0][0] == "equal"):
        groups.append(group)

    out_lines = [f"--- {a_label}", f"+++ {b_label}"]
    for g in groups:
        a_start = g[0][1]
        b_start = g[0][3]
        a_len = sum(ae - as_ for tag, as_, ae, bs, be in g if tag in ("equal", "delete", "replace"))
        b_len = sum(be - bs for tag, as_, ae, bs, be in g if tag in ("equal", "insert", "replace"))
        a_hdr = a_start + 1 if a_len else a_start
        b_hdr = b_start + 1 if b_len else b_start
        out_lines.append(f"@@ -{a_hdr},{a_len} +{b_hdr},{b_len} @@")
        for tag, as_, ae, bs, be in g:
            if tag == "equal":
                for i in range(as_, ae):
                    out_lines.append(" " + a[i])
            elif tag == "delete":
                for i in range(as_, ae):
                    out_lines.append("-" + a[i])
            elif tag == "insert":
                for i in range(bs, be):
                    out_lines.append("+" + b[i])
            elif tag == "replace":
                for i in range(as_, ae):
                    out_lines.append("-" + a[i])
                for i in range(bs, be):
                    out_lines.append("+" + b[i])
    return "\n".join(out_lines) + "\n"
