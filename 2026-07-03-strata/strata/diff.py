"""Myers O(ND) diff: shortest edit script between two sequences, plus a
unified-diff renderer.

This is the real algorithm (Myers, 1986) — it explores diagonals of the
edit graph in increasing order of edit distance D and stops at the
first D for which some diagonal reaches the bottom-right corner, which
is provably the shortest edit script. That's O((N+M)D) time, versus the
O(N*M) a naive dynamic-programming LCS table would cost.
"""


def _shortest_edit_trace(a, b):
    """Forward Myers pass. Returns (trace, d) where trace[d] is a snapshot
    of the diagonal-endpoint array V as it stood *before* round d ran
    (i.e. the state round d's computation reads from), and d is the edit
    distance of the shortest edit script."""
    n, m = len(a), len(b)
    max_d = n + m
    offset = max_d
    v = [0] * (2 * max_d + 1) if max_d > 0 else [0]
    trace = []
    for d in range(max_d + 1):
        trace.append(v.copy())
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
                x = v[offset + k + 1]
            else:
                x = v[offset + k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[offset + k] = x
            if x >= n and y >= m:
                return trace, d, offset
    # unreachable: d=max_d always resolves the full path
    raise AssertionError("Myers diff failed to converge")


def _backtrack(a, b, trace, d, offset):
    x, y = len(a), len(b)
    edits = []  # built end-to-start, reversed at the end
    for D in range(d, 0, -1):
        v = trace[D]
        k = x - y
        down = (k == -D) or (k != D and v[offset + k - 1] < v[offset + k + 1])
        prev_k = k + 1 if down else k - 1
        prev_x = v[offset + prev_k]
        prev_y = prev_x - prev_k
        interm_x, interm_y = (prev_x, prev_y + 1) if down else (prev_x + 1, prev_y)
        while x > interm_x and y > interm_y:
            edits.append("equal")
            x, y = x - 1, y - 1
        edits.append("insert" if down else "delete")
        x, y = prev_x, prev_y
    while x > 0 and y > 0:
        edits.append("equal")
        x, y = x - 1, y - 1
    edits.reverse()
    return edits


def diff_tags(a, b):
    """Return the raw sequence of per-element tags ('equal'/'insert'/'delete')
    describing the shortest edit script turning list `a` into list `b`."""
    if a == b:
        return ["equal"] * len(a)
    trace, d, offset = _shortest_edit_trace(a, b)
    return _backtrack(a, b, trace, d, offset)


def get_opcodes(a, b):
    """Group the tag sequence into (tag, a1, a2, b1, b2) ranges, matching
    the shape of difflib.SequenceMatcher.get_opcodes()."""
    tags = diff_tags(a, b)
    opcodes = []
    ai = bi = 0
    i = 0
    n = len(tags)
    while i < n:
        tag = tags[i]
        j = i
        while j < n and tags[j] == tag:
            j += 1
        count = j - i
        if tag == "equal":
            opcodes.append(("equal", ai, ai + count, bi, bi + count))
            ai += count
            bi += count
        elif tag == "delete":
            opcodes.append(("delete", ai, ai + count, bi, bi))
            ai += count
        else:  # insert
            opcodes.append(("insert", ai, ai, bi, bi + count))
            bi += count
        i = j
    return opcodes


def _group_opcodes(opcodes, context):
    opcodes = list(opcodes)
    if not opcodes:
        return []
    if opcodes[0][0] == "equal":
        tag, i1, i2, j1, j2 = opcodes[0]
        opcodes[0] = (tag, max(i1, i2 - context), i2, max(j1, j2 - context), j2)
    if opcodes[-1][0] == "equal":
        tag, i1, i2, j1, j2 = opcodes[-1]
        opcodes[-1] = (tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context))

    groups = []
    group = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal" and i2 - i1 > 2 * context:
            group.append((tag, i1, min(i2, i1 + context), j1, min(j2, j1 + context)))
            groups.append(group)
            group = []
            i1 = max(i1, i2 - context)
            j1 = max(j1, j2 - context)
        group.append((tag, i1, i2, j1, j2))
    if group and not (len(group) == 1 and group[0][0] == "equal"):
        groups.append(group)
    return groups


def _hunk_header(a1, a2, b1, b2):
    def fmt(start, length):
        if length == 1:
            return f"{start + 1}"
        return f"{start + 1},{length}"
    return f"@@ -{fmt(a1, a2 - a1)} +{fmt(b1, b2 - b1)} @@\n"


def unified_diff(a_lines, b_lines, a_label="a", b_label="b", context=3):
    """Render a unified diff (list of text lines, each already ending in
    '\\n' except possibly the very last). Returns [] if a_lines == b_lines."""
    if a_lines == b_lines:
        return []
    opcodes = get_opcodes(a_lines, b_lines)
    groups = _group_opcodes(opcodes, context)
    if not groups:
        return []
    out = [f"--- {a_label}\n", f"+++ {b_label}\n"]
    for group in groups:
        a1, a2 = group[0][1], group[-1][2]
        b1, b2 = group[0][3], group[-1][4]
        out.append(_hunk_header(a1, a2, b1, b2))
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in a_lines[i1:i2]:
                    out.append(_with_marker(" " + line))
            else:
                if tag == "delete":
                    for line in a_lines[i1:i2]:
                        out.append(_with_marker("-" + line))
                else:
                    for line in b_lines[j1:j2]:
                        out.append(_with_marker("+" + line))
    return out


def _with_marker(line):
    if line.endswith("\n"):
        return line
    return line + "\n\\ No newline at end of file\n"


def split_lines(text):
    """Split text into lines keeping line endings, the unit unified_diff works over."""
    if text == "":
        return []
    return text.splitlines(keepends=True)
