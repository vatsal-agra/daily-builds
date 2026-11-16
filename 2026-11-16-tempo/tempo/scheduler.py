"""Busy-interval algebra and a multi-timezone meeting-slot finder.

Everything is computed on aware UTC instants.  Each attendee has a time zone, working hours
(plus optional "stretch" hours they will tolerate in a pinch) and busy time, which may be
one-off blocks or recurring series (any Recurrence).  `find_slots` returns well-separated
candidate slots ranked by how kind they are to everyone's local clock.
"""
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .dates import DAY_CODES, DAY_NAMES
from .errors import TempoError
from .recur import Recurrence
from .tz import UTC, get_zone, resolve, fmt_offset

__all__ = ["Interval", "merge", "intersect", "subtract", "complement", "WorkHours", "Busy",
           "Attendee", "Slot", "find_slots", "explain_no_slots", "timeline"]


# ------------------------------------------------------------------ interval algebra
@dataclass(frozen=True, order=True)
class Interval:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise TempoError("Interval endpoints must be timezone-aware")
        if self.end < self.start:
            raise TempoError("Interval end is before start")

    @property
    def duration(self):
        return self.end - self.start


def merge(intervals):
    """Union: sorted, non-overlapping, touching intervals coalesced; empty ones dropped."""
    xs = sorted((i for i in intervals if i.end > i.start), key=lambda i: (i.start, i.end))
    out = []
    for i in xs:
        if out and i.start <= out[-1].end:
            if i.end > out[-1].end:
                out[-1] = Interval(out[-1].start, i.end)
        else:
            out.append(i)
    return out


def intersect(a, b):
    a, b = merge(a), merge(b)
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i].start, b[j].start), min(a[i].end, b[j].end)
        if lo < hi:
            out.append(Interval(lo, hi))
        if a[i].end < b[j].end:
            i += 1
        else:
            j += 1
    return out


def subtract(a, b):
    """a minus b."""
    a, b = merge(a), merge(b)
    out = []
    for iv in a:
        cur = iv.start
        for x in b:
            if x.end <= cur:
                continue
            if x.start >= iv.end:
                break
            if x.start > cur:
                out.append(Interval(cur, x.start))
            cur = max(cur, x.end)
            if cur >= iv.end:
                break
        if cur < iv.end:
            out.append(Interval(cur, iv.end))
    return out


def complement(intervals, window):
    return subtract([window], intervals)


# ------------------------------------------------------------------ working hours
_DAYSPEC = re.compile(r"^(?P<days>[A-Za-z, -]+?)\s+(?P<ranges>\d.*)$")


def _parse_hm(s, spec):
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", s.strip())
    if not m:
        raise TempoError(f"bad time {s!r} in hours spec {spec!r}")
    h, mi = int(m[1]), int(m[2] or 0)
    if (h, mi) == (24, 0):
        return 24 * 60
    if h > 23 or mi > 59:
        raise TempoError(f"time {s!r} out of range in hours spec {spec!r}")
    return h * 60 + mi


