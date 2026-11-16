"""Five-field cron expressions: next/prev/iteration in a time zone.

Syntax: `min hour day-of-month month day-of-week`, plus
  * lists `1,15`, ranges `1-5`, steps `*/10` `5-30/5` `5/15`, names (JAN-DEC, SUN-SAT), `?`
  * day-of-month `L` (last day), `L-3` (third from last)
  * day-of-week `5L` (last Friday), `MON#2` (second Monday); 0 and 7 are both Sunday
  * aliases @yearly @annually @monthly @weekly @daily @midnight @hourly
Like Vixie cron, when BOTH day fields are restricted a day matches if EITHER does.
Fire times are wall-clock times in `zone`; nonexistent ones (spring-forward gap) fire at the
first moment after the gap and a repeated hour (fall back) fires once.
"""
from datetime import datetime, timedelta, date

from .dates import DAY_CODES, days_in_month, nth_weekday_in
from .errors import CronError
from .tz import UTC, get_zone, resolve, wall

ALIASES = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
           "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
           "@hourly": "0 * * * *"}
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_DOW = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_FIELDS = [("minute", 0, 59, None), ("hour", 0, 23, None), ("day-of-month", 1, 31, None),
           ("month", 1, 12, _MON), ("day-of-week", 0, 7, _DOW)]


def _num(tok, lo, hi, names, fname, expr, pos):
    t = tok.upper()
    if names and t in names:
        return names.index(t) + (1 if fname == "month" else 0)
    if not t.isdigit():
        raise CronError(f"{fname}: cannot read {tok!r}", expr, pos)
    n = int(t)
    if not lo <= n <= hi:
        raise CronError(f"{fname}: {n} out of range {lo}-{hi}", expr, pos)
    return n


def _parse_field(text, idx, expr, pos):
    fname, lo, hi, names = _FIELDS[idx]
    vals, specials = set(), []
    starts_star = text.startswith("*") or text.startswith("?")
    off = pos
    for item in text.split(","):
        if item == "":
            raise CronError(f"{fname}: empty list item", expr, off)
        step = 1
        body = item
        if "/" in item:
            body, st = item.split("/", 1)
            if not st.isdigit() or int(st) < 1:
                raise CronError(f"{fname}: bad step {st!r}", expr, off + len(body) + 1)
            step = int(st)
        if idx == 2 and body.upper() == "L":
            specials.append(("L", 0))
        elif idx == 2 and body.upper().startswith("L-") and body[2:].isdigit():
            n = int(body[2:])
            if not 1 <= n <= 30:
                raise CronError("day-of-month: L-n needs n between 1 and 30", expr, off)
            specials.append(("L", n))
        elif idx == 4 and "#" in body:
            d, n = body.split("#", 1)
            dn = _num(d, 0, 7, names, fname, expr, off) % 7
            if not n.isdigit() or not 1 <= int(n) <= 5:
                raise CronError("day-of-week: #n needs n between 1 and 5", expr, off)
            specials.append(("nth", dn, int(n)))
        elif idx == 4 and body.upper().endswith("L") and len(body) > 1:
            dn = _num(body[:-1], 0, 7, names, fname, expr, off) % 7
            specials.append(("nth", dn, -1))
        else:
            if body in ("*", "?"):
                a, b = lo, hi
            elif "-" in body:
                x, y = body.split("-", 1)
                a, b = (_num(x, lo, hi, names, fname, expr, off),
                        _num(y, lo, hi, names, fname, expr, off + len(x) + 1))
                if a > b:
                    raise CronError(f"{fname}: range {body} runs backwards", expr, off)
            else:
                a = _num(body, lo, hi, names, fname, expr, off)
                b = hi if "/" in item else a
            for v in range(a, b + 1, step):
                vals.add(v)
        off += len(item) + 1
    if idx == 4:
        vals = {v % 7 for v in vals}
    return vals, specials, starts_star


