"""Merge-base discovery and line-based three-way (diff3-style) merging.

The merge walks the opcodes of base-vs-ours and base-vs-theirs
(computed with the Myers diff engine) together with two synchronized
pointers over base-coordinate space. At each base position it first
drains any zero-width `insert` opcodes anchored there (from either or
both sides — insertions are compared and conflict only if both sides
inserted *different* text at the same spot), then resolves the next
shared span of base content: if only one side diverged from base
there, that side wins silently; if both diverged to the *same* text,
that wins; otherwise it's a real conflict, marked `<<<<<<<`/`=======`/`>>>>>>>`.
"""

from dataclasses import dataclass, field

from .diff import get_opcodes


@dataclass
class MergeResult:
    text: str
    has_conflict: bool
    conflict_count: int = 0


def _conflict_block(ours_slice, theirs_slice, ours_label, theirs_label):
    out = [f"<<<<<<< {ours_label}\n"]
    out.append("".join(ours_slice))
    if ours_slice and not ours_slice[-1].endswith("\n"):
        out.append("\n")
    out.append("=======\n")
    out.append("".join(theirs_slice))
    if theirs_slice and not theirs_slice[-1].endswith("\n"):
        out.append("\n")
    out.append(f">>>>>>> {theirs_label}\n")
    return "".join(out)


def three_way_merge(base_text, ours_text, theirs_text, ours_label="ours", theirs_label="theirs"):
    base_lines = base_text.splitlines(keepends=True)
    ours_lines = ours_text.splitlines(keepends=True)
    theirs_lines = theirs_text.splitlines(keepends=True)

    ops_ours = get_opcodes(base_lines, ours_lines)
    ops_theirs = get_opcodes(base_lines, theirs_lines)

    i = j = 0
    pos = 0
    out = []
    has_conflict = False
    conflict_count = 0

    def side_slice(op, start, end, other_lines):
        tag = op[0]
        if tag == "equal":
            off = op[3] - op[1]
            return other_lines[start + off:end + off]
        return []  # delete: this side has nothing here

    while True:
        op_o = ops_ours[i] if i < len(ops_ours) else None
        op_t = ops_theirs[j] if j < len(ops_theirs) else None
        if op_o is None and op_t is None:
            break

        o_ins = op_o if op_o is not None and op_o[0] == "insert" and op_o[1] == pos else None
        t_ins = op_t if op_t is not None and op_t[0] == "insert" and op_t[1] == pos else None

        if o_ins is not None or t_ins is not None:
            o_text = ours_lines[o_ins[3]:o_ins[4]] if o_ins is not None else None
            t_text = theirs_lines[t_ins[3]:t_ins[4]] if t_ins is not None else None
            if o_ins is not None and t_ins is not None:
                if o_text == t_text:
                    out.append("".join(o_text))
                else:
                    has_conflict = True
                    conflict_count += 1
                    out.append(_conflict_block(o_text, t_text, ours_label, theirs_label))
                i += 1
                j += 1
            elif o_ins is not None:
                out.append("".join(o_text))
                i += 1
            else:
                out.append("".join(t_text))
                j += 1
            continue

        # No insert pending at `pos`: both sides must now offer a non-insert
        # (equal/delete) opcode starting exactly at `pos`, unless base is exhausted.
        if pos >= len(base_lines):
            break
        assert op_o is not None and op_o[1] <= pos < op_o[2], "ours opcodes desynced from base position"
        assert op_t is not None and op_t[1] <= pos < op_t[2], "theirs opcodes desynced from base position"

        end = min(op_o[2], op_t[2])
        base_slice = base_lines[pos:end]
        ours_slice = side_slice(op_o, pos, end, ours_lines)
        theirs_slice = side_slice(op_t, pos, end, theirs_lines)

        if ours_slice == base_slice and theirs_slice == base_slice:
            out.append("".join(base_slice))
        elif ours_slice == base_slice:
            out.append("".join(theirs_slice))
        elif theirs_slice == base_slice:
            out.append("".join(ours_slice))
        elif ours_slice == theirs_slice:
            out.append("".join(ours_slice))
        else:
            has_conflict = True
            conflict_count += 1
            out.append(_conflict_block(ours_slice, theirs_slice, ours_label, theirs_label))

        pos = end
        if op_o[2] == end:
            i += 1
        if op_t[2] == end:
            j += 1

    return MergeResult(text="".join(out), has_conflict=has_conflict, conflict_count=conflict_count)
