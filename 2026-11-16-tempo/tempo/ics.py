"""iCalendar (RFC 5545) reader/writer for VEVENTs, with full recurrence handling.

Supported: line unfolding, parameters (quoted values), TEXT escapes, DTSTART/DTEND/DURATION as
DATE, floating DATE-TIME, UTC and TZID (IANA names plus common Windows names), RRULE, EXDATE,
RDATE, RECURRENCE-ID overrides and STATUS:CANCELLED instances.  VTIMEZONE blocks are ignored
(TZID is resolved through the IANA database instead); the writer emits IANA TZIDs without
VTIMEZONE, which Google/Apple/Outlook accept.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .errors import ICSError
from .recur import Recurrence
from .rrule import parse_rrule
from .tz import UTC, get_zone, resolve, wall

WINDOWS_ZONES = {
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris", "India Standard Time": "Asia/Kolkata",
    "Tokyo Standard Time": "Asia/Tokyo", "China Standard Time": "Asia/Shanghai",
    "AUS Eastern Standard Time": "Australia/Sydney", "UTC": "UTC",
    "Singapore Standard Time": "Asia/Singapore", "Arabian Standard Time": "Asia/Dubai",
}


# ------------------------------------------------------------------ content lines
@dataclass
class Line:
    name: str
    params: dict
    value: str
    lineno: int


def unfold(text):
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] = (out[-1][0], out[-1][1] + raw[1:])
        else:
            out.append((len(out) + 1, raw))
    return [(n, l) for n, l in out if l.strip()]


_PARAM = re.compile(r';([A-Za-z0-9-]+)=("[^"]*"|[^;:]*)')


def parse_line(lineno, raw):
    m = re.match(r"([A-Za-z0-9-]+)", raw)
    if not m:
        raise ICSError(f"line {lineno}: not a content line: {raw[:40]!r}")
    name, pos, params = m[1].upper(), m.end(), {}
    while pos < len(raw) and raw[pos] == ";":
        pm = _PARAM.match(raw, pos)
        if not pm:
            raise ICSError(f"line {lineno}: bad parameter in {raw[:50]!r}")
        params[pm[1].upper()] = pm[2].strip('"')
        pos = pm.end()
    if pos >= len(raw) or raw[pos] != ":":
        raise ICSError(f"line {lineno}: missing ':' in {raw[:50]!r}")
    return Line(name, params, raw[pos + 1:], lineno)


def unescape(s):
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], s)


def escape(s):
    return s.replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def fold(line):
    """Fold to 75 octets per line (never splitting a UTF-8 sequence)."""
    b, out, first = line.encode("utf-8"), [], True
    while len(b) > (75 if first else 74):
        cut = 75 if first else 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b, first = b[cut:], False
    out.append(b.decode("utf-8"))
    return "\r\n ".join(out)


# ------------------------------------------------------------------ values
def zone_of(params, lineno):
    tzid = params.get("TZID")
    if tzid is None:
        return None
    tzid = WINDOWS_ZONES.get(tzid, tzid).lstrip("/")
    try:
        return get_zone(tzid)
    except ValueError:
        raise ICSError(f"line {lineno}: unknown TZID {params['TZID']!r}")


def parse_value(line):
    """Return (value, zone, is_date): date | naive datetime | aware UTC datetime."""
    v, p = line.value.strip(), line.params
    kind = p.get("VALUE", "").upper()
    if kind == "DATE" or re.fullmatch(r"\d{8}", v):
        try:
            return date(int(v[:4]), int(v[4:6]), int(v[6:8])), None, True
        except ValueError:
            raise ICSError(f"line {line.lineno}: invalid date {v!r}")
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z?)", v)
    if not m:
        raise ICSError(f"line {line.lineno}: invalid date-time {v!r}")
    try:
        dt = datetime(*(int(m[i]) for i in range(1, 7)))
    except ValueError:
        raise ICSError(f"line {line.lineno}: invalid date-time {v!r}")
    if m[7]:
        return dt.replace(tzinfo=UTC), UTC, False
    z = zone_of(p, line.lineno)
    return dt, z, False


def parse_duration(v, lineno):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m or v.strip() in ("P", "-P", "+P", "PT") :
        raise ICSError(f"line {lineno}: invalid DURATION {v!r}")
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    td = timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -td if m[1] == "-" else td


def fmt_duration(td):
    secs = int(td.total_seconds())
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    mi, s = divmod(rem, 60)
    out = f"{sign}P"
    if d:
        out += f"{d}D"
    if h or mi or s or not d:
        out += "T" + (f"{h}H" if h else "") + (f"{mi}M" if mi else "") + (f"{s}S" if s or not (h or mi) else "")
    return out


# ------------------------------------------------------------------ model
@dataclass
class Event:
    uid: str
    summary: str = ""
    start: object = None             # date | naive datetime | aware datetime
    zone: object = None              # tzinfo or None (floating / all-day)
    end: object = None
    duration: timedelta = None
    all_day: bool = False
    rrule: str = None
    exdates: list = field(default_factory=list)
    rdates: list = field(default_factory=list)
    description: str = ""
    location: str = ""
    status: str = ""
    recurrence_id: object = None     # set on override components
    overrides: dict = field(default_factory=dict)

    @property
    def length(self):
        if self.duration is not None:
            return self.duration
        if self.end is not None:
            if self.all_day:
                return self.end - self.start
            return _as_utc(self.end, self.zone) - _as_utc(self.start, self.zone)
        return timedelta(days=1) if self.all_day else timedelta(0)

    def recurrence(self):
        if not self.rrule:
            return None
        s = self.start
        if self.all_day:
            s = datetime(s.year, s.month, s.day)
        return Recurrence(self.rrule, s, self.zone if not self.all_day else None,
                          exdates=[(datetime(x.year, x.month, x.day) if self.all_day and isinstance(x, date)
                                    and not isinstance(x, datetime) else x) for x in self.exdates],
                          rdates=[(datetime(x.year, x.month, x.day) if self.all_day and isinstance(x, date)
                                   and not isinstance(x, datetime) else x) for x in self.rdates])


def _as_utc(dt, zone):
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    if zone is None:
        return dt.replace(tzinfo=UTC)  # floating: treated as UTC for arithmetic only
    return resolve(dt, zone).astimezone(UTC)


@dataclass
class Occurrence:
    start: object          # aware datetime (zoned/UTC), naive datetime (floating), or date (all-day)
    end: object
    event: Event
    override: bool = False

    @property
    def summary(self):
        return self.event.summary

    def sort_key(self):
        s = self.start
        if isinstance(s, datetime):
            return (s.astimezone(UTC).replace(tzinfo=None) if s.tzinfo else s)
        return datetime(s.year, s.month, s.day)


@dataclass
class Calendar:
    events: list = field(default_factory=list)
    name: str = ""
    warnings: list = field(default_factory=list)

    def occurrences(self, start, end):
        """All occurrences overlapping [start, end) (dates or datetimes), sorted.

        `start`/`end` may be naive (compared against floating/all-day events and, for zoned
        events, interpreted as UTC) or aware.
        """
        def norm(x):
            if isinstance(x, datetime):
                return x if x.tzinfo else x.replace(tzinfo=UTC)
            return datetime(x.year, x.month, x.day, tzinfo=UTC)
        lo, hi = norm(start), norm(end)
        out = []
        for ev in self.events:
            out.extend(_event_occurrences(ev, lo, hi))
        out.sort(key=lambda o: (o.sort_key(), o.event.uid))
        return out


def _cmp_key(v, zone):
    """Comparable UTC key for an occurrence start of any flavour."""
    if isinstance(v, datetime):
        return v.astimezone(UTC) if v.tzinfo else _as_utc(v, zone)
    return datetime(v.year, v.month, v.day, tzinfo=UTC)


def _event_occurrences(ev, lo, hi):
    length = ev.length
    rec = ev.recurrence()
    if rec is None:
        starts = [_aware(ev, ev.start)]
    else:
        wlo = lo - length - timedelta(days=1)
        probe = rec.between(wlo.replace(tzinfo=None) if rec.floating else wlo,
                            hi.replace(tzinfo=None) if rec.floating else hi)
        starts = [s.date() if ev.all_day else s for s in probe]
    res = []
    consumed = set()
    for s in starts:
        k = _cmp_key(s, ev.zone)
        ov = ev.overrides.get(_okey(s, ev))
        if ov is not None:
            consumed.add(_okey(s, ev))
            if ov.status.upper() == "CANCELLED":
                continue
            res.extend(_event_occurrences_single(ov, lo, hi, override=True))
            continue
        end = _add(s, length, ev)
        if k < hi and _cmp_key(end, ev.zone) > lo or (length == timedelta(0) and lo <= k < hi):
            res.append(Occurrence(s, end, ev))
    # overrides that moved an occurrence *into* the window from outside it
    for rid, ov in ev.overrides.items():
        if rid in consumed or ov.status.upper() == "CANCELLED":
            continue
        res.extend(_event_occurrences_single(ov, lo, hi, override=True))
    return res


def _event_occurrences_single(ov, lo, hi, override):
    length = ov.length
    start = _aware(ov, ov.start)
    k = _cmp_key(start, ov.zone)
    end = _add(start, length, ov)
    if k < hi and _cmp_key(end, ov.zone) > lo or (length == timedelta(0) and lo <= k < hi):
        return [Occurrence(start, end, ov, override)]
    return []


def _aware(ev, v):
    """Zoned events carry wall-clock starts; occurrences always expose real instants."""
    if isinstance(v, datetime) and v.tzinfo is None and ev.zone is not None:
        return resolve(v, ev.zone)
    return v


def _okey(v, ev):
    """Key identifying an instance (matches RECURRENCE-ID)."""
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(UTC)
    if isinstance(v, datetime):
        return v if ev.zone is None else _as_utc(v, ev.zone)
    return v


def _add(s, length, ev):
    if isinstance(s, datetime) and s.tzinfo is not None and ev.zone is not None and not ev.all_day:
        return (s.astimezone(UTC) + length).astimezone(s.tzinfo)
    return s + length


# ------------------------------------------------------------------ parsing
def parse_ics(text):
    if "BEGIN:VCALENDAR" not in text.upper():
        raise ICSError("not an iCalendar file (no BEGIN:VCALENDAR)")
    lines = [parse_line(n, l) for n, l in unfold(text)]
    cal, stack, cur = Calendar(), [], None
    comps = []
    for ln in lines:
        if ln.name == "BEGIN":
            stack.append(ln.value.upper())
            if ln.value.upper() == "VEVENT":
                cur = []
                comps.append(cur)
            continue
        if ln.name == "END":
            if not stack or stack[-1] != ln.value.upper():
                raise ICSError(f"line {ln.lineno}: END:{ln.value} does not match BEGIN:{stack[-1] if stack else '?'}")
            stack.pop()
            if ln.value.upper() == "VEVENT":
                cur = None
            continue
        if stack and stack[-1] == "VEVENT" and cur is not None:
            cur.append(ln)
        elif stack == ["VCALENDAR"] and ln.name in ("X-WR-CALNAME", "NAME"):
            cal.name = unescape(ln.value)
    if stack:
        raise ICSError(f"unterminated component BEGIN:{stack[-1]}")
    masters, over = {}, []
    for c in comps:
        ev = _build_event(c, cal)
        if ev is None:
            continue
        if ev.recurrence_id is not None:
            over.append(ev)
        else:
            if ev.uid in masters:
                cal.warnings.append(f"duplicate UID {ev.uid}: keeping the first")
                continue
            masters[ev.uid] = ev
            cal.events.append(ev)
    for o in over:
        m = masters.get(o.uid)
        if m is None:
            cal.warnings.append(f"override for unknown UID {o.uid} kept as a standalone event")
            o.recurrence_id = None
            cal.events.append(o)
        else:
            m.overrides[_okey(o.recurrence_id, m)] = o
    return cal


def _build_event(lines, cal):
    ev = Event(uid="")
    seen = {}
    for ln in lines:
        n = ln.name
        if n == "UID":
            ev.uid = ln.value.strip()
        elif n == "SUMMARY":
            ev.summary = unescape(ln.value)
        elif n == "DESCRIPTION":
            ev.description = unescape(ln.value)
        elif n == "LOCATION":
            ev.location = unescape(ln.value)
        elif n == "STATUS":
            ev.status = ln.value.strip()
        elif n == "DTSTART":
            seen["dtstart"] = ln
        elif n == "DTEND":
            seen["dtend"] = ln
        elif n == "DURATION":
            ev.duration = parse_duration(ln.value, ln.lineno)
        elif n == "RRULE":
            try:
                ev.rrule = parse_rrule(ln.value).to_string()
            except ValueError as e:
                raise ICSError(f"line {ln.lineno}: bad RRULE: {str(e).splitlines()[0]}")
        elif n in ("EXDATE", "RDATE"):
            target = ev.exdates if n == "EXDATE" else ev.rdates
            for part in ln.value.split(","):
                if n == "RDATE" and "/" in part:
                    cal.warnings.append(f"line {ln.lineno}: RDATE periods are not supported; ignored")
                    continue
                v, _, _ = parse_value(Line(n, ln.params, part, ln.lineno))
                target.append(v)
        elif n == "RECURRENCE-ID":
            if ln.params.get("RANGE", "").upper() == "THISANDFUTURE":
                cal.warnings.append(f"line {ln.lineno}: RANGE=THISANDFUTURE treated as a single instance")
            seen["rid"] = ln
    if "dtstart" not in seen:
        cal.warnings.append("skipped a VEVENT with no DTSTART")
        return None
    if not ev.uid:
        ev.uid = f"auto-{uuid.uuid4()}"
    v, z, is_date = parse_value(seen["dtstart"])
    ev.start, ev.zone, ev.all_day = v, z, is_date
    if z is not None and not is_date and v.tzinfo is None:
        pass  # wall time in zone
    if z is UTC and isinstance(v, datetime):
        ev.zone = UTC
    if "dtend" in seen:
        e, ez, _ = parse_value(seen["dtend"])
        if is_date != isinstance(e, date) and not isinstance(e, datetime) or (isinstance(e, datetime) == is_date):
            raise ICSError(f"line {seen['dtend'].lineno}: DTEND type differs from DTSTART")
        ev.end = e
        if ev.length < timedelta(0):
            raise ICSError(f"line {seen['dtend'].lineno}: DTEND is before DTSTART")
    if "rid" in seen:
        rv, rz, _ = parse_value(seen["rid"])
        ev.recurrence_id = rv
        if isinstance(rv, datetime) and rv.tzinfo is None and rz is not None:
            ev.recurrence_id = resolve(rv, rz)
    return ev


# ------------------------------------------------------------------ writing
def _fmt(v, zone, all_day=False, prop="DTSTART"):
    if all_day or (isinstance(v, date) and not isinstance(v, datetime)):
        d = v if not isinstance(v, datetime) else v.date()
        return f"{prop};VALUE=DATE:{d.strftime('%Y%m%d')}"
    if v.tzinfo is not None and (v.utcoffset() == timedelta(0) and zone in (None, UTC)):
        return f"{prop}:{v.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    if zone is not None and zone is not UTC:
        w = wall(v, zone) if v.tzinfo else v
        return f"{prop};TZID={getattr(zone, 'key', str(zone))}:{w.strftime('%Y%m%dT%H%M%S')}"
    if v.tzinfo is not None:
        return f"{prop}:{v.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    return f"{prop}:{v.strftime('%Y%m%dT%H%M%S')}"


def _write_event(ev, out, stamp):
    out.append("BEGIN:VEVENT")
    out.append(f"UID:{ev.uid}")
    out.append(f"DTSTAMP:{stamp}")
    if ev.recurrence_id is not None:
        out.append(_fmt(ev.recurrence_id, ev.zone, ev.all_day, "RECURRENCE-ID"))
    out.append(_fmt(ev.start, ev.zone, ev.all_day))
    if ev.end is not None:
        out.append(_fmt(ev.end, ev.zone, ev.all_day, "DTEND"))
    elif ev.duration is not None:
        out.append(f"DURATION:{fmt_duration(ev.duration)}")
    if ev.rrule:
        out.append(f"RRULE:{ev.rrule}")
    for name, vals in (("EXDATE", ev.exdates), ("RDATE", ev.rdates)):
        for v in vals:
            out.append(_fmt(v, ev.zone, ev.all_day, name))
    if ev.summary:
        out.append(f"SUMMARY:{escape(ev.summary)}")
    if ev.location:
        out.append(f"LOCATION:{escape(ev.location)}")
    if ev.description:
        out.append(f"DESCRIPTION:{escape(ev.description)}")
    if ev.status:
        out.append(f"STATUS:{ev.status}")
    out.append("END:VEVENT")


def write_ics(cal, prodid="-//Tempo//EN", now=None):
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{prodid}", "CALSCALE:GREGORIAN"]
    if cal.name:
        out.append(f"X-WR-CALNAME:{escape(cal.name)}")
    for ev in cal.events:
        _write_event(ev, out, stamp)
        for o in ev.overrides.values():
            _write_event(o, out, stamp)
    out.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in out) + "\r\n"
