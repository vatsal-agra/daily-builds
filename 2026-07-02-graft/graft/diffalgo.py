"""Myers O(ND) diff: minimal edit script between two sequences, plus a
git-style unified-diff formatter built on top of it.
"""


def _shortest_edit_trace(a, b):
    n, m = len(a), len(b)
    max_d = n + m
    v = {1: 0}
    trace = []
    for d in range(0, max_d + 1):
        trace.append(dict(v))
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v.get(k - 1, 0) < v.get(k + 1, 0)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, 0) + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[k] = x
            if x >= n and y >= m:
                return trace, d
    raise AssertionError("unreachable: Myers diff must terminate within N+M steps")


def _backtrack(trace, d, a, b):
    x, y = len(a), len(b)
    ops = []  # reversed; each is ('equal'|'insert'|'delete', a_idx_or_None, b_idx_or_None)
    for depth in range(d, 0, -1):
        v = trace[depth]
        k = x - y
        if k == -depth or (k != depth and v.get(k - 1, 0) < v.get(k + 1, 0)):
            prev_k = k + 1
        else:
            prev_k = k - 1
        prev_x = v.get(prev_k, 0)
        prev_y = prev_x - prev_k
        while x > prev_x and y > prev_y:
            ops.append(("equal", x - 1, y - 1))
            x -= 1
            y -= 1
        if x == prev_x:
            ops.append(("insert", None, y - 1))
            y -= 1
        else:
            ops.append(("delete", x - 1, None))
            x -= 1
    while x > 0 and y > 0:
        ops.append(("equal", x - 1, y - 1))
        x -= 1
        y -= 1
    while x > 0:
        ops.append(("delete", x - 1, None))
        x -= 1
    while y > 0:
        ops.append(("insert", None, y - 1))
        y -= 1
    ops.reverse()
    return ops


def edit_script(a, b):
    """Return the minimal per-element edit script as a list of
    ('equal'|'insert'|'delete', a_idx, b_idx) tuples (idx is None where n/a).
    """
    if a == b:
        return [("equal", i, i) for i in range(len(a))]
    trace, d = _shortest_edit_trace(a, b)
    return _backtrack(trace, d, a, b)


def edit_distance(a, b):
    """Number of insert+delete operations in the minimal edit script."""
    return sum(1 for tag, _, _ in edit_script(a, b) if tag != "equal")


def opcodes(a, b):
    """Collapse the per-element edit script into difflib-style ranges:
    [(tag, i1, i2, j1, j2), ...] with tag in equal/delete/insert/replace.
    """
    ops = edit_script(a, b)
    groups = []
    for tag, ai, bi in ops:
        if groups and groups[-1][0] == tag:
            groups[-1][1].append((ai, bi))
        else:
            groups.append([tag, [(ai, bi)]])

    ranges = []
    for tag, items in groups:
        if tag == "equal":
            i1, j1 = items[0]
            i2, j2 = items[-1]
            ranges.append(["equal", i1, i2 + 1, j1, j2 + 1])
        elif tag == "delete":
            i1 = items[0][0]
            i2 = items[-1][0]
            j = items[0][1] if items[0][1] is not None else _infer_j(ranges)
            ranges.append(["delete", i1, i2 + 1, j, j])
        else:  # insert
            j1 = items[0][1]
            j2 = items[-1][1]
            i = _infer_i(ranges)
            ranges.append(["insert", i, i, j1, j2 + 1])

    # merge adjacent delete+insert (or insert+delete) into replace, git/difflib-style
    merged = []
    i = 0
    while i < len(ranges):
        cur = ranges[i]
        if (
            i + 1 < len(ranges)
            and {cur[0], ranges[i + 1][0]} == {"delete", "insert"}
        ):
            nxt = ranges[i + 1]
            d = cur if cur[0] == "delete" else nxt
            ins = cur if cur[0] == "insert" else nxt
            merged.append(["replace", d[1], d[2], ins[3], ins[4]])
            i += 2
        else:
            merged.append(cur)
            i += 1
    return [tuple(r) for r in merged]


def _infer_j(ranges):
    return ranges[-1][4] if ranges else 0


def _infer_i(ranges):
    return ranges[-1][2] if ranges else 0


def grouped_opcodes(ops, context=3):
    """Split opcodes into hunks, trimming/collapsing long equal runs down to
    `context` lines of surrounding context (same algorithm as
    difflib.SequenceMatcher.get_grouped_opcodes).
    """
    codes = list(ops)
    if not codes:
        return []
    if codes[0][0] == "equal":
        tag, i1, i2, j1, j2 = codes[0]
        codes[0] = (tag, max(i1, i2 - context), i2, max(j1, j2 - context), j2)
    if codes[-1][0] == "equal":
        tag, i1, i2, j1, j2 = codes[-1]
        codes[-1] = (tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context))

    nn = context + context
    groups = []
    group = []
    for tag, i1, i2, j1, j2 in codes:
        if tag == "equal" and i2 - i1 > nn:
            group.append((tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context)))
            groups.append(group)
            group = []
            i1, j1 = max(i1, i2 - context), max(j1, j2 - context)
        group.append((tag, i1, i2, j1, j2))
    if group and not (len(group) == 1 and group[0][0] == "equal"):
        groups.append(group)
    return groups


def unified_diff(a_lines, b_lines, a_path, b_path, context=3):
    """Git-style unified diff. a_lines/b_lines: lists of lines WITHOUT
    trailing newlines. Returns a list of output lines (also without
    trailing newlines).
    """
    ops = opcodes(a_lines, b_lines)
    if all(op[0] == "equal" for op in ops):
        return []

    out = [f"--- {a_path}", f"+++ {b_path}"]
    for hunk_ops in grouped_opcodes(ops, context):
        a_start = hunk_ops[0][1]
        a_end = hunk_ops[-1][2]
        b_start = hunk_ops[0][3]
        b_end = hunk_ops[-1][4]
        a_count = a_end - a_start
        b_count = b_end - b_start
        a_hdr = f"{a_start + 1},{a_count}" if a_count != 1 else f"{a_start + 1}"
        b_hdr = f"{b_start + 1},{b_count}" if b_count != 1 else f"{b_start + 1}"
        if a_count == 0:
            a_hdr = f"{a_start},0"
        if b_count == 0:
            b_hdr = f"{b_start},0"
        out.append(f"@@ -{a_hdr} +{b_hdr} @@")
        for tag, i1, i2, j1, j2 in hunk_ops:
            if tag == "equal":
                for k in range(i1, i2):
                    out.append(f" {a_lines[k]}")
            else:
                if tag in ("delete", "replace"):
                    for k in range(i1, i2):
                        out.append(f"-{a_lines[k]}")
                if tag in ("insert", "replace"):
                    for k in range(j1, j2):
                        out.append(f"+{b_lines[k]}")
    return out
