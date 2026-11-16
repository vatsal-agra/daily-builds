"""RFC 5545 RRULE: parser, validator and expander.

Expansion happens in *floating wall-clock time* (naive datetimes), period by period
(a year, a month, a week, a day, an hour ...), following the RFC's candidate-set model:

  1. the period yields a pool of candidate days (the whole year/month/week, or the single day);
  2. every BYMONTH/BYWEEKNO/BYYEARDAY/BYMONTHDAY/BYDAY part filters that pool
     (for a part coarser than FREQ this is the RFC's "expand"; finer parts "limit");
  3. times of day come from BYHOUR/BYMINUTE/BYSECOND (defaults from DTSTART);
  4. BYSETPOS selects from the sorted set of the whole period.

Zone handling lives in recur.py; nothing here knows about time zones.
"""
import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from .dates import (DAY_CODES, days_in_month, days_in_year, nth_weekday_in, week_of,
                    week_start, year_dates, month_dates, yearday)
from .errors import RRuleError

FREQS = ["YEARLY", "MONTHLY", "WEEKLY", "DAILY", "HOURLY", "MINUTELY", "SECONDLY"]
_FRANK = {f: i for i, f in enumerate(FREQS)}
_DAY_IDX = {c: i for i, c in enumerate(DAY_CODES)}

# Safety valve: consecutive empty periods tolerated before the rule is declared exhausted
# (e.g. FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30 never matches).
_EMPTY_LIMIT = {"YEARLY": 9000, "MONTHLY": 110000, "WEEKLY": 480000, "DAILY": 3_300_000,
                "HOURLY": 3_000_000, "MINUTELY": 3_000_000, "SECONDLY": 3_000_000}
MAX_YEAR = 9990  # expansion stops here (keeps week-number math clear of date.max)
_MONTH_MAX = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


@dataclass(frozen=True)
class Rule:
    freq: str
    interval: int = 1
    count: int = None
    until: object = None          # date | naive datetime | aware datetime | None
    wkst: int = 0                 # 0=Monday
    bysecond: tuple = ()
    byminute: tuple = ()
    byhour: tuple = ()
    byday: tuple = ()             # ((ordinal|0, weekday), ...)
    bymonthday: tuple = ()
    byyearday: tuple = ()
    byweekno: tuple = ()
    bymonth: tuple = ()
    bysetpos: tuple = ()

    def to_string(self):
        parts = [f"FREQ={self.freq}"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.count is not None:
            parts.append(f"COUNT={self.count}")
        if self.until is not None:
            parts.append("UNTIL=" + _fmt_until(self.until))
        if self.wkst != 0:
            parts.append(f"WKST={DAY_CODES[self.wkst]}")
        for name, vals in (("BYMONTH", self.bymonth), ("BYWEEKNO", self.byweekno),
                           ("BYYEARDAY", self.byyearday), ("BYMONTHDAY", self.bymonthday)):
            if vals:
                parts.append(name + "=" + ",".join(map(str, vals)))
        if self.byday:
            parts.append("BYDAY=" + ",".join(
                (str(o) if o else "") + DAY_CODES[w] for o, w in self.byday))
        for name, vals in (("BYHOUR", self.byhour), ("BYMINUTE", self.byminute),
                           ("BYSECOND", self.bysecond), ("BYSETPOS", self.bysetpos)):
            if vals:
                parts.append(name + "=" + ",".join(map(str, vals)))
        return ";".join(parts)

    __str__ = to_string

    def with_(self, **kw):
        return replace(self, **kw)


def _fmt_until(u):
    if isinstance(u, datetime):
        if u.tzinfo is not None:
            from .tz import UTC
            return u.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        return u.strftime("%Y%m%dT%H%M%S")
    return u.strftime("%Y%m%d")


def parse_until(text, source=None, pos=0):
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z?))?", text)
    if not m:
        raise RRuleError(f"bad UNTIL value {text!r} (expected YYYYMMDD or YYYYMMDDTHHMMSS[Z])",
                         source, pos)
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    try:
        if m[4] is None:
            return date(y, mo, d)
        dt = datetime(y, mo, d, int(m[4]), int(m[5]), int(m[6]))
    except ValueError as e:
        raise RRuleError(f"invalid UNTIL date: {e}", source, pos)
    if m[7]:
        from .tz import UTC
        dt = dt.replace(tzinfo=UTC)
    return dt


