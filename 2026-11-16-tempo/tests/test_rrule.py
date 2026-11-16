import unittest
from itertools import islice
from datetime import datetime, timedelta

from tests.helpers import d, days
from tempo.rrule import parse_rrule, expand_wall, Rule
from tempo.errors import RRuleError, TempoError
from tempo.recur import Recurrence


def run(rule, start, n=100, **kw):
    return list(islice(expand_wall(parse_rrule(rule), start, **kw), n))


class RFC5545Examples(unittest.TestCase):
    """Worked examples from RFC 5545 section 3.8.5.3 (wall-clock results)."""

    def test_daily_10(self):
        got = run("FREQ=DAILY;COUNT=10", d(1997, 9, 2, 9))
        self.assertEqual(days(got), [f"1997-09-{x:02d}" for x in range(2, 12)])

    def test_every_other_week_su_tu_th(self):
        got = run("FREQ=WEEKLY;INTERVAL=2;WKST=SU;BYDAY=TU,TH", d(1997, 9, 2, 9), 6)
        self.assertEqual(days(got), ["1997-09-02", "1997-09-04", "1997-09-16", "1997-09-18",
                                     "1997-09-30", "1997-10-02"])

    def test_second_to_last_monday(self):
        got = run("FREQ=MONTHLY;COUNT=6;BYDAY=-2MO", d(1997, 9, 22, 9))
        self.assertEqual(days(got), ["1997-09-22", "1997-10-20", "1997-11-17", "1997-12-22",
                                     "1998-01-19", "1998-02-16"])

    def test_us_election_day(self):
        got = run("FREQ=YEARLY;INTERVAL=4;BYMONTH=11;BYDAY=TU;BYMONTHDAY=2,3,4,5,6,7,8",
                  d(1996, 11, 5, 9), 3)
        self.assertEqual(days(got), ["1996-11-05", "2000-11-07", "2004-11-02"])

    def test_third_of_tu_we_th(self):
        got = run("FREQ=MONTHLY;COUNT=3;BYDAY=TU,WE,TH;BYSETPOS=3", d(1997, 9, 4, 9))
        self.assertEqual(days(got), ["1997-09-04", "1997-10-07", "1997-11-06"])

    def test_last_working_day(self):
        got = run("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", d(1997, 9, 29, 9), 3)
        self.assertEqual(days(got), ["1997-09-30", "1997-10-31", "1997-11-28"])

    def test_friday_13th(self):
        got = run("FREQ=MONTHLY;BYDAY=FR;BYMONTHDAY=13", d(1997, 9, 2, 9), 5)
        self.assertEqual(days(got), ["1998-02-13", "1998-03-13", "1998-11-13", "1999-08-13", "2000-10-13"])

    def test_wkst_changes_result(self):
        mo = run("FREQ=WEEKLY;INTERVAL=2;COUNT=4;BYDAY=TU,SU;WKST=MO", d(1997, 8, 5, 9))
        su = run("FREQ=WEEKLY;INTERVAL=2;COUNT=4;BYDAY=TU,SU;WKST=SU", d(1997, 8, 5, 9))
        self.assertEqual(days(mo), ["1997-08-05", "1997-08-10", "1997-08-19", "1997-08-24"])
        self.assertEqual(days(su), ["1997-08-05", "1997-08-17", "1997-08-19", "1997-08-31"])

    def test_invalid_dates_skipped(self):
        got = run("FREQ=MONTHLY;BYMONTHDAY=15,30;COUNT=5", d(1997, 1, 15, 9))
        self.assertEqual(days(got), ["1997-01-15", "1997-01-30", "1997-02-15", "1997-03-15", "1997-03-30"])

    def test_20th_monday_of_year(self):
        got = run("FREQ=YEARLY;BYDAY=20MO;COUNT=3", d(1997, 5, 19, 9))
        self.assertEqual(days(got), ["1997-05-19", "1998-05-18", "1999-05-17"])

    def test_monday_of_week_20(self):
        got = run("FREQ=YEARLY;BYWEEKNO=20;BYDAY=MO;COUNT=3", d(1997, 5, 12, 9))
        self.assertEqual(days(got), ["1997-05-12", "1998-05-11", "1999-05-17"])

    def test_yearday_every_third_year(self):
        got = run("FREQ=YEARLY;INTERVAL=3;COUNT=10;BYYEARDAY=1,100,200", d(1997, 1, 1, 9))
        self.assertEqual(days(got), ["1997-01-01", "1997-04-10", "1997-07-19", "2000-01-01", "2000-04-09",
                                     "2000-07-18", "2003-01-01", "2003-04-10", "2003-07-19", "2006-01-01"])

    def test_every_20_minutes_window(self):
        got = run("FREQ=DAILY;BYHOUR=9,10,11,12,13,14,15,16;BYMINUTE=0,20,40;COUNT=9", d(1997, 9, 2, 9))
        self.assertEqual([x.strftime("%H:%M") for x in got[:4]], ["09:00", "09:20", "09:40", "10:00"])

    def test_hourly_interval_3_until(self):
        got = run("FREQ=HOURLY;INTERVAL=3;UNTIL=19970902T170000", d(1997, 9, 2, 9))
        self.assertEqual([x.hour for x in got], [9, 12, 15])


