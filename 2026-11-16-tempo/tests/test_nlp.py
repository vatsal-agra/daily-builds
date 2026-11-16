import unittest
from datetime import date

from tempo.errors import NLError
from tempo.nlp import english_to_rrule, rrule_to_english
from tempo.rrule import parse_rrule

CASES = {
    "every day": "FREQ=DAILY",
    "daily at 9am": "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
    "every weekday at 8:30": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=30",
    "weekends": "FREQ=WEEKLY;BYDAY=SA,SU",
    "every other tuesday until dec 31 2027": "FREQ=WEEKLY;INTERVAL=2;UNTIL=20271231;BYDAY=TU",
    "every mon and wed at 3pm": "FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=15;BYMINUTE=0",
    "every tuesday, thursday and saturday": "FREQ=WEEKLY;BYDAY=TU,TH,SA",
    "every other week on monday and thursday": "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH",
    "biweekly": "FREQ=WEEKLY;INTERVAL=2",
    "the last friday of every month": "FREQ=MONTHLY;BYDAY=-1FR",
    "second thursday of every month at noon": "FREQ=MONTHLY;BYDAY=2TH;BYHOUR=12;BYMINUTE=0",
    "every first monday of the month": "FREQ=MONTHLY;BYDAY=1MO",
    "every month on the 15th": "FREQ=MONTHLY;BYMONTHDAY=15",
    "monthly on the 1st and 15th": "FREQ=MONTHLY;BYMONTHDAY=1,15",
    "on the last day of every month": "FREQ=MONTHLY;BYMONTHDAY=-1",
    "every 6 months on the 1st": "FREQ=MONTHLY;INTERVAL=6;BYMONTHDAY=1",
    "every year on march 3": "FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=3",
    "every 4th of july": "FREQ=YEARLY;BYMONTH=7;BYMONTHDAY=4",
    "yearly on jan 1 at midnight": "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1;BYHOUR=0;BYMINUTE=0",
    "every 3 days for 10 times": "FREQ=DAILY;INTERVAL=3;COUNT=10",
    "every 2 hours": "FREQ=HOURLY;INTERVAL=2",
    "every three days": "FREQ=DAILY;INTERVAL=3",
    "every 15 minutes": "FREQ=MINUTELY;INTERVAL=15",
    "every day at 9 and 15:00 until 2027-03-01": "FREQ=DAILY;UNTIL=20270301;BYHOUR=9,15;BYMINUTE=0",
    "EVERY   Other   MONDAY": "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO",
}


class Forward(unittest.TestCase):
    def test_cases(self):
        for text, want in CASES.items():
            self.assertEqual(english_to_rrule(text, 2026).rule, parse_rrule(want), text)

    def test_start_date_and_binding(self):
        sch = english_to_rrule("every tuesday and thursday at 9am starting nov 17 2026")
        self.assertEqual(sch.start, date(2026, 11, 17))
        got = sch.to_recurrence("Europe/Paris").take(3)
        self.assertEqual([x.strftime("%a %d %H:%M") for x in got], ["Tue 17 09:00", "Thu 19 09:00", "Tue 24 09:00"])

    def test_first_occurrence_matches_rule_not_start_date(self):
        sch = english_to_rrule("every tuesday")
        first = sch.to_recurrence("UTC", date(2026, 11, 16)).take(1)[0]   # a Monday
        self.assertEqual(first.weekday(), 1)

    def test_errors_are_positioned_and_specific(self):
        bad = {"": "empty", "every blorp": "could not understand", "every day at 25:00": "cannot read time",
               "until never": "cannot read date", "every tuesday at 9 and 14:30": "clean grid",
               "every 0 days": "at least 1", "on the 40th of every month": "out of range",
               "every day until feb 30 2027": "invalid date", "0 times": "at least 1"}
        for text, frag in bad.items():
            with self.assertRaises(NLError, msg=text) as cm:
                english_to_rrule(text, 2026)
            self.assertIn(frag, str(cm.exception), text)

    def test_unknown_word_is_underlined(self):
        with self.assertRaises(NLError) as cm:
            english_to_rrule("every blorp")
        text_line, caret_line = str(cm.exception).splitlines()[-2:]
        self.assertEqual(caret_line.index("^"), text_line.index("blorp"))


class Backward(unittest.TestCase):
    def test_descriptions(self):
        want = {
            "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR": "every weekday",
            "FREQ=WEEKLY;BYDAY=MO,WE": "every Monday and Wednesday",
            "FREQ=MONTHLY;BYDAY=-1FR": "every month on the last Friday",
            "FREQ=MONTHLY;BYMONTHDAY=1,15": "every month on the 1st and 15th",
            "FREQ=MONTHLY;BYMONTHDAY=-1": "every month on the last day",
            "FREQ=DAILY;INTERVAL=3;COUNT=10": "every 3 days, 10 times",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;UNTIL=20271231": "every other week on Tuesday, until December 31, 2027",
            "FREQ=YEARLY;BYMONTH=7;BYMONTHDAY=4": "every year on the 4th of July",
            "FREQ=DAILY;BYHOUR=9,15;BYMINUTE=0": "every day at 09:00 and 15:00",
            "FREQ=YEARLY;BYWEEKNO=20;BYDAY=MO": "every year on Monday in week 20",
            "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1": "every month on weekdays (taking the last match of each period)",
            "FREQ=HOURLY;INTERVAL=2": "every 2 hours",
            "FREQ=MONTHLY;BYMONTHDAY=-3": "every month on the 3rd-to-last day",
        }
        for rule, text in want.items():
            self.assertEqual(rrule_to_english(rule), text, rule)

    def test_round_trip_phrases(self):
        """english -> rule -> english -> rule must land on the same rule (for the invertible forms)."""
        for text in CASES:
            r1 = english_to_rrule(text, 2026).rule
            back = rrule_to_english(r1)
            try:
                r2 = english_to_rrule(back, 2026).rule
            except NLError:
                continue   # some prose (e.g. "every week on weekdays at 08:30") is output-only
            self.assertEqual(r1, r2, f"{text!r} -> {back!r}")


if __name__ == "__main__":
    unittest.main()