def _ints(val, name, lo, hi, source, pos, allow_neg=False, allow_zero=True):
    out = []
    off = pos
    for tok in val.split(","):
        if not re.fullmatch(r"[+-]?\d+", tok):
            raise RRuleError(f"{name} expects integers, got {tok!r}", source, off)
        n = int(tok)
        if not allow_neg and n < 0:
            raise RRuleError(f"{name} does not allow negative values ({n})", source, off)
        if (n == 0 and not allow_zero) or not (lo <= abs(n) <= hi or (n == 0 and allow_zero and lo == 0)):
            rng = f"{lo}..{hi}" + (" (or negated)" if allow_neg else "")
            hint = " (leap seconds are not supported)" if (name == "BYSECOND" and n == 60) else ""
            raise RRuleError(f"{name} value {n} out of range {rng}{hint}", source, off)
        out.append(n)
        off += len(tok) + 1
    return tuple(sorted(set(out)))


def parse_rrule(text):
    """Parse 'FREQ=WEEKLY;BYDAY=MO,WE' (an optional leading 'RRULE:' is accepted)."""
    src = text.strip()
    body = src[6:] if src.upper().startswith("RRULE:") else src
    base = len(src) - len(body)
    if not body:
        raise RRuleError("empty rule", src, 0)
    kv = {}
    pos = base
    for part in body.split(";"):
        if part == "":
            raise RRuleError("empty rule part (stray ';')", src, pos)
        if "=" not in part:
            raise RRuleError(f"expected NAME=VALUE, got {part!r}", src, pos)
        k, v = part.split("=", 1)
        k = k.upper()
        if k in kv:
            raise RRuleError(f"duplicate {k}", src, pos)
        if v == "":
            raise RRuleError(f"{k} has no value", src, pos + len(k) + 1)
        kv[k] = (v, pos + len(k) + 1)
        pos += len(part) + 1
    known = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "WKST", "BYSECOND", "BYMINUTE", "BYHOUR",
             "BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH", "BYSETPOS"}
    for k, (v, p) in kv.items():
        if k not in known:
            raise RRuleError(f"unknown rule part {k}", src, p - len(k) - 1)
    if "FREQ" not in kv:
        raise RRuleError("FREQ is required", src, base)
    f, fp = kv["FREQ"]
    freq = f.upper()
    if freq not in _FRANK:
        raise RRuleError(f"unknown FREQ {f!r} (expected one of {', '.join(FREQS)})", src, fp)
    if "COUNT" in kv and "UNTIL" in kv:
        raise RRuleError("COUNT and UNTIL are mutually exclusive", src, kv["UNTIL"][1] - 6)

    kw = {"freq": freq}
    if "INTERVAL" in kv:
        v, p = kv["INTERVAL"]
        if not re.fullmatch(r"\d+", v) or int(v) < 1:
            raise RRuleError(f"INTERVAL must be a positive integer, got {v!r}", src, p)
        kw["interval"] = int(v)
    if "COUNT" in kv:
        v, p = kv["COUNT"]
        if not re.fullmatch(r"\d+", v) or int(v) < 1:
            raise RRuleError(f"COUNT must be a positive integer, got {v!r}", src, p)
        kw["count"] = int(v)
    if "UNTIL" in kv:
        v, p = kv["UNTIL"]
        kw["until"] = parse_until(v, src, p)
    if "WKST" in kv:
        v, p = kv["WKST"]
        if v.upper() not in _DAY_IDX:
            raise RRuleError(f"WKST must be one of {', '.join(DAY_CODES)}", src, p)
        kw["wkst"] = _DAY_IDX[v.upper()]
    for name, key, lo, hi, neg, zero in (
            ("BYSECOND", "bysecond", 0, 59, False, True),
            ("BYMINUTE", "byminute", 0, 59, False, True),
            ("BYHOUR", "byhour", 0, 23, False, True),
            ("BYMONTHDAY", "bymonthday", 1, 31, True, False),
            ("BYYEARDAY", "byyearday", 1, 366, True, False),
            ("BYWEEKNO", "byweekno", 1, 53, True, False),
            ("BYMONTH", "bymonth", 1, 12, False, False),
            ("BYSETPOS", "bysetpos", 1, 366, True, False)):
        if name in kv:
            v, p = kv[name]
            kw[key] = _ints(v, name, lo, hi, src, p, neg, zero)
    if "BYDAY" in kv:
        v, p = kv["BYDAY"]
        days, off = [], p
        for tok in v.split(","):
            m = re.fullmatch(r"([+-]?\d{1,2})?([A-Za-z]{2})", tok)
            if not m or m[2].upper() not in _DAY_IDX:
                raise RRuleError(f"bad BYDAY entry {tok!r} (expected e.g. MO, 2TU, -1FR)", src, off)
            o = int(m[1]) if m[1] else 0
            if m[1] is not None and not (1 <= abs(o) <= 53):
                raise RRuleError(f"BYDAY ordinal {o} out of range 1..53", src, off)
            days.append((o, _DAY_IDX[m[2].upper()]))
            off += len(tok) + 1
        kw["byday"] = tuple(sorted(set(days), key=lambda x: (x[1], x[0])))
    rule = Rule(**kw)
    _validate(rule, src, kv)
    return rule