class Semantics(unittest.TestCase):
    def test_leap_day_yearly(self):
        got = run("FREQ=YEARLY", d(2024, 2, 29), 4)
        self.assertEqual([x.year for x in got], [2024, 2028, 2032, 2036])

    def test_monthly_31_skips_short_months(self):
        got = run("FREQ=MONTHLY", d(2026, 1, 31), 5)
        self.assertEqual([x.month for x in got], [1, 3, 5, 7, 8])

    def test_week_numbering_year_edges(self):
        # 2026-12-28 is Monday of ISO week 53 of 2026; 2027-01-04 begins week 1 of 2027
        got = run("FREQ=YEARLY;BYWEEKNO=53;BYDAY=MO;COUNT=2", d(2026, 1, 1))
        self.assertEqual(days(got), ["2026-12-28", "2032-12-27"])
        got = run("FREQ=YEARLY;BYWEEKNO=1;BYDAY=MO;COUNT=2", d(2027, 1, 1))
        self.assertEqual(days(got), ["2027-01-04", "2028-01-03"])
        got = run("FREQ=YEARLY;BYWEEKNO=-1;BYDAY=SU;COUNT=2", d(2026, 1, 1))
        # last week of week-year 2026 ends Sun 2027-01-03 (a date in calendar year 2027)
        self.assertEqual(days(got), ["2027-01-03", "2028-01-02"])

    def test_negative_monthday_and_yearday(self):
        self.assertEqual(days(run("FREQ=MONTHLY;BYMONTHDAY=-1;COUNT=3", d(2026, 1, 1))),
                         ["2026-01-31", "2026-02-28", "2026-03-31"])
        self.assertEqual(days(run("FREQ=YEARLY;BYYEARDAY=-1;COUNT=2", d(2027, 1, 1))), ["2027-12-31", "2028-12-31"])

    def test_bysetpos_multiple(self):
        got = run("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1,-1;COUNT=4", d(2026, 1, 1))
        self.assertEqual(days(got), ["2026-01-01", "2026-01-30", "2026-02-02", "2026-02-27"])

    def test_bysetpos_full_week_even_before_dtstart(self):
        # dateutil truncates the first week at DTSTART; RFC positions are relative to the whole week
        got = run("FREQ=WEEKLY;BYDAY=WE,MO,SU;BYSETPOS=1;COUNT=2", d(2027, 11, 16, 9))
        self.assertEqual(days(got), ["2027-11-22", "2027-11-29"])

    def test_count_and_until_stop(self):
        self.assertEqual(len(run("FREQ=DAILY;COUNT=7", d(2026, 1, 1))), 7)
        self.assertEqual(len(run("FREQ=DAILY;UNTIL=20260110", d(2026, 1, 1))), 10)
        self.assertEqual(len(run("FREQ=DAILY;UNTIL=20260110T090000", d(2026, 1, 1, 9))), 10)
        self.assertEqual(len(run("FREQ=DAILY;UNTIL=20260110T085959", d(2026, 1, 1, 9))), 9)

    def test_rfc_dtstart_included_even_if_not_matching(self):
        got = run("FREQ=WEEKLY;BYDAY=MO;COUNT=2", d(2026, 11, 17, 9), include_dtstart=True)
        self.assertEqual(days(got), ["2026-11-17", "2026-11-23"])
        got = run("FREQ=WEEKLY;BYDAY=MO;COUNT=2", d(2026, 11, 17, 9))
        self.assertEqual(days(got), ["2026-11-23", "2026-11-30"])

    def test_until_before_dtstart_is_empty(self):
        self.assertEqual(run("FREQ=DAILY;UNTIL=20200101T000000", d(2026, 1, 1), include_dtstart=True), [])

    def test_subdaily_limits(self):
        got = run("FREQ=MINUTELY;INTERVAL=45;BYHOUR=9,10;COUNT=3", d(2026, 1, 1, 8, 15))
        self.assertEqual([x.strftime("%H:%M") for x in got], ["09:00", "09:45", "10:30"])
        got = run("FREQ=SECONDLY;BYSECOND=5,50;COUNT=4", d(2026, 1, 1))
        self.assertEqual([x.second for x in got], [5, 50, 5, 50])

    def test_exhausted_rule_terminates(self):
        # Feb-30-like contradictions are rejected at parse time; a yearly rule that matches
        # nothing within range (Feb 29 every 4th year starting off-cycle) just ends.
        got = run("FREQ=YEARLY;INTERVAL=4;BYMONTH=2;BYMONTHDAY=29", d(2001, 2, 1))
        self.assertEqual(got, [])

    def test_skip_to_equivalence(self):
        rules = ["FREQ=DAILY;INTERVAL=3", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH;WKST=SU",
                 "FREQ=MONTHLY;BYDAY=-1FR", "FREQ=YEARLY;INTERVAL=2;BYMONTH=3,9;BYMONTHDAY=1",
                 "FREQ=HOURLY;INTERVAL=7", "FREQ=MINUTELY;INTERVAL=50;BYHOUR=1,2,3"]
        for rs in rules:
            start = d(2022, 5, 17, 3, 14, 15)
            target = d(2023, 2, 11, 5, 5)
            full = [x for x in islice(expand_wall(parse_rrule(rs), start), 60000) if x >= target][:25]
            fast = [x for x in islice(expand_wall(parse_rrule(rs), start, skip_to=target), 60000) if x >= target][:25]
            self.assertEqual(full, fast, rs)


