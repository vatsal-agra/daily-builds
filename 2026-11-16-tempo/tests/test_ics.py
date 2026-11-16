import os
import unittest
from datetime import date, datetime, timedelta

from tests.helpers import UTC
from tempo.errors import ICSError
from tempo.ics import (Calendar, Event, fold, fmt_duration, parse_duration, parse_ics, unfold, write_ics)

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "..", "examples", "team.ics"), encoding="utf-8") as _f:
    TEAM = _f.read()


def wrap(*events):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(f"BEGIN:VEVENT\r\n{e}\r\nEND:VEVENT\r\n" for e in events) + "END:VCALENDAR\r\n"


def occ(cal, a, b):
    return [(o.start, o.summary) for o in cal.occurrences(a, b)]


class Parse(unittest.TestCase):
    def test_team_file(self):
        cal = parse_ics(TEAM)
        self.assertEqual(cal.name, "Team")
        got = cal.occurrences(datetime(2026, 11, 2), datetime(2026, 11, 9))
        # Mon, Tue, (Wed 4th EXDATE'd), Thu 5th moved to 11:00, (Fri 6th cancelled)
        self.assertEqual([(o.start.strftime("%a %H:%M"), o.override) for o in got],
                         [("Mon 09:30", False), ("Tue 09:30", False), ("Thu 11:00", True)])
        self.assertEqual(got[2].end - got[2].start, timedelta(minutes=30))
        self.assertEqual(got[0].summary, "Daily standup, with notes")   # \, unescaped
        self.assertEqual(got[0].start.utcoffset(), timedelta(hours=-5))

    def test_unfold_and_multibyte_fold(self):
        text = "SUMMARY:" + "é" * 80
        folded = fold(text)
        for ln in folded.split("\r\n"):
            self.assertLessEqual(len(ln.encode()), 75)
        self.assertEqual(unfold(folded)[0][1], text)

    def test_all_day_recurring_and_holiday(self):
        cal = parse_ics(wrap("UID:a\r\nDTSTART;VALUE=DATE:20261126\r\nDTEND;VALUE=DATE:20261127\r\nRRULE:FREQ=YEARLY\r\nSUMMARY:Thanks"))
        got = cal.occurrences(date(2026, 1, 1), date(2028, 1, 1))
        self.assertEqual([o.start for o in got], [date(2026, 11, 26), date(2027, 11, 26)])
        self.assertEqual(got[0].end, date(2026, 11, 27))

    def test_utc_and_floating_and_windows_tz(self):
        cal = parse_ics(wrap("UID:u\r\nDTSTART:20261116T090000Z\r\nDTEND:20261116T100000Z\r\nSUMMARY:U",
                             "UID:f\r\nDTSTART:20261116T090000\r\nSUMMARY:F",
                             "UID:w\r\nDTSTART;TZID=Pacific Standard Time:20261116T090000\r\nDURATION:PT1H\r\nSUMMARY:W"))
        got = {o.summary: o.start for o in cal.occurrences(datetime(2026, 11, 16), datetime(2026, 11, 17))}
        self.assertEqual(got["U"], datetime(2026, 11, 16, 9, tzinfo=UTC))
        self.assertIsNone(got["F"].tzinfo)
        self.assertEqual(got["W"].astimezone(UTC).hour, 17)

    def test_exdate_multi_value_and_rdate(self):
        cal = parse_ics(wrap("UID:a\r\nDTSTART:20260101T090000Z\r\nDURATION:PT1H\r\nRRULE:FREQ=DAILY;COUNT=5\r\n"
                             "EXDATE:20260102T090000Z,20260103T090000Z\r\nRDATE:20260110T090000Z\r\nSUMMARY:x"))
        days = [o.start.day for o in cal.occurrences(datetime(2026, 1, 1), datetime(2026, 2, 1))]
        self.assertEqual(days, [1, 4, 5, 10])

    def test_dtstart_always_first_instance(self):
        cal = parse_ics(wrap("UID:a\r\nDTSTART:20261117T090000Z\r\nDURATION:PT1H\r\nRRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=2\r\nSUMMARY:x"))
        days = [o.start.day for o in cal.occurrences(datetime(2026, 11, 1), datetime(2026, 12, 31))]
        self.assertEqual(days, [17, 23])

    def test_override_moved_into_window_from_outside(self):
        cal = parse_ics(wrap("UID:a\r\nDTSTART:20261102T090000Z\r\nDURATION:PT1H\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:x",
                             "UID:a\r\nRECURRENCE-ID:20261109T090000Z\r\nDTSTART:20261201T090000Z\r\nDURATION:PT1H\r\nSUMMARY:moved far"))
        self.assertEqual([o.start.month for o in cal.occurrences(datetime(2026, 11, 1), datetime(2026, 11, 30))], [11, 11])
        self.assertEqual([o.summary for o in cal.occurrences(datetime(2026, 12, 1), datetime(2026, 12, 2))], ["moved far"])

    def test_zero_length_event_appears(self):
        cal = parse_ics(wrap("UID:a\r\nDTSTART:20261102T090000Z\r\nSUMMARY:ping"))
        self.assertEqual(len(cal.occurrences(datetime(2026, 11, 2), datetime(2026, 11, 3))), 1)

    def test_warnings(self):
        cal = parse_ics(wrap("UID:a\r\nSUMMARY:no start", "UID:b\r\nDTSTART:20261102T090000Z\r\nSUMMARY:b",
                             "UID:b\r\nDTSTART:20261103T090000Z\r\nSUMMARY:dup",
                             "UID:zzz\r\nRECURRENCE-ID:20261102T090000Z\r\nDTSTART:20261102T090000Z\r\nSUMMARY:orphan"))
        self.assertEqual(len(cal.warnings), 3)
        self.assertEqual(len(cal.events), 2)

    def test_errors(self):
        bad = {
            "hello": "VCALENDAR",
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VCALENDAR\r\n": "does not match",
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n": "unterminated",
            wrap("UID:a\r\nDTSTART:2026-11-16\r\nSUMMARY:x"): "invalid date-time",
            wrap("UID:a\r\nDTSTART:20261316T090000Z\r\nSUMMARY:x"): "invalid date-time",
            wrap("UID:a\r\nDTSTART;TZID=Mars/Base:20261116T090000\r\nSUMMARY:x"): "unknown TZID",
            wrap("UID:a\r\nDTSTART:20261116T090000Z\r\nDURATION:soon"): "DURATION",
            wrap("UID:a\r\nDTSTART:20261116T090000Z\r\nDTEND:20261115T090000Z"): "before DTSTART",
            wrap("UID:a\r\nDTSTART:20261116T090000Z\r\nDTEND;VALUE=DATE:20261117"): "differs",
            wrap("UID:a\r\nDTSTART:20261116T090000Z\r\nRRULE:FREQ=NEVER"): "bad RRULE",
            wrap("UID:a\r\nDTSTART:20261116T090000Z\r\nBROKENLINE"): "missing ':'",
            wrap("UID:a\r\nDTSTART;TZID=\"unterminated:20261116T090000"): "TZID",
        }
        for text, frag in bad.items():
            with self.assertRaises(ICSError, msg=text[:60]) as cm:
                parse_ics(text)
            self.assertIn(frag, str(cm.exception))

    def test_durations(self):
        for s, td in {"PT30M": timedelta(minutes=30), "P1D": timedelta(days=1), "P1W": timedelta(weeks=1),
                      "P1DT2H3M4S": timedelta(days=1, hours=2, minutes=3, seconds=4), "-PT15M": -timedelta(minutes=15)}.items():
            self.assertEqual(parse_duration(s, 1), td)
            self.assertEqual(parse_duration(fmt_duration(td), 1), td)
        for bad in ("P", "PT", "1H", "P1H"):
            with self.assertRaises(ICSError):
                parse_duration(bad, 1)


