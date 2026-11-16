import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.helpers import UTC
from tempo.cron import Cron
from tempo.errors import CronError

NY = ZoneInfo("America/New_York")


def u(*a):
    return datetime(*a, tzinfo=UTC)


class Basics(unittest.TestCase):
    def test_step_list_range(self):
        c = Cron("*/20 9-10 * * *")
        got = c.take(u(2026, 11, 16, 0, 0), 7)
        self.assertEqual([x.strftime("%H:%M") for x in got], ["09:00", "09:20", "09:40", "10:00", "10:20", "10:40", "09:00"])

    def test_names_and_aliases(self):
        self.assertEqual(Cron("0 0 * JAN-MAR MON-FRI").next(u(2026, 11, 16)), u(2027, 1, 1))
        self.assertEqual(Cron("@DAILY").next(u(2026, 11, 16, 5)), u(2026, 11, 17))
        self.assertEqual(Cron("@weekly").next(u(2026, 11, 16)), u(2026, 11, 22))
        self.assertEqual(Cron("@hourly").next(u(2026, 11, 16, 5, 30)), u(2026, 11, 16, 6))
        self.assertEqual(Cron("@yearly").next(u(2026, 11, 16)), u(2027, 1, 1))

    def test_last_day_and_nth_weekday(self):
        self.assertEqual([x.day for x in Cron("0 9 L * *").take(u(2026, 1, 1), 3)], [31, 28, 31])
        self.assertEqual([x.day for x in Cron("0 9 L-2 * *").take(u(2026, 1, 1), 2)], [29, 26])
        self.assertEqual(Cron("0 9 * * FRI#2").next(u(2026, 6, 1)), u(2026, 6, 12, 9))
        self.assertEqual(Cron("0 9 * * 5L").next(u(2026, 6, 1)), u(2026, 6, 26, 9))
        self.assertEqual(Cron("0 0 * * 7#1").next(u(2026, 11, 16)), u(2026, 12, 6))

    def test_dom_dow_or_vs_and(self):
        # both restricted -> OR (Vixie)
        c = Cron("0 0 13 * FRI")
        got = [x.strftime("%m-%d") for x in c.take(u(2026, 2, 1), 5)]
        self.assertEqual(got, ["02-06", "02-13", "02-20", "02-27", "03-06"])
        # starred-with-step day field -> AND with the other
        c = Cron("0 0 */10 * MON")
        self.assertTrue(all(x.weekday() == 0 and (x.day - 1) % 10 == 0 for x in c.take(u(2026, 1, 1), 6)))

    def test_sunday_is_0_and_7(self):
        a = Cron("0 0 * * 0").take(u(2026, 11, 16), 2)
        b = Cron("0 0 * * 7").take(u(2026, 11, 16), 2)
        self.assertEqual(a, b)
        self.assertEqual(a[0].weekday(), 6)
        self.assertEqual(Cron("0 0 * * 5-7").next(u(2026, 11, 16)).weekday(), 4)

    def test_next_prev_strictness_and_seconds(self):
        c = Cron("* * * * *")
        self.assertEqual(c.next(u(2026, 11, 16, 10, 0, 0)), u(2026, 11, 16, 10, 1))
        self.assertEqual(c.next(datetime(2026, 11, 16, 10, 0, 30, 500, tzinfo=UTC)), u(2026, 11, 16, 10, 1))
        self.assertEqual(c.prev(u(2026, 11, 16, 10, 0, 0)), u(2026, 11, 16, 9, 59))
        self.assertEqual(c.prev(datetime(2026, 11, 16, 10, 0, 30, tzinfo=UTC)), u(2026, 11, 16, 10, 0))

    def test_prev_next_inverse(self):
        c = Cron("17 3,15 */3 * *")
        t = u(2026, 11, 16, 10)
        for _ in range(20):
            n = c.next(t)
            self.assertEqual(c.prev(n + timedelta(seconds=1)), n)
            self.assertEqual(c.next(c.prev(n)), n)
            t = n

    def test_between_and_iter(self):
        c = Cron("*/5 * * * *")
        self.assertEqual(len(c.between(u(2026, 11, 16), u(2026, 11, 16, 1))), 13)   # inclusive ends
        self.assertEqual(len(list(zip(range(5), c.iter(u(2026, 1, 1))))), 5)

    def test_never_fires(self):
        for e in ("0 0 31 2 *", "0 0 30 2 *"):
            with self.assertRaises(CronError):
                Cron(e).next(u(2026, 1, 1))
        # Feb 29 AND-ed with a Monday fires about every 28 years — still found
        self.assertEqual(Cron("0 0 29 2 *").next(u(2026, 1, 1)), u(2028, 2, 29))