class WorkHours:
    """Weekly pattern of local time ranges.

        WorkHours.parse("Mon-Fri 09:00-12:00,13:00-17:00; Sat 10-14")
    """

    def __init__(self, table):
        self.table = {d: sorted(r) for d, r in table.items() if r}

    @classmethod
    def parse(cls, spec):
        table = {d: [] for d in range(7)}
        names = {c.lower(): i for i, c in enumerate(DAY_CODES)}
        names.update({n.lower(): i for i, n in enumerate(DAY_NAMES)})
        names.update({n[:3].lower(): i for i, n in enumerate(DAY_NAMES)})
        any_ = False
        for chunk in filter(None, (c.strip() for c in spec.split(";"))):
            m = _DAYSPEC.match(chunk)
            if not m:
                raise TempoError(f"bad hours spec {chunk!r} (expected e.g. 'Mon-Fri 09:00-17:00')")
            days = set()
            for tok in m["days"].replace(" ", "").split(","):
                if "-" in tok:
                    a, b = tok.split("-", 1)
                    if a.lower() not in names or b.lower() not in names:
                        raise TempoError(f"unknown day in {tok!r}")
                    i, j = names[a.lower()], names[b.lower()]
                    days.update(((i + k) % 7) for k in range(((j - i) % 7) + 1))
                else:
                    if tok.lower() not in names:
                        raise TempoError(f"unknown day {tok!r}")
                    days.add(names[tok.lower()])
            for rg in m["ranges"].split(","):
                if "-" not in rg:
                    raise TempoError(f"bad range {rg!r} in {chunk!r}")
                a, b = rg.split("-", 1)
                lo, hi = _parse_hm(a, chunk), _parse_hm(b, chunk)
                if hi <= lo:
                    raise TempoError(f"range {rg!r} must end after it starts (use two ranges "
                                     f"to cross midnight)")
                for d in days:
                    table[d].append((lo, hi))
                    any_ = True
        if not any_:
            raise TempoError("hours spec is empty")
        return cls(table)

    def intervals(self, zone, start, end):
        """Working Intervals (UTC) overlapping [start, end)."""
        zone = get_zone(zone)
        d = (start.astimezone(zone) - timedelta(days=1)).date()
        last = (end.astimezone(zone) + timedelta(days=1)).date()
        out = []
        while d <= last:
            for lo, hi in self.table.get(d.weekday(), ()):
                a = resolve(datetime(d.year, d.month, d.day) + timedelta(minutes=lo), zone)
                b = resolve(datetime(d.year, d.month, d.day) + timedelta(minutes=hi), zone)
                out.append(Interval(a.astimezone(UTC), b.astimezone(UTC)))
            d += timedelta(days=1)
        return merge(out)

    def describe(self):
        runs = {}
        for d, rs in self.table.items():
            runs.setdefault(tuple(rs), []).append(d)
        parts = []
        for rs, days in sorted(runs.items(), key=lambda kv: kv[1][0]):
            parts.append(f"{_days_str(days)} " + ",".join(f"{a//60:02d}:{a%60:02d}-{b//60:02d}:{b%60:02d}" for a, b in rs))
        return "; ".join(parts)


def _days_str(days):
    days = sorted(days)
    out, i = [], 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1] == days[j] + 1:
            j += 1
        out.append(DAY_NAMES[days[i]][:3] if i == j else
                   f"{DAY_NAMES[days[i]][:3]}-{DAY_NAMES[days[j]][:3]}")
        i = j + 1
    return ",".join(out)


# ------------------------------------------------------------------ attendees
@dataclass
class Busy:
    """A busy block: one-off (start, duration) or recurring (a Recurrence + duration)."""
    start: datetime = None
    duration: timedelta = None
    recurrence: Recurrence = None
    title: str = ""

    def intervals(self, lo, hi, zone):
        if self.duration is None or self.duration <= timedelta(0):
            raise TempoError(f"busy block {self.title!r} needs a positive duration")
        if self.recurrence is None:
            s = self.start if self.start.tzinfo else resolve(self.start, zone)
            s = s.astimezone(UTC)
            return [Interval(s, s + self.duration)] if (s < hi and s + self.duration > lo) else []
        occ = self.recurrence.between(lo - self.duration, hi)
        res = []
        for o in occ:
            s = (o if o.tzinfo else resolve(o, zone)).astimezone(UTC)
            res.append(Interval(s, s + self.duration))
        return res


@dataclass
class Attendee:
    name: str
    zone: object = "UTC"
    hours: WorkHours = None
    stretch: WorkHours = None
    busy: list = field(default_factory=list)
    optional: bool = False

    def __post_init__(self):
        if self.hours is None:
            self.hours = "Mon-Fri 09:00-17:00"

    def __setattr__(self, key, value):
        # accept strings / zone names on any assignment, not only at construction
        if key == "zone":
            value = get_zone(value)
        elif key in ("hours", "stretch") and isinstance(value, str):
            value = WorkHours.parse(value)
        object.__setattr__(self, key, value)

    def busy_intervals(self, lo, hi, buffer=timedelta(0)):
        xs = []
        for b in self.busy:
            if isinstance(b, Interval):
                xs.append(b)
            else:
                xs.extend(b.intervals(lo - buffer, hi + buffer, self.zone))
        return merge(Interval(i.start - buffer, i.end + buffer) for i in xs)