class Write(unittest.TestCase):
    def test_roundtrip_team_file(self):
        cal = parse_ics(TEAM)
        text = write_ics(cal)
        self.assertTrue(text.endswith("\r\n"))
        self.assertTrue(all(len(l.encode()) <= 75 for l in text.split("\r\n")))
        cal2 = parse_ics(text)
        rng = (datetime(2026, 11, 1), datetime(2026, 12, 5))
        f = lambda c: [(str(o.start), str(o.end), o.summary, o.override) for o in c.occurrences(*rng)]
        self.assertEqual(f(cal), f(cal2))
        self.assertEqual(cal2.name, "Team")

    def test_write_from_scratch(self):
        ev = Event(uid="x@t", summary="Semi;colon, comma\nnewline", start=datetime(2026, 5, 1, 9), zone=None,
                   duration=timedelta(hours=1), rrule="FREQ=DAILY;COUNT=2", location="Room 1")
        cal = Calendar(events=[ev], name="N")
        text = write_ics(cal, now=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertIn("DTSTAMP:20260101T000000Z", text)
        self.assertIn("SUMMARY:Semi\;colon\\, comma\\nnewline", text)
        back = parse_ics(text).events[0]
        self.assertEqual(back.summary, ev.summary)
        self.assertEqual(back.duration, ev.duration)


if __name__ == "__main__":
    unittest.main()