class Parsing(unittest.TestCase):
    def test_roundtrip_normalises(self):
        r = parse_rrule("freq=monthly;byday=2tu,-1fr,mo;interval=2;wkst=su;byhour=3")
        self.assertEqual(r.to_string(), "FREQ=MONTHLY;INTERVAL=2;WKST=SU;BYDAY=MO,2TU,-1FR;BYHOUR=3")
        self.assertEqual(parse_rrule(r.to_string()), r)

    def test_prefix_and_whitespace(self):
        self.assertEqual(parse_rrule("  RRULE:FREQ=DAILY;COUNT=2 ").count, 2)

    def test_errors_have_positions(self):
        cases = {
            "FREQ=DAILY;BYHOUR=24": "BYHOUR",
            "FREQ=DAILY;BYSECOND=60": "leap seconds",
            "FREQ=WEEKLY;BYDAY=2MO": "need FREQ=MONTHLY",
            "FREQ=DAILY;COUNT=2;UNTIL=20260101": "mutually exclusive",
            "FREQ=BOGUS": "unknown FREQ",
            "COUNT=3": "FREQ is required",
            "FREQ=DAILY;;": "stray",
            "FREQ=DAILY;X-FOO=1": "unknown rule part",
            "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30": "can never match",
            "FREQ=DAILY;BYSETPOS=1": "BYSETPOS requires",
            "FREQ=DAILY;INTERVAL=0": "positive",
            "FREQ=MONTHLY;BYWEEKNO=3": "BYWEEKNO",
            "FREQ=DAILY;UNTIL=20260230": "invalid UNTIL",
            "FREQ=DAILY;BYDAY=XX": "bad BYDAY",
            "FREQ=DAILY;FREQ=WEEKLY": "duplicate",
            "": "empty",
        }
        for src, frag in cases.items():
            with self.assertRaises(RRuleError, msg=src) as cm:
                parse_rrule(src)
            self.assertIn(frag, str(cm.exception), src)
            if src and cm.exception.pos is not None:
                self.assertIn("^", str(cm.exception))

    def test_caret_points_at_value(self):
        try:
            parse_rrule("FREQ=DAILY;BYHOUR=1,25")
        except RRuleError as e:
            line, caret = str(e).splitlines()[-2:]
            self.assertEqual(line.index("25"), caret.index("^"))

    def test_huge_interval_ends_cleanly(self):
        for f in ("DAILY", "WEEKLY", "HOURLY", "MINUTELY", "MONTHLY", "YEARLY"):
            got = Recurrence(f"FREQ={f};INTERVAL=99999999999", datetime(2026, 1, 1), "UTC").take(3)
            self.assertEqual(len(got), 1, f)

    def test_extreme_dates(self):
        self.assertEqual(len(Recurrence("FREQ=DAILY", datetime(9999, 12, 31), "UTC").take(3)), 1)
        self.assertEqual(len(Recurrence("FREQ=WEEKLY", datetime(1, 1, 1), "UTC").take(2)), 2)


if __name__ == "__main__":
    unittest.main()
