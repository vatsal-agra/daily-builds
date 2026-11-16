"""Command line: python -m tempo <command> ...

  rrule  RULE --start 2026-01-31T09:00 [--tz Europe/Paris] [-n 10] [--exdate ...]
  cron   EXPR [--tz ZONE] [--from ISO] [-n 5] [--prev]
  meet   --people people.json --from ISO --to ISO --minutes 45
"""
import argparse
import json
import sys
from datetime import datetime, timedelta

from .errors import TempoError
from .recur import Recurrence
from .cron import Cron
from .tz import UTC, get_zone, resolve, fmt_offset


def parse_dt(s, zone=None):
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise TempoError(f"cannot read date/time {s!r} (use ISO 8601, e.g. 2026-03-08T09:30)")
    return d


def show(dt):
    if dt.tzinfo is None:
        return dt.strftime("%a %Y-%m-%d %H:%M:%S")
    return f"{dt.strftime('%a %Y-%m-%d %H:%M:%S')} {fmt_offset(dt)} {dt.tzname() or ''}".rstrip()


def cmd_rrule(a):
    start = parse_dt(a.start)
    rec = Recurrence(a.rule, start, a.tz, exdates=[parse_dt(x) for x in a.exdate or []],
                     rdates=[parse_dt(x) for x in a.rdate or []], gap=a.gap,
                     rfc_dtstart=not a.strict_start)
    print(f"rule  : {rec.rule}")
    try:
        from .nlp import rrule_to_english
        print(f"means : {rrule_to_english(rec.rule)}")
    except ImportError:
        pass
    for i, x in enumerate(rec.take(a.n), 1):
        print(f"{i:>4}  {show(x)}")
    return 0


def cmd_cron(a):
    c = Cron(a.expr, a.tz)
    z = get_zone(a.tz)
    ref = parse_dt(a.start) if a.start else datetime.now(UTC)
    if ref.tzinfo is None:
        ref = resolve(ref, z)
    if a.prev:
        cur = ref
        for i in range(1, a.n + 1):
            cur = c.prev(cur)
            print(f"{i:>4}  {show(cur.astimezone(z))}")
    else:
        for i, x in enumerate(c.take(ref, a.n), 1):
            print(f"{i:>4}  {show(x)}")
    return 0


def cmd_meet(a):
    from .scheduler import Attendee, Busy, find_slots, explain_no_slots, timeline
    with open(a.people) as f:
        spec = json.load(f)
    people = []
    for p in spec:
        busy = []
        for b in p.get("busy", []):
            z = get_zone(p.get("tz", "UTC"))
            s = parse_dt(b["start"])
            rec = Recurrence(b["rrule"], s, z) if b.get("rrule") else None
            busy.append(Busy(start=s if s.tzinfo else resolve(s, z), duration=timedelta(minutes=b["minutes"]),
                             recurrence=rec, title=b.get("title", "")))
        people.append(Attendee(p["name"], p.get("tz", "UTC"), p.get("hours"), p.get("stretch"),
                               busy, p.get("optional", False)))
    lo, hi = parse_dt(a.start), parse_dt(a.end)
    lo = lo if lo.tzinfo else lo.replace(tzinfo=UTC)
    hi = hi if hi.tzinfo else hi.replace(tzinfo=UTC)
    dur = timedelta(minutes=a.minutes)
    slots = find_slots(people, lo, hi, dur, allow_stretch=a.stretch, limit=a.limit,
                       buffer=timedelta(minutes=a.buffer))
    if not slots:
        print("No slot found.")
        for line in explain_no_slots(people, lo, hi, dur, timedelta(minutes=a.buffer), a.stretch):
            print(" -", line)
        return 2
    for s in slots:
        print(s.render())
        print()
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="tempo", description="Recurrence, cron and meeting-finder toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rrule", help="expand an RRULE")
    r.add_argument("rule")
    r.add_argument("--start", required=True)
    r.add_argument("--tz")
    r.add_argument("-n", type=int, default=10)
    r.add_argument("--exdate", action="append")
    r.add_argument("--rdate", action="append")
    r.add_argument("--gap", choices=["forward", "skip"], default="forward")
    r.add_argument("--strict-start", action="store_true", help="do not force DTSTART as first instance")
    r.set_defaults(fn=cmd_rrule)
    c = sub.add_parser("cron", help="next/previous cron fire times")
    c.add_argument("expr")
    c.add_argument("--tz", default="UTC")
    c.add_argument("--from", dest="start")
    c.add_argument("-n", type=int, default=5)
    c.add_argument("--prev", action="store_true")
    c.set_defaults(fn=cmd_cron)
    m = sub.add_parser("meet", help="find meeting slots")
    m.add_argument("--people", required=True)
    m.add_argument("--from", dest="start", required=True)
    m.add_argument("--to", dest="end", required=True)
    m.add_argument("--minutes", type=int, default=30)
    m.add_argument("--buffer", type=int, default=0)
    m.add_argument("--limit", type=int, default=5)
    m.add_argument("--stretch", action="store_true")
    m.set_defaults(fn=cmd_meet)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except TempoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