@dataclass
class Slot:
    start: datetime
    end: datetime
    score: float
    local: dict            # name -> (local start, local end, flag)
    optional_free: list
    optional_busy: list
    notes: list

    def render(self):
        lines = [f"{self.start.strftime('%a %Y-%m-%d %H:%M')}Z  → {self.end.strftime('%H:%M')}Z"
                 f"   score {self.score:.1f}"]
        for n, (a, b, flag) in self.local.items():
            lines.append(f"    {n:<12} {a.strftime('%a %H:%M')}–{b.strftime('%H:%M')} "
                         f"{a.tzname() or fmt_offset(a)}{'  (stretch)' if flag == 'stretch' else ''}")
        for n in self.optional_busy:
            lines.append(f"    {n:<12} unavailable (optional)")
        return "\n".join(lines)


def _contains(ivs, starts, s, e):
    i = bisect_right(starts, s) - 1
    return i >= 0 and ivs[i].start <= s and e <= ivs[i].end


def find_slots(attendees, window_start, window_end, duration, step=timedelta(minutes=15),
               buffer=timedelta(0), allow_stretch=False, min_optional=0, limit=5,
               min_separation=None, sweet=(10 * 60, 16 * 60)):
    """Rank meeting slots of `duration` inside [window_start, window_end].

    Required attendees must be inside their working hours (or stretch hours when
    allow_stretch) and free of busy time (+`buffer` either side).  Optional attendees that are
    free earn a bonus; `min_optional` of them must be free.  Score is lower-is-better:
      +40 per attendee in stretch hours, + hours outside the 10:00-16:00 sweet spot at their
      local clock, + a fairness term (worst attendee's discomfort), - 8 per free optional
      attendee, + a tiny lateness tiebreak.
    The returned slots are greedily non-overlapping (>= min_separation apart).
    """
    if not attendees:
        raise TempoError("need at least one attendee")
    for dt in (window_start, window_end):
        if dt.tzinfo is None:
            raise TempoError("window_start / window_end must be timezone-aware")
    if window_end <= window_start:
        raise TempoError("window_end must be after window_start")
    if duration <= timedelta(0) or step <= timedelta(0):
        raise TempoError("duration and step must be positive")
    names = [a.name for a in attendees]
    if len(set(names)) != len(names):
        raise TempoError("attendee names must be unique")
    if not any(not a.optional for a in attendees):
        raise TempoError("at least one attendee must be required")
    lo, hi = window_start.astimezone(UTC), window_end.astimezone(UTC)
    win = Interval(lo, hi)

    prepared = {}
    for a in attendees:
        core = intersect(a.hours.intervals(a.zone, lo, hi), [win])
        stretch = []
        if allow_stretch and a.stretch is not None:
            stretch = intersect(a.stretch.intervals(a.zone, lo, hi), [win])
        allowed = merge(core + stretch)
        busy = a.busy_intervals(lo, hi, buffer)
        free = subtract(allowed, busy)
        core_free = subtract(core, busy)
        prepared[a.name] = (free, [i.start for i in free], core_free, [i.start for i in core_free])

    # grid aligned to whole `step` multiples since the Unix epoch (so slots start on :00/:15...)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    step_s = int(step.total_seconds())
    first = int((lo - epoch).total_seconds())
    first += (-first) % step_s
    cands = []
    t = epoch + timedelta(seconds=first)
    while t + duration <= hi:
        e = t + duration
        ok, score, local, ofree, obusy, notes, worst = True, 0.0, {}, [], [], [], 0.0
        for a in attendees:
            free, fst, cfree, cst = prepared[a.name]
            if not _contains(free, fst, t, e):
                if a.optional:
                    obusy.append(a.name)
                    continue
                ok = False
                break
            in_core = _contains(cfree, cst, t, e)
            ls, le = t.astimezone(a.zone), e.astimezone(a.zone)
            pen = 0.0 if in_core else 40.0
            mid = (ls.hour * 60 + ls.minute + (le.hour * 60 + le.minute + (1440 if le.date() > ls.date() else 0))) / 2
            mid %= 1440
            dist = max(sweet[0] - mid, mid - sweet[1], 0) / 60.0
            pen += dist
            if a.optional:
                ofree.append(a.name)
                score -= 8 if in_core else 2
            else:
                score += pen
                worst = max(worst, pen)
            local[a.name] = (ls, le, "core" if in_core else "stretch")
            if not in_core:
                notes.append(f"{a.name} is outside core hours")
        if not ok:
            t += step
            continue
        if len(ofree) < min_optional:
            t += step
            continue
        score += worst + (t - lo).total_seconds() / 86400.0 * 0.05
        cands.append(Slot(t, e, score, local, ofree, obusy, notes))
        t += step
    cands.sort(key=lambda s: (s.score, s.start))
    sep = duration if min_separation is None else min_separation
    chosen = []
    for c in cands:
        if all(c.end + sep <= x.start or x.end + sep <= c.start for x in chosen):
            chosen.append(c)
            if len(chosen) >= limit:
                break
    return chosen


