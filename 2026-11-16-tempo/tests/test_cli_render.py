import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

from tests.helpers import UTC
from tempo.ics import parse_ics
from tempo.render import render_meeting, render_month
from tempo.scheduler import Attendee, find_slots

ROOT = os.path.join(os.path.dirname(__file__), "..")
TEAM = os.path.join(ROOT, "examples", "team.ics")
PEOPLE = os.path.join(ROOT, "examples", "people.json")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def tempo(*args):
    r = subprocess.run([sys.executable, "-m", "tempo", *args], capture_output=True, text=True, cwd=ROOT)
    return r.returncode, r.stdout, r.stderr


class CLI(unittest.TestCase):
    def test_rrule(self):
        rc, out, err = tempo("rrule", "FREQ=MONTHLY;BYDAY=-1FR", "--start", "2026-01-01T09:00", "--tz", "Europe/Paris", "-n", "3")
        self.assertEqual(rc, 0, err)
        self.assertIn("every month on the last Friday", out)
        self.assertIn("Fri 2026-01-30 09:00:00 +01:00", out)

    def test_rrule_exdate_and_strict_start(self):
        rc, out, _ = tempo("rrule", "FREQ=WEEKLY;BYDAY=MO", "--start", "2026-11-17T09:00", "--tz", "UTC", "-n", "2", "--strict-start")
        self.assertIn("Mon 2026-11-23", out)
        self.assertNotIn("Tue 2026-11-17", out)
        rc, out, _ = tempo("rrule", "FREQ=DAILY;COUNT=3", "--start", "2026-01-01T09:00", "--tz", "UTC", "--exdate", "2026-01-02T09:00")
        self.assertNotIn("2026-01-02", out)

    def test_cron_next_prev(self):
        rc, out, _ = tempo("cron", "*/20 2 * * *", "--tz", "America/New_York", "--from", "2026-03-07T12:00", "-n", "4")
        self.assertEqual(rc, 0)
        lines = [l.split(None, 1)[1] for l in out.strip().splitlines()]
        self.assertTrue(lines[0].startswith("Sun 2026-03-08 03:00:00"))
        rc, out, _ = tempo("cron", "0 9 * * *", "--from", "2026-11-16T10:00", "--prev", "-n", "2")
        self.assertIn("2026-11-16 09:00:00", out)

    def test_meet_and_html(self):
        with tempfile.TemporaryDirectory() as td:
            html = os.path.join(td, "m.html")
            rc, out, err = tempo("meet", "--people", PEOPLE, "--from", "2026-11-16T00:00", "--to", "2026-11-21T00:00",
                                 "--minutes", "45", "--stretch", "--limit", "2", "--html", html)
            self.assertEqual(rc, 0, err)
            self.assertIn("Ava", out)
            self.assertIn("(stretch)", out)
            page = read(html)
            self.assertIn("<!doctype html>", page)
            self.assertIn("Meeting finder", page)

    def test_meet_no_slot_exit_code_and_reason(self):
        rc, out, _ = tempo("meet", "--people", PEOPLE, "--from", "2026-11-16T00:00", "--to", "2026-11-21T00:00", "--minutes", "45")
        self.assertEqual(rc, 2)
        self.assertIn("No slot found", out)
        self.assertIn("never overlap", out)

    def test_say_and_explain(self):
        rc, out, _ = tempo("say", "every", "tuesday", "and", "thursday", "at", "9am", "--tz", "Europe/Paris", "--start", "2026-11-16", "-n", "2")
        self.assertEqual(rc, 0)
        self.assertIn("FREQ=WEEKLY;BYDAY=TU,TH;BYHOUR=9;BYMINUTE=0", out)
        self.assertIn("Tue 2026-11-17 09:00:00 +01:00", out)
        rc, out, _ = tempo("explain", "FREQ=MONTHLY;BYMONTHDAY=-1")
        self.assertEqual(out.strip(), "every month on the last day")

    def test_ics_list_and_month(self):
        rc, out, _ = tempo("ics", TEAM, "--from", "2026-11-02", "--to", "2026-11-09", "--tz", "America/New_York")
        self.assertIn("Thu 2026-11-05 11:00  Standup (moved)  [moved]", out)
        with tempfile.TemporaryDirectory() as td:
            html = os.path.join(td, "c.html")
            rc, out, _ = tempo("ics", TEAM, "--month", "2026-11", "--html", html)
            self.assertEqual(rc, 0)
            self.assertIn("November 2026", read(html))

    def test_errors_are_clean_one_liners(self):
        cases = [
            (["rrule", "FREQ=BOGUS", "--start", "2026-01-01"], "unknown FREQ"),
            (["rrule", "FREQ=DAILY", "--start", "garbage"], "cannot read date/time"),
            (["rrule", "FREQ=DAILY", "--start", "2026-01-01", "--tz", "Mars/Base"], "unknown time zone"),
            (["cron", "* * * *"], "5 fields"),
            (["say", "every", "blorp"], "could not understand"),
            (["ics", "/nonexistent.ics"], "cannot read"),
            (["meet", "--people", "/nonexistent", "--from", "2026-01-05", "--to", "2026-01-06"], "cannot read"),
        ]
        for args, frag in cases:
            rc, out, err = tempo(*args)
            self.assertEqual(rc, 1, args)
            self.assertIn(frag, err, args)
            self.assertNotIn("Traceback", err, args)

    def test_bad_people_files(self):
        with tempfile.TemporaryDirectory() as td:
            for name, body, frag in [("a.json", "{nope", "not valid JSON"), ("b.json", "[]", "non-empty"),
                                     ("c.json", '[{"tz":"UTC"}]', "'name'"), ("d.json", '{"a":1}', "non-empty"),
                                     ("e.json", '[{"name":"a","busy":[{"start":"2026-01-01T09:00"}]}]', "'minutes'"),
                                     ("f.json", '[{"name":"a","busy":[{"start":"2026-01-01T09:00","minutes":-5}]}]', "positive"),
                                     ("g.json", '[{"name":"a","hours":"nonsense"}]', "bad hours spec")]:
                p = os.path.join(td, name)
                with open(p, "w") as f:
                    f.write(body)
                rc, out, err = tempo("meet", "--people", p, "--from", "2026-01-05T00:00", "--to", "2026-01-06T00:00")
                self.assertEqual(rc, 1, name)
                self.assertIn(frag, err, name)
                self.assertNotIn("Traceback", err, name)

    def test_n_must_be_positive(self):
        rc, _, err = tempo("rrule", "FREQ=DAILY", "--start", "2026-01-01", "-n", "0")
        self.assertEqual(rc, 2)
        self.assertIn("at least 1", err)