def _validate(r, src, kv):
    def at(key):
        return kv[key][1] - len(key) - 1 if key in kv else 0
    if r.byweekno and r.freq != "YEARLY":
        raise RRuleError("BYWEEKNO is only valid with FREQ=YEARLY", src, at("BYWEEKNO"))
    if r.byyearday and r.freq in ("DAILY", "WEEKLY", "MONTHLY"):
        raise RRuleError(f"BYYEARDAY is not valid with FREQ={r.freq}", src, at("BYYEARDAY"))
    if r.bymonthday and r.freq == "WEEKLY":
        raise RRuleError("BYMONTHDAY is not valid with FREQ=WEEKLY", src, at("BYMONTHDAY"))
    ordinals = any(o for o, _ in r.byday)
    if ordinals and r.freq not in ("MONTHLY", "YEARLY"):
        raise RRuleError("BYDAY ordinals (e.g. 2TU) need FREQ=MONTHLY or YEARLY", src, at("BYDAY"))
    if ordinals and r.freq == "YEARLY" and r.byweekno:
        raise RRuleError("BYDAY ordinals cannot be combined with BYWEEKNO", src, at("BYDAY"))
    if r.bymonthday and all(m > 0 for m in r.bymonthday):
        months = r.bymonth or tuple(range(1, 13))
        longest = max(_MONTH_MAX[m - 1] for m in months)
        if min(r.bymonthday) > longest:
            raise RRuleError(
                f"BYMONTHDAY={','.join(map(str, r.bymonthday))} can never match"
                + (f" in BYMONTH={','.join(map(str, r.bymonth))}" if r.bymonth else ""),
                src, at("BYMONTHDAY"))
    if r.bysetpos and not any((r.bysecond, r.byminute, r.byhour, r.byday, r.bymonthday,
                               r.byyearday, r.byweekno, r.bymonth)):
        raise RRuleError("BYSETPOS requires another BYxxx part", src, at("BYSETPOS"))


# --------------------------------------------------------------------------- expansion

def _sets(r, dt):
    """Resolve DTSTART-derived defaults into concrete filter sets."""
    bymonth = set(r.bymonth)
    bymonthday = set(r.bymonthday)
    byday = list(r.byday)
    if not (r.byweekno or r.byyearday or r.bymonthday or r.byday):
        if r.freq == "YEARLY":
            if not bymonth:
                bymonth = {dt.month}
            bymonthday = {dt.day}
        elif r.freq == "MONTHLY":
            bymonthday = {dt.day}
        elif r.freq == "WEEKLY":
            byday = [(0, dt.weekday())]
    return bymonth, bymonthday, byday


def _make_date_filter(r, dt):
    bymonth, bymonthday, byday = _sets(r, dt)
    byyearday = set(r.byyearday)
    byweekno = set(r.byweekno)
    plain = {w for o, w in byday if o == 0}
    ordn = [(o, w) for o, w in byday if o != 0]
    scope = "month" if (r.freq == "MONTHLY" or (r.freq == "YEARLY" and bymonth)) else "year"
    wkst = r.wkst

    def ok(d):
        if bymonth and d.month not in bymonth:
            return False
        if byweekno:
            wy, wn, wmax = week_of(d, wkst)
            if wn not in byweekno and (wn - wmax - 1) not in byweekno:
                return False
        if byyearday:
            yd = yearday(d)
            if yd not in byyearday and (yd - days_in_year(d.year) - 1) not in byyearday:
                return False
        if bymonthday:
            if d.day not in bymonthday and (d.day - days_in_month(d.year, d.month) - 1) not in bymonthday:
                return False
        if byday:
            wd = d.weekday()
            if wd in plain:
                return True
            if ordn:
                n, m = nth_weekday_in(d, scope)
                return any(w == wd and o in (n, m) for o, w in ordn)
            return False
        return True
    return ok


