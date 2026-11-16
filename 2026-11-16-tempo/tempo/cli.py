"""Command line: python -m tempo <command> ...

  rrule  RULE --start 2026-01-31T09:00 [--tz Europe/Paris] [-n 10] [--exdate ...]
  cron   EXPR [--tz ZONE] [--from ISO] [-n 5] [--prev]
  meet   --people people.json --from ISO --to ISO --minutes 45 [--html out.html]
  say    "every other tuesday at 9am" [--tz ZONE] [--start DATE] [-n 5]
  explain RULE                       RRULE -> English
  ics    FILE.ics [--from ISO --to ISO] [--month YYYY-MM --html out.html]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta

from .errors import TempoError
from .recur import Recurrence
from .cron import Cron
from .tz import UTC, get_zone, resolve, fmt_offset


def positive_int(text):
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number")
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


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
    try:
        with open(a.people, encoding="utf-8") as f:
            spec = json.load(f)
    except OSError as e:
        raise TempoError(f"cannot read {a.people}: {e.strerror or e}")
    except json.JSONDecodeError as e:
        raise TempoError(f"{a.people} is not valid JSON: {e}")
    if not isinstance(spec, list) or not spec:
        raise TempoError("people file must be a non-empty JSON list of attendee objects")

    def need(obj, key, where):
        if not isinstance(obj, dict) or key not in obj:
            raise TempoError(f"{where}: missing required field {key!r}")
        return obj[key]
    people = []
    for i, p in enumerate(spec):
        where = f"attendee #{i + 1}"
        name = need(p, "name", where)
        where = f"attendee {name!r}"
        z = get_zone(p.get("tz", "UTC"))
        busy = []
        for j, b in enumerate(p.get("busy", [])):
            bw = f"{where} busy #{j + 1}"
            s = parse_dt(need(b, "start", bw))
            mins = need(b, "minutes", bw)
            if not isinstance(mins, (int, float)) or mins <= 0:
                raise TempoError(f"{bw}: 'minutes' must be a positive number")
            rec = Recurrence(b["rrule"], s, z) if b.get("rrule") else None
            busy.append(Busy(start=s if s.tzinfo else resolve(s, z), duration=timedelta(minutes=mins),
                             recurrence=rec, title=b.get("title", "")))
        people.append(Attendee(name, z, p.get("hours"), p.get("stretch"), busy,
                               bool(p.get("optional", False))))
    lo, hi = parse_dt(a.start), parse_dt(a.end)
    lo = lo if lo.tzinfo else lo.replace(tzinfo=UTC)
    hi = hi if hi.tzinfo else hi.replace(tzinfo=UTC)
    dur = timedelta(minutes=a.minutes)
    slots = find_slots(people, lo, hi, dur, allow_stretch=a.stretch, limit=a.limit,
                       buffer=timedelta(minutes=a.buffer))
    if a.html:
        from .render import render_meeting
        day = (slots[0].start if slots else lo)
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(render_meeting(people, day, slots))
        print(f"wrote {a.html}")
    if not slots:
        print("No slot found.")
        for line in explain_no_slots(people, lo, hi, dur, timedelta(minutes=a.buffer), a.stretch):
            print(" -", line)
        return 2
    for s in slots:
        print(s.render())
        print()
    return 0


def cmd_say(a):
    from .nlp import english_to_rrule, rrule_to_english
    sch = english_to_rrule(" ".join(a.phrase))
    print(f"rule  : {sch.rule}")
    print(f"means : {rrule_to_english(sch.rule)}")
    default = datetime.fromisoformat(a.start).date() if a.start else None
    rec = sch.to_recurrence(a.tz, default)
    for i, x in enumerate(rec.take(a.n), 1):
        print(f"{i:>4}  {show(x)}")
    return 0


def cmd_explain(a):
    from .nlp import rrule_to_english
    print(rrule_to_english(a.rule))
    return 0


def cmd_ics(a):
    from .ics import parse_ics
    try:
        with open(a.file, encoding="utf-8") as f:
            cal = parse_ics(f.read())
    except OSError as e:
        raise TempoError(f"cannot read {a.file}: {e.strerror or e}")
    except UnicodeDecodeError:
        raise TempoError(f"{a.file} is not UTF-8 text")
    for w in cal.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if a.month:
        from .render import render_month
        try:
            y, m = (int(x) for x in a.month.split("-"))
            html = render_month(cal, y, m, today=datetime.now().date(), zone=a.tz)
        except ValueError:
            raise TempoError("--month must look like 2026-11")
        if a.html:
            with open(a.html, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"wrote {a.html}")
        else:
            print(html)
        return 0
    lo = parse_dt(a.start) if a.start else datetime.now(UTC)
    hi = parse_dt(a.end) if a.end else lo + timedelta(days=14)
    occ = cal.occurrences(lo, hi)
    if not occ:
        print("(no events in range)")
    z = get_zone(a.tz)
    for o in occ:
        s = o.start
        when = s.astimezone(z).strftime("%a %Y-%m-%d %H:%M") if isinstance(s, datetime) and s.tzinfo else \
            (s.strftime("%a %Y-%m-%d") + (" " + s.strftime("%H:%M") if isinstance(s, datetime) else " all-day"))
        print(f"{when}  {o.summary or '(no title)'}{'  [moved]' if o.override else ''}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="tempo", description="Recurrence, cron and meeting-finder toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rrule", help="expand an RRULE")
    r.add_argument("rule")
    r.add_argument("--start", required=True)
    r.add_argument("--tz")
    r.add_argument("-n", type=positive_int, default=10)
    r.add_argument("--exdate", action="append")
    r.add_argument("--rdate", action="append")
    r.add_argument("--gap", choices=["forward", "skip"], default="forward")
    r.add_argument("--strict-start", action="store_true", help="do not force DTSTART as first instance")
    r.set_defaults(fn=cmd_rrule)
    c = sub.add_parser("cron", help="next/previous cron fire times")
    c.add_argument("expr")
    c.add_argument("--tz", default="UTC")
    c.add_argument("--from", dest="start")
    c.add_argument("-n", type=positive_int, default=5)
    c.add_argument("--prev", action="store_true")
    c.set_defaults(fn=cmd_cron)
    m = sub.add_parser("meet", help="find meeting slots")
    m.add_argument("--people", required=True)
    m.add_argument("--from", dest="start", required=True)
    m.add_argument("--to", dest="end", required=True)
    m.add_argument("--minutes", type=positive_int, default=30)
    m.add_argument("--buffer", type=int, default=0)
    m.add_argument("--limit", type=positive_int, default=5)
    m.add_argument("--stretch", action="store_true")
    m.add_argument("--html", help="also write an HTML view of the first day with the proposals")
    m.set_defaults(fn=cmd_meet)
    sy = sub.add_parser("say", help="English phrase -> RRULE + next occurrences")
    sy.add_argument("phrase", nargs="+")
    sy.add_argument("--tz", default="UTC")
    sy.add_argument("--start")
    sy.add_argument("-n", type=positive_int, default=5)
    sy.set_defaults(fn=cmd_say)
    ex = sub.add_parser("explain", help="RRULE -> English")
    ex.add_argument("rule")
    ex.set_defaults(fn=cmd_explain)
    ic = sub.add_parser("ics", help="list or render events of an .ics file")
    ic.add_argument("file")
    ic.add_argument("--from", dest="start")
    ic.add_argument("--to", dest="end")
    ic.add_argument("--tz", default="UTC")
    ic.add_argument("--month")
    ic.add_argument("--html")
    ic.set_defaults(fn=cmd_ics)
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
