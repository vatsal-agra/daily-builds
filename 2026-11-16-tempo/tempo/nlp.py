"""English <-> RRULE.

english_to_rrule("every other tuesday at 9:30am until dec 31 2027")
    -> Schedule(rule=FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;BYHOUR=9;BYMINUTE=30;UNTIL=..., ...)

The grammar is deliberately small and strict: anything it does not understand is reported with
the offending word underlined rather than guessed at.
"""
import re
from dataclasses import dataclass
from datetime import date

from .dates import DAY_CODES, DAY_NAMES, MONTH_NAMES
from .errors import NLError
from .rrule import Rule, parse_rrule, _fmt_until

_DAYS = {}
for _i, _n in enumerate(DAY_NAMES):
    _DAYS[_n.lower()] = _i
    _DAYS[_n[:3].lower()] = _i
_DAYS.update({"tues": 1, "weds": 2, "thur": 3, "thurs": 3})
_MONTHS = {}
for _i, _n in enumerate(MONTH_NAMES):
    _MONTHS[_n.lower()] = _i + 1
    _MONTHS[_n[:3].lower()] = _i + 1
_MONTHS["sept"] = 9
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1,
        "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
_UNIT = {"second": "SECONDLY", "minute": "MINUTELY", "hour": "HOURLY", "day": "DAILY",
         "week": "WEEKLY", "month": "MONTHLY", "year": "YEARLY"}
_NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "twelve": 12}
_DAYRE = "|".join(sorted(_DAYS, key=len, reverse=True))
_MONRE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ORDRE = "|".join(_ORD)


@dataclass
class Schedule:
    rule: Rule
    start: date = None        # "starting ..." date, if given

    def __str__(self):
        return self.rule.to_string()

    def to_recurrence(self, zone, default_start=None):
        """Bind to a zone: DTSTART is the schedule's start date (or `default_start`, or today)
        at its first time of day (midnight when none was given)."""
        from datetime import datetime
        from .recur import Recurrence
        d = self.start or default_start or date.today()
        h = self.rule.byhour[0] if self.rule.byhour else 0
        m = self.rule.byminute[0] if self.rule.byminute else 0
        # rfc_dtstart off: the first occurrence is the first date that actually fits the phrase
        return Recurrence(self.rule, datetime(d.year, d.month, d.day, h, m), zone, rfc_dtstart=False)


def _n(tok):
    tok = tok.lower()
    return _NUMW[tok] if tok in _NUMW else int(re.sub(r"(st|nd|rd|th)$", "", tok))


def _parse_date(s, src, pos, default_year=None):
    s = s.strip().lower().rstrip(",")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(rf"({_MONRE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?", s)
        if m:
            return date(int(m[3]) if m[3] else (default_year or date.today().year), _MONTHS[m[1]], int(m[2]))
        m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONRE})\.?(?:,?\s*(\d{{4}}))?", s)
        if m:
            return date(int(m[3]) if m[3] else (default_year or date.today().year), _MONTHS[m[2]], int(m[1]))
    except ValueError as e:
        raise NLError(f"invalid date {s!r}: {e}", src, pos)
    raise NLError(f"cannot read date {s!r} (try 'dec 31 2027' or '2027-12-31')", src, pos)


def _time_tokens(s):
    """'9am and 14:30' -> [(9,0),(14,30)]; returns None if unreadable."""
    out = []
    for part in re.split(r"\s*(?:,|\band\b)\s*", s.strip()):
        if not part:
            continue
        if part == "noon":
            out.append((12, 0))
        elif part == "midnight":
            out.append((0, 0))
        else:
            m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", part)
            if not m:
                return None
            h, mi, ap = int(m[1]), int(m[2] or 0), (m[3] or "").replace(".", "")
            if mi > 59:
                return None
            if ap:
                if not 1 <= h <= 12:
                    return None
                h = h % 12 + (12 if ap == "pm" else 0)
            elif h > 23:
                return None
            out.append((h, mi))
    return out or None