def explain_no_slots(attendees, window_start, window_end, duration, buffer=timedelta(0),
                     allow_stretch=False):
    """Human-readable diagnosis for an empty result."""
    lo, hi = window_start.astimezone(UTC), window_end.astimezone(UTC)
    win = Interval(lo, hi)
    req = [a for a in attendees if not a.optional]
    lines = []
    common = [win]
    for a in req:
        h = intersect(a.hours.intervals(a.zone, lo, hi), [win])
        if allow_stretch and a.stretch is not None:
            h = merge(h + intersect(a.stretch.intervals(a.zone, lo, hi), [win]))
        common = intersect(common, h)
    total = sum((i.duration for i in common), timedelta(0))
    if not any(i.duration >= duration for i in common):
        lines.append(f"working hours of {', '.join(a.name for a in req)} never overlap for "
                     f"{int(duration.total_seconds() // 60)} min in this window"
                     f" (longest shared stretch: "
                     f"{int(max((i.duration for i in common), default=timedelta(0)).total_seconds() // 60)} min)")
        if not allow_stretch:
            lines.append("try allow_stretch=True, a longer window, or a shorter meeting")
        return lines
    lines.append(f"working hours overlap for {total} in total, but busy time removes every "
                 f"{int(duration.total_seconds() // 60)}-minute opening")
    for a in req:
        busy = a.busy_intervals(lo, hi, buffer)
        blocked = sum((i.duration for i in intersect(common, busy)), timedelta(0))
        lines.append(f"  {a.name}: blocks {blocked} of the shared hours")
    return lines


def timeline(attendees, day, width=48, zone=UTC):
    """ASCII chart of one day (in `zone`): '#' working, '.' off, 'x' busy. One row per attendee."""
    zone = get_zone(zone)
    start = resolve(datetime(day.year, day.month, day.day), zone).astimezone(UTC)
    end = resolve(datetime(day.year, day.month, day.day) + timedelta(days=1), zone).astimezone(UTC)
    span = (end - start) / width
    lines = ["".ljust(14) + "".join(str((i * 24 // width) % 10) if (i * 24) % width == 0 else " "
                                    for i in range(width))]
    for a in attendees:
        work = intersect(a.hours.intervals(a.zone, start, end), [Interval(start, end)])
        busy = a.busy_intervals(start, end)
        row = []
        for i in range(width):
            c = Interval(start + span * i, start + span * (i + 1))
            mid = c.start + span / 2
            ch = "."
            if any(w.start <= mid < w.end for w in work):
                ch = "#"
            if any(b.start <= mid < b.end for b in busy):
                ch = "x"
            row.append(ch)
        lines.append(f"{a.name[:13]:<14}" + "".join(row))
    return "\n".join(lines)