def expand_wall(rule, dtstart, until=None, include_dtstart=False, skip_to=None):
    """Lazily yield naive wall-clock datetimes for `rule` starting at naive `dtstart`.

    `until` (naive datetime) overrides rule.until; it is inclusive.  Occurrences before
    dtstart are never produced.  With include_dtstart the RFC 5545 convention (DTSTART is
    always the first instance, even if the rule would not generate it) is applied.
    """
    r = rule
    if until is None and r.until is not None:
        u = r.until
        if isinstance(u, datetime):
            if u.tzinfo is not None:
                raise RRuleError("aware UNTIL needs a zone: use Recurrence(...) or pass until=")
            until = u
        else:
            until = datetime(u.year, u.month, u.day, 23, 59, 59, 999999)
    count = r.count
    emitted = 0
    if include_dtstart:
        if until is not None and dtstart > until:
            return
        first = dtstart
        yield first
        emitted += 1
        if count is not None and emitted >= count:
            return
    flt = _make_date_filter(r, dtstart)
    hours = sorted(r.byhour) or [dtstart.hour]
    minutes = sorted(r.byminute) or [dtstart.minute]
    seconds = sorted(r.bysecond) or [dtstart.second]
    freq, iv = r.freq, r.interval
    empty = 0
    limit = _EMPTY_LIMIT[freq]
    k = _first_period(r, dtstart, skip_to) if (skip_to is not None and count is None) else 0
    last = None
    while True:
        try:
            cands = _period(r, freq, iv, k, dtstart, flt, hours, minutes, seconds)
        except (OverflowError, ValueError):
            return  # ran off the end of the representable calendar
        if cands is None:
            return
        k += 1
        if r.bysetpos and cands:
            n = len(cands)
            picked = set()
            for p in r.bysetpos:
                i = p - 1 if p > 0 else n + p
                if 0 <= i < n:
                    picked.add(i)
            cands = [cands[i] for i in sorted(picked)]
        produced = False
        for occ in cands:
            if occ < dtstart:
                continue
            if include_dtstart and occ == dtstart:
                continue
            if until is not None and occ > until:
                return
            if last is not None and occ <= last:
                continue
            last = occ
            produced = True
            yield occ
            emitted += 1
            if count is not None and emitted >= count:
                return
        empty = 0 if produced else empty + 1
        if empty > limit:
            return


def _first_period(r, dt, target):
    """Index of a period at or just before the one containing `target` (never after it)."""
    iv, f = r.interval, r.freq
    if target <= dt:
        return 0
    if f == "YEARLY":
        n = (target.year - dt.year) // iv
    elif f == "MONTHLY":
        n = ((target.year * 12 + target.month) - (dt.year * 12 + dt.month)) // iv
    elif f == "WEEKLY":
        n = (target.date() - week_start(dt.date(), r.wkst)).days // (7 * iv)
    elif f == "DAILY":
        n = (target.date() - dt.date()).days // iv
    else:
        unit = {"HOURLY": 3600, "MINUTELY": 60, "SECONDLY": 1}[f]
        base = dt.replace(minute=0, second=0, microsecond=0) if f == "HOURLY" else \
            dt.replace(second=0, microsecond=0) if f == "MINUTELY" else dt.replace(microsecond=0)
        n = int((target - base).total_seconds() // unit) // iv
    return max(0, n - 1)


def _period(r, freq, iv, k, dt, flt, hours, minutes, seconds):
    """Sorted candidate datetimes of the k-th period, or None when past MAX_YEAR."""
    if freq == "YEARLY":
        y = dt.year + k * iv
        if y > MAX_YEAR:
            return None
        days = [d for d in year_dates(y) if flt(d)]
    elif freq == "MONTHLY":
        idx = dt.year * 12 + dt.month - 1 + k * iv
        y, m = divmod(idx, 12)
        if y > MAX_YEAR:
            return None
        days = [d for d in month_dates(y, m + 1) if flt(d)]
    elif freq == "WEEKLY":
        ws = week_start(dt.date(), r.wkst) + timedelta(days=7 * iv * k)
        if ws.year > MAX_YEAR:
            return None
        days = [d for d in (ws + timedelta(days=i) for i in range(7)) if flt(d)]
    elif freq == "DAILY":
        d = dt.date() + timedelta(days=iv * k)
        if d.year > MAX_YEAR:
            return None
        days = [d] if flt(d) else []
    else:
        if freq == "HOURLY":
            base = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=iv * k)
        elif freq == "MINUTELY":
            base = dt.replace(second=0, microsecond=0) + timedelta(minutes=iv * k)
        else:
            base = dt.replace(microsecond=0) + timedelta(seconds=iv * k)
        if base.year > MAX_YEAR:
            return None
        if not flt(base.date()):
            return []
        if r.byhour and base.hour not in r.byhour:
            return []
        if freq in ("MINUTELY", "SECONDLY") and r.byminute and base.minute not in r.byminute:
            return []
        if freq == "SECONDLY" and r.bysecond and base.second not in r.bysecond:
            return []
        if freq == "HOURLY":
            return [base.replace(minute=mi, second=s) for mi in minutes for s in seconds]
        if freq == "MINUTELY":
            return [base.replace(second=s) for s in seconds]
        return [base]
    out = []
    for d in days:
        for h in hours:
            for mi in minutes:
                for s in seconds:
                    out.append(datetime(d.year, d.month, d.day, h, mi, s))
    return out