def english_to_rrule(text, default_year=None):
    """Parse an English recurrence phrase into a Schedule (rule + optional start date)."""
    src = text
    s = " " + re.sub(r"\s+", " ", text.strip().lower()) + " "
    if not text.strip():
        raise NLError("empty schedule")
    kw = {}
    start = None

    def take(pattern, flags=0):
        nonlocal s
        m = re.search(pattern, s, flags)
        if m:
            s = s[:m.start()] + " " + s[m.end():]
        return m

    m = take(r"\b(?:until|through|thru|ending(?: on)?|till)\s+(.+?)(?= (?:at|starting|from|for|every|on|each)\b| *$)")
    if m:
        u = _parse_date(m[1], src, 0, default_year)
        kw["until"] = u
    m = take(r"\b(?:for\s+)?(\d+|" + "|".join(_NUMW) + r")\s+(?:times|occurrences|occurrence|time)\b")
    if m:
        kw["count"] = _n(m[1])
        if kw["count"] < 1:
            raise NLError("count must be at least 1", src, 0)
    m = take(r"\b(?:starting|beginning|from)\s+(?:on\s+)?(.+?)(?= (?:at|until|for|every|on|each)\b| *$)")
    if m:
        start = _parse_date(m[1], src, 0, default_year)
    times = []
    for m in list(re.finditer(r"\bat\s+((?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)"
                              r"(?:\s*(?:,|and)\s*(?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?))*)", s)):
        t = _time_tokens(m[1])
        if t is None:
            raise NLError(f"cannot read time {m[1].strip()!r}", src, max(src.lower().find(m[1].strip()), 0))
        times += t
    s = re.sub(r"\bat\s+((?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)"
               r"(?:\s*(?:,|and)\s*(?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?))*)", " ", s)
    if times:
        times = sorted(set(times))
        kw["byhour"] = tuple(sorted({h for h, _ in times}))
        kw["byminute"] = tuple(sorted({mi for _, mi in times}))
        if len(times) != len(kw["byhour"]) * len(kw["byminute"]):
            raise NLError("those times are not a clean grid (e.g. 9:00 and 14:30 would also "
                          "produce 9:30 and 14:00); say them as separate rules", src, 0)

    body = s.strip()
    iv = 1

    def finish(freq, **extra):
        return Schedule(Rule(freq=freq, interval=iv, **kw, **extra), start)

    # --- aliases
    simple = {"daily": ("DAILY", {}), "weekly": ("WEEKLY", {}), "monthly": ("MONTHLY", {}),
              "yearly": ("YEARLY", {}), "annually": ("YEARLY", {}), "hourly": ("HOURLY", {})}
    b = re.sub(r"^(?:repeat(?:s|ing)?\s+)?", "", body)
    b = re.sub(r"\beach\b", "every", b)
    b = re.sub(r"\bevery\s+other\b", "every 2", b)
    b = re.sub(r"\bbiweekly\b", "every 2 weeks", b)
    b = re.sub(r"\bfortnightly\b", "every 2 weeks", b)
    b = re.sub(r"\bevery\s+(" + "|".join(_NUMW) + r")\b", lambda m_: f"every {_NUMW[m_[1]]}", b)
    b = b.strip()

    if b in simple:
        f, ex = simple[b]
        return finish(f, **ex)
    m = re.fullmatch(r"(?:every|on)\s+(?:weekday|weekdays)|weekdays", b)
    if m:
        return finish("WEEKLY", byday=tuple((0, d) for d in range(5)))
    if re.fullmatch(r"(?:every\s+)?weekends?|every weekend day", b):
        return finish("WEEKLY", byday=((0, 5), (0, 6)))
    m = re.fullmatch(r"every\s+(?:(\d+)\s+)?(second|minute|hour|day|week|month|year)s?", b)
    if m:
        iv = int(m[1]) if m[1] else 1
        if iv < 1:
            raise NLError("interval must be at least 1", src, 0)
        return finish(_UNIT[m[2]])
    # --- weekly: every [N] mon[day] (and|,) wed
    dl = rf"(?:{_DAYRE})s?"
    m = re.fullmatch(rf"(?:every|on)\s+(?:(\d+)\s+)?((?:{dl})(?:\s*(?:,|and|&)\s*{dl})*)", b)
    if m:
        iv = int(m[1]) if m[1] else 1
        days = sorted({_DAYS[d.rstrip("s") if d.rstrip("s") in _DAYS else d]
                       for d in re.findall(rf"{_DAYRE}", m[2])})
        # "every 2 tuesday" is read as "every 2 weeks on Tuesday"
        return finish("WEEKLY", byday=tuple((0, d) for d in days))
    m = re.fullmatch(rf"every\s+(\d+)\s+weeks?\s+on\s+((?:{dl})(?:\s*(?:,|and|&)\s*{dl})*)", b)
    if m:
        iv = int(m[1])
        days = sorted({_DAYS[d] for d in re.findall(rf"{_DAYRE}", m[2])})
        return finish("WEEKLY", byday=tuple((0, d) for d in days))
    # --- nth weekday of month: "the last friday of every month", "every 2nd tuesday"
    m = re.fullmatch(rf"(?:on\s+)?(?:the\s+|every\s+)?({_ORDRE})\s+({_DAYRE})s?(?:\s+of\s+(?:every\s+)?(?:the\s+)?(?:(\d+)\s+)?months?)?", b)
    if m:
        iv = int(m[3]) if m[3] else 1
        return finish("MONTHLY", byday=((_ORD[m[1]], _DAYS[m[2]]),))
    m = re.fullmatch(rf"(?:on\s+)?(?:the\s+)?({_ORDRE})\s+({_DAYRE})s?\s+of\s+({_MONRE})", b)
    if m:
        return finish("YEARLY", byday=((_ORD[m[1]], _DAYS[m[2]]),), bymonth=(_MONTHS[m[3]],))
    # --- monthly on days: "monthly on the 1st and 15th", "every month on the 15th", "on the last day of every month"
    mday = r"(\d{1,2})(?:st|nd|rd|th)?"
    m = re.fullmatch(rf"(?:every|monthly)\s*(?:(\d+)\s+)?(?:months?)?\s*(?:on\s+)?(?:the\s+)?((?:{mday}|last(?: day)?)(?:\s*(?:,|and)\s*(?:the\s+)?(?:{mday}|last(?: day)?))*)\s*(?:day\s+)?(?:of\s+(?:the|every)\s+months?)?", b)
    if m and m[2]:
        iv = int(m[1]) if m[1] else 1
        return finish("MONTHLY", bymonthday=_month_days(m[2], src))
    m = re.fullmatch(rf"(?:on\s+)?(?:the\s+)?((?:{mday}|last(?: day)?)(?:\s*(?:,|and)\s*(?:the\s+)?(?:{mday}|last(?: day)?))*)\s*(?:day\s+)?of\s+(?:every|each|the)\s+months?", b)
    if m:
        return finish("MONTHLY", bymonthday=_month_days(m[1], src))
    m = re.fullmatch(r"on\s+the\s+last\s+day\s+of\s+(?:every\s+)?months?", b)
    if m:
        return finish("MONTHLY", bymonthday=(-1,))
    # --- yearly on a date: "every year on march 3", "yearly on jan 1", "every 4th of july"
    m = re.fullmatch(rf"(?:every\s+(?:year\s+)?|yearly\s+|annually\s+)?(?:on\s+)?(?:the\s+)?({_MONRE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?", b)
    if m:
        return finish("YEARLY", bymonth=(_MONTHS[m[1]],), bymonthday=(int(m[2]),))
    m = re.fullmatch(rf"(?:every\s+)?(?:year\s+)?(?:on\s+)?(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\s+of\s+({_MONRE})", b)
    if m:
        return finish("YEARLY", bymonth=(_MONTHS[m[2]],), bymonthday=(int(m[1]),))
    if not b and times:
        return finish("DAILY")   # "at 9am"
    # unreadable: underline the first word we could not place
    word = re.search(r"\S+", b)
    pos = src.lower().find(word[0]) if word else 0
    raise NLError("could not understand this schedule; try forms like 'every other tuesday at 9am', "
                  "'the last friday of every month', 'monthly on the 1st and 15th', "
                  "'every 3 days until dec 31'", src, max(pos, 0))


