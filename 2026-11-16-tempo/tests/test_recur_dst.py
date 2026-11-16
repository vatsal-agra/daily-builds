import unittest
from datetime import datetime, timedelta, timezone

from tests.helpers import d, UTC
from tempo.recur import Recurrence
from tempo.errors import TempoError
from tempo.tz import classify, resolve, get_zone

NY = "America/New_York"


def hm(xs):
    return [x.strftime("%m-%d %H:%M%z") for x in xs]


class Gap(unittest.TestCase):
    def test_classify(self):
        z = get_zone(NY)
        self.assertEqual(classify(d(2026, 3, 8, 2, 30), z), "gap")
        self.assertEqual(classify(d(2026, 11, 1, 1, 30), z), "fold")
        self.assertEqual(classify(d(2026, 6, 1, 12), z), "ok")

    def test_daily_in_gap_moves_forward_then_returns(self):
        r = Recurrence("FREQ=DAILY;COUNT=4", d(2026, 3, 6, 2, 30), NY)
        self.assertEqual(hm(r), ["03-06 02:30-0500", "03-07 02:30-0500", "03-08 03:30-0400", "03-09 02:30-0400"])

    def test_gap_skip_policy(self):
        r = Recurrence("FREQ=DAILY;COUNT=3", d(2026, 3, 7, 2, 30), NY, gap="skip")
        self.assertEqual(hm(r), ["03-07 02:30-0500", "03-09 02:30-0400"])

    def test_hourly_across_gap_is_unique_and_sorted(self):
        r = Recurrence("FREQ=HOURLY;COUNT=5", d(2026, 3, 8, 0, 30), NY)
        got = r.take(5)
        self.assertEqual(hm(got), ["03-08 00:30-0500", "03-08 01:30-0500", "03-08 03:30-0400", "03-08 04:30-0400"])
        self.assertEqual(got, sorted(got))

    def test_minutely_across_gap_sorted_unique_instants(self):
        got = Recurrence("FREQ=MINUTELY;INTERVAL=20;COUNT=9", d(2026, 3, 8, 1, 0), NY).take(20)
        inst = [x.astimezone(UTC) for x in got]
        self.assertEqual(inst, sorted(set(inst)))
        self.assertEqual(len(inst), 6)

    def test_fold_takes_first_occurrence(self):
        r = Recurrence("FREQ=DAILY;COUNT=3", d(2026, 10, 31, 1, 30), NY)
        self.assertEqual(hm(r), ["10-31 01:30-0400", "11-01 01:30-0400", "11-02 01:30-0500"])

    def test_wall_clock_constant_utc_offset_changes(self):
        got = Recurrence("FREQ=WEEKLY;COUNT=3;BYDAY=SU", d(2026, 3, 1, 9), NY).take(3)
        self.assertEqual([x.hour for x in got], [9, 9, 9])
        self.assertEqual([x.astimezone(UTC).hour for x in got], [14, 13, 13])   # Mar 8 09:00 is already EDT

    def test_exotic_zones(self):
        lh = Recurrence("FREQ=DAILY;COUNT=2", d(2026, 4, 4, 1, 45), "Australia/Lord_Howe").take(2)
        self.assertEqual(len(lh), 2)
        apia = Recurrence("FREQ=DAILY;COUNT=4", d(2011, 12, 29, 12), "Pacific/Apia").take(4)
        insts = [x.astimezone(UTC) for x in apia]
        self.assertEqual(insts, sorted(set(insts)))     # the skipped 30 Dec never duplicates


class SetOps(unittest.TestCase):
    def test_exdate_naive_and_aware(self):
        r = Recurrence("FREQ=DAILY;COUNT=4", d(2026, 3, 6, 9), NY,
                       exdates=[d(2026, 3, 7, 9), datetime(2026, 3, 9, 13, tzinfo=UTC)])
        self.assertEqual([x.day for x in r], [6, 8])

    def test_rdate_merge_and_dedupe(self):
        r = Recurrence("FREQ=DAILY;COUNT=3", d(2026, 3, 6, 9), "UTC",
                       rdates=[datetime(2026, 3, 7, 9, tzinfo=UTC), datetime(2026, 3, 20, 9, tzinfo=UTC)])
        self.assertEqual([x.day for x in r], [6, 7, 8, 20])

    def test_count_not_reduced_by_exdate(self):
        r = Recurrence("FREQ=DAILY;COUNT=5", d(2026, 1, 1, 9), "UTC", exdates=[d(2026, 1, 2, 9)])
        self.assertEqual(len(r.take(99)), 4)   # RFC: EXDATE removes instances of the COUNT set

    def test_until_utc_vs_zone(self):
        r = Recurrence("FREQ=DAILY;UNTIL=20261119T140000Z", d(2026, 11, 17, 9), NY)
        self.assertEqual([x.day for x in r], [17, 18, 19])     # 09:00 EST = 14:00Z is inclusive
        r = Recurrence("FREQ=DAILY;UNTIL=20261119T135959Z", d(2026, 11, 17, 9), NY)
        self.assertEqual([x.day for x in r], [17, 18])

    def test_floating_series(self):
        r = Recurrence("FREQ=DAILY;COUNT=2", d(2026, 1, 1, 9))
        self.assertTrue(r.floating)
        self.assertIsNone(r.take(1)[0].tzinfo)
        with self.assertRaises(TempoError):
            Recurrence("FREQ=DAILY;UNTIL=20261119T140000Z", d(2026, 1, 1, 9)).take(1)

    def test_queries(self):
        r = Recurrence("FREQ=DAILY", d(2026, 1, 1, 9), "UTC")
        a, b = datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 2, 4, tzinfo=UTC)
        self.assertEqual([x.day for x in r.between(a, b)], [1, 2, 3])
        self.assertEqual(r.after(a).day, 1)
        self.assertEqual(r.before(a).day, 31)
        self.assertEqual(r.between(b, a), [])
        self.assertEqual(r.after(datetime(2026, 2, 1, 9, tzinfo=UTC), inclusive=True).day, 1)
        self.assertEqual(r.after(datetime(2026, 2, 1, 9, tzinfo=UTC)).day, 2)

    def test_between_fast_on_ancient_fine_grained_series(self):
        import time
        r = Recurrence("FREQ=MINUTELY;INTERVAL=5", d(2020, 1, 1), "UTC")
        t = time.time()
        got = r.between(datetime(2026, 11, 16, tzinfo=UTC), datetime(2026, 11, 16, 1, tzinfo=UTC))
        self.assertEqual(len(got), 13)
        self.assertLess(time.time() - t, 0.5)

    def test_skip_to_agrees_with_full_scan_across_dst(self):
        r = Recurrence("FREQ=HOURLY;INTERVAL=1", d(2026, 3, 1), NY)
        a, b = datetime(2026, 3, 8, 4, tzinfo=UTC), datetime(2026, 3, 8, 12, tzinfo=UTC)
        full = [x for x in r.take(1000) if a <= x.astimezone(UTC) <= b]
        self.assertEqual(r.between(a, b), full)

    def test_bad_inputs(self):
        with self.assertRaises(TempoError):
            Recurrence("FREQ=DAILY", d(2026, 1, 1), "Mars/Base")
        with self.assertRaises(TempoError):
            Recurrence("FREQ=DAILY", d(2026, 1, 1), "UTC", gap="sideways")
        self.assertEqual(len(Recurrence("FREQ=DAILY;COUNT=2", datetime(2026, 1, 1).date()).take(5)), 2)


if __name__ == "__main__":
    unittest.main()