class Render(unittest.TestCase):
    def test_month_html_structure_and_escaping(self):
        cal = parse_ics(read(TEAM))
        cal.events[0].summary = "<script>alert(1)</script> & co"
        page = render_month(cal, 2026, 11, today=date(2026, 11, 16), zone="America/New_York")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(page.count("class=dow"), 7)
        self.assertEqual(page.count("<div class='day"), 42)
        self.assertIn("minmax(0,1fr)", page)       # regression: nowrap text must not stretch columns
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn(" today", page)
        self.assertIn("ov", page)                   # the moved instance is styled

    def test_month_grid_sizes(self):
        cal = parse_ics(read(TEAM))
        for (y, m, cells) in ((2027, 2, 28), (2026, 9, 35), (2026, 11, 42)):
            self.assertEqual(render_month(cal, y, m).count("<div class='day"), cells, (y, m))
        with self.assertRaises(ValueError):
            render_month(cal, 2026, 13)

    def test_meeting_html_uses_local_midnight_window(self):
        a = Attendee("Ava", "America/Los_Angeles")
        b = Attendee("Ben", "Europe/London")
        slots = find_slots([a, b], datetime(2026, 11, 16, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC),
                           timedelta(minutes=30), limit=1) or []
        page = render_meeting([a, b], datetime(2026, 11, 16, 16, 45, tzinfo=UTC), slots)
        self.assertIn("Ava", page)
        # Ben (UTC+0 in Nov): 09:00-17:00 -> bar starts at 37.5% and is 33.3% wide
        self.assertIn("left:37.50%;width:33.33%", page)
        self.assertIn("No common slot" if not slots else "score", page)


if __name__ == "__main__":
    unittest.main()