def _month_days(txt, src):
    out = []
    for part in re.split(r"\s*(?:,|and)\s*", txt.strip()):
        part = part.replace("the ", "").strip()
        if part.startswith("last"):
            out.append(-1)
        else:
            d = int(re.sub(r"\D", "", part))
            if not 1 <= d <= 31:
                raise NLError(f"day of month {d} is out of range", src, 0)
            out.append(d)
    return tuple(sorted(set(out)))


# ------------------------------------------------------------------ RRULE -> English
def _ord(n):
    if n == -1:
        return "last"
    if n < 0:
        return f"{_ord(-n)}-to-last"
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def rrule_to_english(rule):
    """Describe a Rule (or RRULE string) in plain English."""
    r = parse_rrule(rule) if isinstance(rule, str) else rule
    unit = {"YEARLY": "year", "MONTHLY": "month", "WEEKLY": "week", "DAILY": "day",
            "HOURLY": "hour", "MINUTELY": "minute", "SECONDLY": "second"}[r.freq]
    plain0 = sorted(w for o, w in r.byday if o == 0)
    nat = None
    if r.freq == "WEEKLY" and r.interval == 1 and plain0 and len(plain0) == len(r.byday):
        nat = ("every weekday" if plain0 == [0, 1, 2, 3, 4] else "every weekend" if plain0 == [5, 6]
               else "every " + _join(DAY_NAMES[w] for w in plain0))
    if nat:
        head = nat
    elif r.interval == 1:
        head = {"YEARLY": "every year", "MONTHLY": "every month", "WEEKLY": "every week",
                "DAILY": "every day"}.get(r.freq, f"every {unit}")
    elif r.interval == 2 and r.freq in ("WEEKLY", "DAILY", "MONTHLY", "YEARLY"):
        head = f"every other {unit}"
    else:
        head = f"every {r.interval} {unit}s"
    parts = []
    days = r.byday
    plain = [] if nat else sorted(w for o, w in days if o == 0)
    if plain:
        if plain == [0, 1, 2, 3, 4] and r.freq in ("WEEKLY", "DAILY"):
            parts.append("on weekdays")
        elif plain == [5, 6] and r.freq in ("WEEKLY", "DAILY"):
            parts.append("on weekends")
        else:
            parts.append("on " + _join(DAY_NAMES[w] for w in plain))
    ords = [(o, w) for o, w in days if o != 0]
    if ords:
        parts.append("on the " + _join(f"{_ord(o)} {DAY_NAMES[w]}" for o, w in ords))
    if r.bymonthday:
        parts.append("on the " + _join("last day" if d == -1 else (_ord(d) if d > 0 else f"{_ord(d)} day")
                                       for d in r.bymonthday))
    if r.byyearday:
        parts.append("on day " + _join(str(d) for d in r.byyearday) + " of the year")
    if r.byweekno:
        parts.append("in week " + _join(str(w) for w in r.byweekno))
    if r.bymonth:
        parts.append(("in " if not r.bymonthday else "of ") + _join(MONTH_NAMES[m - 1] for m in r.bymonth))
    if r.byhour or r.byminute or r.bysecond:
        hrs = r.byhour or ()
        mns = r.byminute or ((0,) if hrs else ())
        if hrs:
            ts = [f"{h:02d}:{m:02d}" + (f":{s:02d}" if r.bysecond else "")
                  for h in hrs for m in mns for s in (r.bysecond or (None,)) if s is None or True][:12]
            parts.append("at " + _join(ts) + ("…" if len(hrs) * len(mns) > 12 else ""))
        elif r.byminute:
            parts.append("at minute " + _join(str(m) for m in r.byminute))
        else:
            parts.append("at second " + _join(str(s) for s in r.bysecond))
    if r.bysetpos:
        parts.append("(taking the " + _join(_ord(p) for p in r.bysetpos) + " match of each period)")
    out = head + (" " + " ".join(parts) if parts else "")
    if r.wkst != 0 and r.freq in ("WEEKLY",) and r.interval > 1:
        out += f", weeks starting {DAY_NAMES[r.wkst]}"
    if r.count is not None:
        out += f", {r.count} time{'s' if r.count != 1 else ''}"
    if r.until is not None:
        u = r.until
        d = u.date() if hasattr(u, "date") and callable(u.date) else u
        out += f", until {MONTH_NAMES[d.month - 1]} {d.day}, {d.year}"
    return out
