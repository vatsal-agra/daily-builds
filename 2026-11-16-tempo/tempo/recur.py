"""Zoned recurrence: an RRULE + DTSTART + zone + EXDATE/RDATE -> a lazy, sorted stream of instants."""
import heapq
from datetime import date, datetime, timedelta

from .errors import TempoError
from .rrule import Rule, expand_wall, parse_rrule
from .tz import UTC, get_zone, resolve, wall, to_utc


class Recurrence:
    """A recurring series.

    dtstart   naive (wall clock in `zone`) or aware datetime.  A naive dtstart with no zone is a
              *floating* series and yields naive datetimes.
    zone      IANA name / tzinfo.  Defaults to dtstart's own tzinfo.
    exdates   instants (or naive walls in `zone`) removed from the series.
    rdates    extra instants added to the series.
    gap       'forward' (default; nonexistent wall times move past the gap) or 'skip'.
    rfc_dtstart  when True (default) DTSTART is always the first instance, as RFC 5545 says,
              even if the rule alone would not generate it.
    """

    def __init__(self, rule, dtstart, zone=None, exdates=(), rdates=(), gap="forward",
                 rfc_dtstart=True):
        self.rule = parse_rrule(rule) if isinstance(rule, str) else rule
        if not isinstance(self.rule, Rule):
            raise TempoError("rule must be an RRULE string or Rule")
        if gap not in ("forward", "skip"):
            raise TempoError("gap must be 'forward' or 'skip'")
        if isinstance(dtstart, date) and not isinstance(dtstart, datetime):
            dtstart = datetime(dtstart.year, dtstart.month, dtstart.day)
        if zone is None and dtstart.tzinfo is not None:
            zone = dtstart.tzinfo
        self.zone = get_zone(zone) if zone is not None else None
        if self.zone is None and dtstart.tzinfo is not None:
            self.zone = dtstart.tzinfo
        self.floating = self.zone is None
        self.gap = gap
        self.rfc_dtstart = rfc_dtstart
        self.dtstart_wall = (wall(dtstart, self.zone) if dtstart.tzinfo is not None
                             else dtstart.replace(microsecond=0))
        self.dtstart = self._res(self.dtstart_wall)
        self.exdates = {self._norm(e) for e in exdates}
        self.rdates = sorted({self._norm(r) for r in rdates})

    # -- helpers
    def _res(self, w):
        if self.floating:
            return w
        return resolve(w, self.zone, self.gap)

    def _norm(self, dt):
        """Key used to compare instants: aware UTC (or naive for floating series)."""
        if self.floating:
            if dt.tzinfo is not None:
                raise TempoError("floating series cannot take aware EXDATE/RDATE")
            return dt
        if dt.tzinfo is None:
            r = resolve(dt, self.zone, "forward")
            return r.astimezone(UTC)
        return dt.astimezone(UTC)

    def _key(self, dt):
        return dt if self.floating else dt.astimezone(UTC)

    def _until_limits(self):
        """(loose wall limit for expansion, exact instant limit)."""
        u = self.rule.until
        if u is None:
            return None, None
        if isinstance(u, datetime):
            if u.tzinfo is None:
                w = u
                inst = self._res(w) if not self.floating else w
                return w, inst
            if self.floating:
                raise TempoError("UNTIL is in UTC but the series is floating (no zone)")
            w = wall(u, self.zone)
            return w + timedelta(days=1), u.astimezone(UTC)
        # date-valued UNTIL: through the end of that day
        w = datetime(u.year, u.month, u.day, 23, 59, 59)
        return w, (w if self.floating else resolve(w, self.zone, "forward").astimezone(UTC))

    # -- iteration
    def _main(self):
        loose, exact = self._until_limits()
        walls = expand_wall(self.rule, self.dtstart_wall, until=loose,
                            include_dtstart=self.rfc_dtstart)
        if self.floating:
            for w in walls:
                if exact is not None and w > exact:
                    return
                yield w
            return
        heap, seen, last = [], set(), None
        for w in walls:
            r = resolve(w, self.zone, self.gap)
            if r is not None:
                k = r.astimezone(UTC)
                if exact is not None and k > exact:
                    continue
                if k not in seen and (last is None or k > last):
                    seen.add(k)
                    heapq.heappush(heap, (k, r))
            while heap and wall(heap[0][1], self.zone) <= w:
                k, r = heapq.heappop(heap)
                seen.discard(k)
                last = k
                yield r
        while heap:
            k, r = heapq.heappop(heap)
            yield r

    def __iter__(self):
        main = self._main()
        if not self.rdates:
            merged = ((self._key(x), x) for x in main)
        else:
            rd = ((self._key(x), x) for x in self._rdate_objs())
            merged = heapq.merge(((self._key(x), x) for x in main), rd, key=lambda p: p[0])
        prev = None
        for k, x in merged:
            if k == prev:
                continue
            prev = k
            if k in self.exdates:
                continue
            yield x

    def _rdate_objs(self):
        for r in self.rdates:
            yield r if self.floating else r.astimezone(self.zone)

    # -- queries
    def take(self, n):
        out = []
        for x in self:
            if len(out) >= n:
                break
            out.append(x)
        return out

    def _cmp(self, dt):
        if self.floating:
            return dt
        if dt.tzinfo is None:
            return resolve(dt, self.zone).astimezone(UTC)
        return dt.astimezone(UTC)

    def between(self, start, end, inclusive=True):
        a, b = self._cmp(start), self._cmp(end)
        out = []
        for x in self:
            k = self._key(x)
            if k > b or (k == b and not inclusive):
                break
            if k > a or (k == a and inclusive):
                out.append(x)
        return out

    def after(self, dt, inclusive=False):
        a = self._cmp(dt)
        for x in self:
            k = self._key(x)
            if k > a or (inclusive and k == a):
                return x
        return None

    def before(self, dt, inclusive=False):
        a = self._cmp(dt)
        res = None
        for x in self:
            k = self._key(x)
            if k > a or (k == a and not inclusive):
                break
            res = x
        return res

    def count(self, limit=1_000_000):
        """Number of occurrences of a finite series (raises if it exceeds `limit`)."""
        n = 0
        for _ in self:
            n += 1
            if n > limit:
                raise TempoError("series is infinite or longer than limit")
        return n
