"""Pike VM: simulates the NFA program over an input string.

Threads carry capture slots; the thread list is kept in priority order so
greedy/lazy alternatives and leftmost matches resolve exactly as in
backtracking engines, but in O(len(text) * len(program)) time with no
exponential blowup.
"""

from .nfa import char_in_ranges

WORD_RANGES = ((48, 57), (65, 90), (95, 95), (97, 122))


def _is_word(ch):
    return char_in_ranges(ord(ch), WORD_RANGES)


def assert_ok(kind, pos, text):
    if kind == "^":
        return pos == 0
    if kind == "$":
        return pos == len(text)
    w1 = pos > 0 and _is_word(text[pos - 1])
    w2 = pos < len(text) and _is_word(text[pos])
    if kind == "b":
        return w1 != w2
    # \B: as in Python's re, it never matches in an empty string.
    return w1 == w2 and len(text) > 0


def _add(lst, visited, prog, pc0, saves0, pos, text):
    """Add a thread, expanding epsilon transitions depth-first so that the
    resulting list order encodes thread priority. First arrival at a pc wins
    (per-step `visited` set), which also breaks empty-repeat loops."""
    stack = [(pc0, saves0)]
    while stack:
        pc, saves = stack.pop()
        if pc in visited:
            continue
        visited.add(pc)
        inst = prog[pc]
        op = inst.op
        if op == "jmp":
            stack.append((inst.x, saves))
        elif op == "split":
            stack.append((inst.y, saves))
            stack.append((inst.x, saves))  # x pops first: preferred branch
        elif op == "save":
            ns = saves.copy()
            ns[inst.slot] = pos
            stack.append((inst.x, ns))
        elif op == "assert":
            if assert_ok(inst.kind, pos, text):
                stack.append((inst.x, saves))
        else:  # char or match: a real (consuming/accepting) thread
            lst.append((pc, saves))


def run(prog, nslots, text, start=0, mode="match", observer=None,
        ban_empty_at=None):
    """Run the VM. mode is 'match' (anchored at start), 'fullmatch'
    (anchored both ends) or 'search' (scan forward). Returns the winning
    thread's capture slots, or None.

    ban_empty_at: position where an empty match is rejected (finditer's
    must-advance rule after a previous empty match, as in re).

    observer, if given, is called as observer(pos, clist) before each step —
    clist is the priority-ordered list of (pc, saves) threads."""
    matched = None
    clist, visited = [], set()
    _add(clist, visited, prog, 0, [None] * nslots, start, text)
    pos, n = start, len(text)
    while True:
        if observer is not None:
            observer(pos, clist)
        nlist, nvisited = [], set()
        ch = ord(text[pos]) if pos < n else None
        for pc, saves in clist:
            inst = prog[pc]
            if inst.op == "char":
                if ch is not None and char_in_ranges(ch, inst.ranges):
                    _add(nlist, nvisited, prog, pc + 1, saves, pos + 1, text)
            else:  # match
                if mode == "fullmatch" and pos != n:
                    continue  # this thread cannot extend; lower ones may
                if (ban_empty_at is not None and pos == ban_empty_at
                        and saves[0] == ban_empty_at):
                    continue  # banned empty match; lower threads may win
                matched = saves
                break  # cut lower-priority threads
        if pos >= n:
            break
        pos += 1
        if mode == "search" and matched is None:
            _add(nlist, nvisited, prog, 0, [None] * nslots, pos, text)
        elif not nlist:
            break  # searching keeps seeding; other modes are done
        clist, visited = nlist, nvisited
    return matched


class Match:
    """A successful match, re.Match-alike."""

    def __init__(self, pattern_obj, text, saves):
        self.re = pattern_obj
        self.string = text
        self._saves = saves

    def span(self, idx=0):
        s, e = self._saves[2 * idx], self._saves[2 * idx + 1]
        if s is None or e is None:
            return (-1, -1)
        return (s, e)

    def start(self, idx=0):
        return self.span(idx)[0]

    def end(self, idx=0):
        return self.span(idx)[1]

    def group(self, *idx):
        if not idx:
            idx = (0,)
        out = []
        for i in idx:
            if not 0 <= i <= self.re.ngroups:
                raise IndexError(f"no such group: {i}")
            s, e = self.span(i)
            out.append(None if s == -1 else self.string[s:e])
        return out[0] if len(out) == 1 else tuple(out)

    def groups(self, default=None):
        return tuple(
            self.group(i) if self.span(i) != (-1, -1) else default
            for i in range(1, self.re.ngroups + 1))

    def __repr__(self):
        return (f"<rxlab.Match span={self.span()!r} "
                f"group={self.group()!r}>")