class DST(unittest.TestCase):
    def test_gap_job_fires_once_after_gap(self):
        got = Cron("30 2 * * *", NY).take(datetime(2026, 3, 7, tzinfo=NY), 3)
        self.assertEqual([x.strftime("%m-%d %H:%M") for x in got], ["03-07 02:30", "03-08 03:30", "03-09 02:30"])

    def test_multiple_gap_fires_each_shifted(self):
        got = Cron("*/20 2 * * *", NY).take(datetime(2026, 3, 7, 12, tzinfo=NY), 4)
        self.assertEqual([x.strftime("%m-%d %H:%M") for x in got], ["03-08 03:00", "03-08 03:20", "03-08 03:40", "03-09 02:00"])

    def test_prev_symmetry_in_gap(self):
        got = []
        t = datetime(2026, 3, 9, 0, tzinfo=NY)
        c = Cron("*/20 2 * * *", NY)
        for _ in range(3):
            t = c.prev(t)
            got.append(t.strftime("%H:%M"))
        self.assertEqual(got, ["03:40", "03:20", "03:00"])

    def test_fold_fires_once(self):
        got = Cron("30 1 * * *", NY).take(datetime(2026, 10, 31, 12, tzinfo=NY), 3)
        self.assertEqual([x.strftime("%m-%d %z") for x in got], ["11-01 -0400", "11-02 -0500", "11-03 -0500"])

    def test_every_30_min_across_fold_strictly_increasing(self):
        got = Cron("*/30 * * * *", NY).take(datetime(2026, 11, 1, 0, tzinfo=NY), 8)
        inst = [x.astimezone(UTC) for x in got]
        self.assertEqual(inst, sorted(set(inst)))

    def test_zone_shifts_fire_time(self):
        self.assertEqual(Cron("0 9 * * *", "Asia/Tokyo").next(datetime(2026, 11, 16, 10)), datetime(2026, 11, 17, 9, tzinfo=ZoneInfo("Asia/Tokyo")))

    def test_half_hour_zone(self):
        got = Cron("30 2 * * *", "Australia/Lord_Howe").take(u(2026, 10, 3), 2)
        self.assertEqual([x.strftime("%H:%M") for x in got], ["02:30", "02:30"])


class Errors(unittest.TestCase):
    def test_bad_expressions_with_positions(self):
        bad = {"* * * *": "5 fields", "60 * * * *": "out of range", "* 24 * * *": "out of range",
               "* * 0 * *": "out of range", "* * * 13 *": "out of range", "* * * * 8": "out of range",
               "*/0 * * * *": "bad step", "5-1 * * * *": "backwards", "@weird": "unknown alias",
               "a b c d e": "cannot read", "1,,2 * * * *": "empty list", "* * L-31 * *": "L-n",
               "* * * * 1#9": "#n", "": "5 fields"}
        for e, frag in bad.items():
            with self.assertRaises(CronError, msg=e) as cm:
                Cron(e)
            self.assertIn(frag, str(cm.exception), e)

    def test_bad_zone(self):
        with self.assertRaises(Exception):
            Cron("* * * * *", "Nope/Zone")


if __name__ == "__main__":
    unittest.main()
