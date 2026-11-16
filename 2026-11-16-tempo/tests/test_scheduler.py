import random
import unittest
from datetime import datetime, timedelta

from tests.helpers import UTC
from tempo.errors import TempoError
from tempo.recur import Recurrence
from tempo.scheduler import (Attendee, Busy, Interval, WorkHours, complement, explain_no_slots,
                             find_slots, intersect, merge, subtract, timeline)

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def mins(ivs, base=T0, span=600):
    """Minute-bitmap oracle."""
    bits = [False] * span
    for i in ivs:
        a = int((i.start - base).total_seconds() // 60)
        b = int((i.end - base).total_seconds() // 60)
        for k in range(max(a, 0), min(b, span)):
            bits[k] = True
    return bits


def rnd_ivs(rng, n=6, span=600):
    out = []
    for _ in range(n):
        a = rng.randint(0, span - 1)
        b = rng.randint(a, min(span, a + 120))
        out.append(Interval(T0 + timedelta(minutes=a), T0 + timedelta(minutes=b)))
    return out


class Algebra(unittest.TestCase):
    def test_properties_against_bitmap_oracle(self):
        rng = random.Random(5)
        for _ in range(300):
            a, b = rnd_ivs(rng), rnd_ivs(rng)
            ma, mb = mins(a), mins(b)
            self.assertEqual(mins(merge(a)), ma)
            self.assertEqual(mins(intersect(a, b)), [x and y for x, y in zip(ma, mb)])
            self.assertEqual(mins(subtract(a, b)), [x and not y for x, y in zip(ma, mb)])
            win = Interval(T0, T0 + timedelta(minutes=600))
            self.assertEqual(mins(complement(a, win)), [not x for x in ma])
            m = merge(a)
            self.assertTrue(all(m[i].end < m[i + 1].start for i in range(len(m) - 1)))   # disjoint, non-touching

    def test_validation(self):
        with self.assertRaises(TempoError):
            Interval(datetime(2026, 1, 1), T0)
        with self.assertRaises(TempoError):
            Interval(T0, T0 - timedelta(hours=1))
        self.assertEqual(merge([Interval(T0, T0)]), [])


class Hours(unittest.TestCase):
    def test_parse_describe(self):
        self.assertEqual(WorkHours.parse("Mon-Fri 9-17").describe(), "Mon-Fri 09:00-17:00")
        self.assertEqual(WorkHours.parse("Fri-Mon 9-17").describe(), "Mon,Fri-Sun 09:00-17:00")
        self.assertEqual(WorkHours.parse("Mon 9-12,13-17; Sat 22-24").describe(), "Mon 09:00-12:00,13:00-17:00; Sat 22:00-24:00")

    def test_bad(self):
        for s in ("", "Mon-Fri", "Mon-Fri 17-9", "Funday 9-5", "Mon 25-26", "Mon 9:99-10"):
            with self.assertRaises(TempoError, msg=s):
                WorkHours.parse(s)

    def test_dst_day_length(self):
        # Sat 22:00-24:00 NY on the spring-forward weekend is still 2h; a 00:00-24:00 Sunday is 23h
        wh = WorkHours.parse("Sun 00:00-24:00")
        ivs = wh.intervals("America/New_York", datetime(2026, 3, 7, tzinfo=UTC), datetime(2026, 3, 10, tzinfo=UTC))
        self.assertEqual(sum((i.duration for i in ivs), timedelta()), timedelta(hours=23))


def brute(attendees, lo, hi, dur, step, buffer, allow_stretch):
    """Independent oracle: test every grid start minute-by-minute against raw definitions."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    sec = int((lo - epoch).total_seconds())
    sec += (-sec) % int(step.total_seconds())
    t = epoch + timedelta(seconds=sec)

    def allowed(a, instant):
        lt = instant.astimezone(a.zone)
        mm = lt.hour * 60 + lt.minute
        tables = [a.hours] + ([a.stretch] if (allow_stretch and a.stretch is not None) else [])
        return any(x <= mm < y for w in tables for x, y in w.table.get(lt.weekday(), ()))

    out = []
    while t + dur <= hi:
        e = t + dur
        ok = True
        for a in attendees:
            if a.optional:
                continue
            if not all(allowed(a, t + timedelta(minutes=k)) for k in range(int(dur.total_seconds() // 60))):
                ok = False
                break
            for b in a.busy:
                ivs = b.intervals(lo - dur, hi + dur, a.zone) if isinstance(b, Busy) else [b]
                if any(t < i.end + buffer and e > i.start - buffer for i in ivs):
                    ok = False
        if ok:
            out.append(t)
        t += step
    return out


class Finder(unittest.TestCase):
    def setUp(self):
        standup = Busy(recurrence=Recurrence("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", datetime(2026, 11, 2, 10), "America/Los_Angeles"),
                       duration=timedelta(minutes=30), title="standup")
        self.ava = Attendee("Ava", "America/Los_Angeles", "Mon-Fri 9-17", "Mon-Fri 7-20", [standup])
        self.ben = Attendee("Ben", "Europe/London", "Mon-Fri 9-17", "Mon-Fri 8-19",
                            [Busy(datetime(2026, 11, 17, 16, tzinfo=UTC), timedelta(hours=1), title="x")])
        self.chi = Attendee("Chi", "Asia/Tokyo", "Mon-Fri 9-18", "Mon-Fri 7-22", optional=True)
        self.lo, self.hi = datetime(2026, 11, 16, tzinfo=UTC), datetime(2026, 11, 21, tzinfo=UTC)

    def all_slots(self, people, **kw):
        return find_slots(people, self.lo, self.hi, kw.pop("dur", timedelta(minutes=45)), limit=10 ** 6,
                          min_separation=timedelta(days=-1), **kw)

    def test_no_overlap_without_stretch_and_diagnosis(self):
        dur = timedelta(minutes=45)
        self.assertEqual(find_slots([self.ava, self.ben], self.lo, self.hi, dur), [])
        msg = " ".join(explain_no_slots([self.ava, self.ben], self.lo, self.hi, dur))
        self.assertIn("never overlap", msg)
        self.assertIn("allow_stretch", msg)

    def test_matches_brute_force_oracle(self):
        for allow in (False, True):
            for buf in (timedelta(0), timedelta(minutes=15)):
                dur = timedelta(minutes=45)
                got = sorted(s.start for s in self.all_slots([self.ava, self.ben], allow_stretch=allow, buffer=buf, dur=dur))
                want = brute([self.ava, self.ben], self.lo, self.hi, dur, timedelta(minutes=15), buf, allow)
                self.assertEqual(got, want, (allow, buf))

    def test_results_never_overlap_busy_and_are_in_hours(self):
        for s in find_slots([self.ava, self.ben, self.chi], self.lo, self.hi, timedelta(minutes=45), allow_stretch=True, limit=20):
            for p in (self.ava, self.ben):
                a, b, flag = s.local[p.name]
                self.assertLess(a.hour, 20)
                self.assertGreaterEqual(a.hour, 7)
            for bz in self.ava.busy_intervals(self.lo, self.hi):
                self.assertFalse(s.start < bz.end and s.end > bz.start)
        sl = find_slots([self.ava, self.ben], self.lo, self.hi, timedelta(minutes=45), allow_stretch=True, limit=20)
        starts = sorted(x.start for x in sl)
        self.assertTrue(all(starts[i] + timedelta(minutes=45) * 2 <= starts[i + 1] for i in range(len(starts) - 1)))

    def test_ranking_prefers_core_over_stretch_and_sweet_spot(self):
        a = Attendee("A", "UTC", "Mon-Fri 9-17", "Mon-Fri 6-22")
        b = Attendee("B", "UTC", "Mon-Fri 9-17", "Mon-Fri 6-22")
        s = find_slots([a, b], self.lo, self.hi, timedelta(hours=1), allow_stretch=True, limit=1)[0]
        self.assertEqual(s.local["A"][2], "core")
        mid = s.start + timedelta(minutes=30)
        self.assertTrue(10 <= mid.hour + mid.minute / 60 <= 16)

    def test_optional_attendee_bonus_and_min_optional(self):
        chi_free = Attendee("Chi", "UTC", "Mon-Fri 9-17", optional=True)
        a = Attendee("A", "UTC", "Mon-Fri 9-17")
        s = find_slots([a, chi_free], self.lo, self.hi, timedelta(hours=1), limit=1)[0]
        self.assertEqual(s.optional_free, ["Chi"])
        busy_chi = Attendee("Chi", "UTC", "Mon-Fri 9-17", optional=True)
        self.assertEqual(find_slots([a, busy_chi], self.lo, self.hi, timedelta(hours=1), min_optional=1, limit=3)[0].optional_free, ["Chi"])
        nobody = Attendee("Chi", "Asia/Tokyo", "Mon-Fri 9-17", optional=True)   # never overlaps A
        self.assertEqual(find_slots([a, nobody], self.lo, self.hi, timedelta(hours=1), min_optional=1), [])
        self.assertTrue(find_slots([a, nobody], self.lo, self.hi, timedelta(hours=1)))

    def test_half_hour_zone_and_dst_day(self):
        a = Attendee("A", "Asia/Kolkata", "Mon-Fri 9-17")
        b = Attendee("B", "UTC", "Mon-Fri 9-17")
        got = find_slots([a, b], self.lo, self.hi, timedelta(hours=1), limit=50)
        self.assertTrue(got)
        for s in got:
            self.assertGreaterEqual(s.start.hour * 60 + s.start.minute, 9 * 60 + 30 - 1)

    def test_validation(self):
        A = Attendee("a")
        with self.assertRaises(TempoError):
            find_slots([A], datetime(2026, 1, 1), datetime(2026, 1, 2), timedelta(hours=1))
        with self.assertRaises(TempoError):
            find_slots([A, A], self.lo, self.hi, timedelta(hours=1))
        with self.assertRaises(TempoError):
            find_slots([], self.lo, self.hi, timedelta(hours=1))
        with self.assertRaises(TempoError):
            find_slots([A], self.hi, self.lo, timedelta(hours=1))
        with self.assertRaises(TempoError):
            find_slots([A], self.lo, self.hi, timedelta(0))
        with self.assertRaises(TempoError):
            find_slots([Attendee("o", optional=True)], self.lo, self.hi, timedelta(hours=1))
        self.assertEqual(find_slots([A], T0, T0 + timedelta(hours=9, minutes=15), timedelta(hours=1)), [])
        with self.assertRaises(TempoError):
            Attendee("x", "Nope/Zone")
        with self.assertRaises(TempoError):
            Busy(start=T0, duration=timedelta(0)).intervals(T0, T0 + timedelta(days=1), "UTC")

    def test_attribute_assignment_is_coerced(self):
        a = Attendee("a")
        a.stretch = "Mon-Fri 7-20"
        a.zone = "Asia/Tokyo"
        self.assertIsInstance(a.stretch, WorkHours)
        self.assertEqual(getattr(a.zone, "key", None), "Asia/Tokyo")

    def test_recurring_busy_in_other_zone_and_timeline(self):
        a = Attendee("a", "UTC", "Mon-Fri 9-17", busy=[Busy(recurrence=Recurrence("FREQ=DAILY", datetime(2026, 1, 1, 12), "America/New_York"),
                                                             duration=timedelta(hours=1))])
        chart = timeline([a], datetime(2026, 11, 17).date())
        self.assertIn("x", chart)
        self.assertEqual(len(chart.splitlines()), 2)
        # 12:00 NY (EST) = 17:00Z, so a 16:30-17:30Z slot must be rejected
        slots = find_slots([a], datetime(2026, 11, 17, 16, tzinfo=UTC), datetime(2026, 11, 17, 18, tzinfo=UTC), timedelta(minutes=30), limit=20)
        self.assertTrue(all(not (s.start < datetime(2026, 11, 17, 18, tzinfo=UTC) and s.end > datetime(2026, 11, 17, 17, tzinfo=UTC)) for s in slots))

    def test_render_text(self):
        s = find_slots([self.ava, self.ben], self.lo, self.hi, timedelta(minutes=45), allow_stretch=True, limit=1)[0]
        text = s.render()
        self.assertIn("Ava", text)
        self.assertIn("stretch", text)


if __name__ == "__main__":
    unittest.main()