class Cron:
    def __init__(self, expr, zone="UTC"):
        self.expr = expr
        src = expr.strip()
        if src.startswith("@"):
            if src.lower() not in ALIASES:
                raise CronError(f"unknown alias {src!r}", expr, 0)
            src = ALIASES[src.lower()]
        parts = src.split()
        if len(parts) != 5:
            raise CronError(f"expected 5 fields (minute hour day month weekday), got {len(parts)}",
                            expr, 0)
        self.zone = get_zone(zone)
        parsed, pos = [], 0
        for i, p in enumerate(parts):
            at = src.index(p, pos)
            parsed.append(_parse_field(p, i, src, at))
            pos = at + len(p)
        (self.minutes, _, _), (self.hours, _, _) = parsed[0][:3], parsed[1][:3]
        self.dom, self.dom_sp, self.dom_star = parsed[2]
        self.months, _, _ = parsed[3]
        self.dow, self.dow_sp, self.dow_star = parsed[4]
        self._mins = sorted(self.minutes)
        self._hrs = sorted(self.hours)

    # ----- matching
    def _day_ok(self, d):
        dom_ok = d.day in self.dom or any(
            s[0] == "L" and d.day == days_in_month(d.year, d.month) - s[1] for s in self.dom_sp)
        dow_ok = d.weekday() == 6 and 0 in self.dow or (d.weekday() + 1) % 7 in self.dow
        if not dow_ok:
            for s in self.dow_sp:
                n, m = nth_weekday_in(d, "month")
                if (d.weekday() + 1) % 7 == s[1] and s[2] in (n, m):
                    dow_ok = True
        # Vixie rule: if either day field starts with '*' the two are ANDed (the starred one
        # may still carry a step, e.g. */4); only when both are restricted do they OR.
        if (self.dom_star and not self.dom_sp) or (self.dow_star and not self.dow_sp):
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def _month_ok(self, d):
        return d.month in self.months

    def matches(self, dt):
        """Does the wall-clock minute containing `dt` fire?"""
        w = wall(dt, self.zone) if dt.tzinfo is not None else dt
        return (w.minute in self.minutes and w.hour in self.hours and self._month_ok(w)
                and self._day_ok(w.date()))

    # ----- wall-clock search
    def _next_wall(self, t0):
        """Smallest matching naive minute >= t0."""
        d = t0.date()
        first = True
        limit = d.year + 120
        while d.year <= limit:
            if not self._month_ok(d):
                d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
                first = False
                continue
            if self._day_ok(d):
                for h in self._hrs:
                    if first and h < t0.hour:
                        continue
                    for m in self._mins:
                        if first and h == t0.hour and m < t0.minute:
                            continue
                        return datetime(d.year, d.month, d.day, h, m)
            d += timedelta(days=1)
            first = False
        raise CronError(f"{self.expr!r} never fires")

    def _prev_wall(self, t0):
        """Largest matching naive minute <= t0."""
        d = t0.date()
        first = True
        limit = d.year - 120
        while d.year >= limit:
            if not self._month_ok(d):
                d = d.replace(day=1) - timedelta(days=1)
                first = False
                continue
            if self._day_ok(d):
                for h in reversed(self._hrs):
                    if first and h > t0.hour:
                        continue
                    for m in reversed(self._mins):
                        if first and h == t0.hour and m > t0.minute:
                            continue
                        return datetime(d.year, d.month, d.day, h, m)
            d -= timedelta(days=1)
            first = False
        raise CronError(f"{self.expr!r} never fired")

    # ----- public
    def _coerce(self, dt):
        if dt.tzinfo is None:
            return resolve(dt, self.zone).astimezone(UTC)
        return dt.astimezone(UTC)

    _MARGIN = timedelta(hours=3)

    def _near_transition(self, a):
        """True when a DST offset change lies within a few hours of instant `a`."""
        if self.zone is UTC:
            return False
        return (a - self._MARGIN).astimezone(self.zone).utcoffset() != \
            (a + self._MARGIN).astimezone(self.zone).utcoffset()

    def next(self, after):
        """First fire instant strictly after `after` (aware, in the cron's zone).

        Wall times swallowed by a spring-forward gap fire just after the gap, so around a
        transition we also look at walls slightly before `after` whose shifted instant is later.
        """
        a = self._coerce(after)
        near = self._near_transition(a)
        wa = wall(a, self.zone).replace(second=0, microsecond=0)
        t = wa - self._MARGIN if near else wa + timedelta(minutes=1)
        best = None
        while True:
            w = self._next_wall(t)
            if best is not None and w > wall(best, self.zone):
                return best
            r = resolve(w, self.zone, "forward")
            k = r.astimezone(UTC)
            if k > a and (best is None or k < best.astimezone(UTC)):
                best = r
                if not near:
                    return best
            t = w + timedelta(minutes=1)

    def prev(self, before):
        """Last fire instant strictly before `before`."""
        b = self._coerce(before)
        near = self._near_transition(b)
        wb = wall(b, self.zone)
        t = wb.replace(second=0, microsecond=0)
        if near:
            t += self._MARGIN
        elif not (wb.second or wb.microsecond):
            t -= timedelta(minutes=1)
        best = None
        while True:
            w = self._prev_wall(t)
            if best is not None and w < wall(best, self.zone) - self._MARGIN:
                return best
            r = resolve(w, self.zone, "forward")
            k = r.astimezone(UTC)
            if k < b and (best is None or k > best.astimezone(UTC)):
                best = r
                if not near:
                    return best
            t = w - timedelta(minutes=1)

    def iter(self, start):
        cur = start
        while True:
            cur = self.next(cur)
            yield cur

    def take(self, start, n):
        out, cur = [], start
        for _ in range(n):
            cur = self.next(cur)
            out.append(cur)
        return out

    def between(self, start, end):
        out, cur = [], self.next(self._coerce(start) - timedelta(microseconds=1))
        e = self._coerce(end)
        while cur.astimezone(UTC) <= e:
            out.append(cur)
            cur = self.next(cur)
        return out
