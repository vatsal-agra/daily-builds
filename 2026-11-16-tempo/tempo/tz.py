"""Wall-clock -> instant resolution with explicit DST policy.

Recurrence rules are expanded in *wall-clock* time ("every day at 02:30").  Converting a
wall-clock time to an instant is ambiguous or impossible twice a year:

  gap   (spring forward) 02:30 never happens.   policy "forward": use the offset in force
        before the gap, which lands on 03:30 (the RFC 5545 rule).  policy "skip": drop it.
  fold  (fall back) 01:30 happens twice.        We always take the first occurrence.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import TempoError

UTC = timezone.utc


def get_zone(name):
    if name is None:
        return UTC
    if not isinstance(name, str):
        return name
    if name.upper() in ("UTC", "Z"):
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise TempoError(f"unknown time zone {name!r} (use an IANA name like 'Europe/Paris')")


def classify(naive, zone):
    """Return 'ok', 'gap' or 'fold' for a naive wall time in `zone`."""
    if zone is UTC:
        return "ok"
    d0 = naive.replace(tzinfo=zone, fold=0)
    d1 = naive.replace(tzinfo=zone, fold=1)
    rt0 = d0.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    if rt0 != naive:
        return "gap"
    if d0.utcoffset() != d1.utcoffset():
        return "fold"
    return "ok"


def resolve(naive, zone, gap="forward"):
    """Naive wall time -> aware datetime in `zone`, or None when gap == 'skip' hits a gap."""
    if zone is UTC:
        return naive.replace(tzinfo=UTC)
    kind = classify(naive, zone)
    d0 = naive.replace(tzinfo=zone, fold=0)
    if kind == "gap":
        if gap == "skip":
            return None
        return d0.astimezone(UTC).astimezone(zone)  # pre-gap offset => shifted forward
    return d0  # ok, or first occurrence of a fold


def wall(aware, zone):
    """Aware datetime -> naive wall time in `zone`."""
    return aware.astimezone(zone).replace(tzinfo=None)


def to_utc(dt, zone=UTC):
    """Accept naive (interpreted in zone) or aware; return aware UTC."""
    if dt.tzinfo is None:
        r = resolve(dt, zone)
        return r.astimezone(UTC)
    return dt.astimezone(UTC)


def fmt_offset(dt):
    off = dt.utcoffset() or timedelta(0)
    s = int(off.total_seconds())
    sign = "+" if s >= 0 else "-"
    s = abs(s)
    return f"{sign}{s // 3600:02d}:{(s % 3600) // 60:02d}"
