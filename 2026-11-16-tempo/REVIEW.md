# Adversarial review (Phase 3)

Method: fuzz against reference libraries (done in phase 2), then a hostile probe script of ~120
inputs (malformed rules, extreme dates/intervals, DST edge cases, empty/duplicate/naive inputs,
bad CLI input files), plus a read-through of every module looking for lazy shortcuts.
All items below were **reproduced first**, then fixed (status column = state after Phase 3).

| # | Sev | Finding | Repro | Fix | Status |
|---|-----|---------|-------|-----|--------|
| 1 | HIGH | Raw `OverflowError` leaks from `FREQ=DAILY/WEEKLY/HOURLY/MINUTELY/SECONDLY;INTERVAL=99999999999` (and large offsets) instead of ending the series cleanly | `Recurrence("FREQ=DAILY;INTERVAL=99999999999", …).take(3)` | period computation treats date overflow as "series exhausted" | fixed |
| 2 | HIGH | `Recurrence.between/after` rescans from DTSTART every call. A `FREQ=MINUTELY;INTERVAL=5` busy block since 2020 took **4.4 s** for a 1-hour query; the meeting finder calls it per attendee per busy series | timing probe | `expand_wall(skip_to=…)` jumps straight to the right period (arithmetic for every FREQ) when the rule has no COUNT; `between`/`after` use it | fixed |
| 3 | HIGH | CLI `meet` crashes with Python tracebacks on invalid JSON, missing keys (`name`, `minutes`), non-list top level, missing file | `meet --people bad.json` | all input validation raises `TempoError`/`OSError` handling → `error: …`, exit 1 | fixed |
| 4 | MED | `-n 0` / negative `-n` silently print nothing (cron) or misbehave | `cron … -n -1` | argparse type rejects n < 1 | fixed |
| 5 | MED | `expand_wall(include_dtstart=True)` emitted DTSTART even when UNTIL precedes it, while `Recurrence` dropped it — two layers disagree | probe | expand_wall emits nothing when DTSTART > UNTIL | fixed |
| 6 | MED | UNTIL that lands in a DST gap with `gap="skip"` resolved to `None`, silently removing the upper bound in the exact-instant check | `UNTIL=20260308T023000`, `gap=skip` | UNTIL bounds always resolve with the "forward" policy | fixed |
| 7 | MED | Rules that can *never* match (`BYMONTH=2;BYMONTHDAY=30`, `BYMONTH=4,6;BYMONTHDAY=31`) burn **1.6 s** before returning nothing — and silently | probe | static impossibility check at parse time → `RRuleError` naming the contradiction | fixed |
| 8 | LOW | `from tempo.scheduler import *` exports `datetime.time`, `field`, … (no `__all__`) and shadows callers' `time` | my own probe broke on it | explicit `__all__`, unused imports dropped | fixed |
| 9 | LOW | `BYSECOND=60` error says "out of range 0..59" without saying why (leap seconds are not representable) | probe | message explains leap seconds are unsupported | fixed |
| 10 | LOW | Optional attendee who is free only in *stretch* hours earned the same −8 bonus as one in core hours; ranking could prefer a 6 a.m. slot for an optional guest | read-through | bonus 8 (core) vs 2 (stretch) | fixed |
| 11 | LOW | `Cron._day_ok` had a redundant Sunday special-case (`weekday()==6 and 0 in dow or …`) – confusing and untested | read-through | simplified to one expression | fixed |
| 12 | LOW | `WEEKLY` + `BYSETPOS` differs from `dateutil` on the first week (dateutil truncates the first week at DTSTART before applying BYSETPOS; RFC 5545 says positions are relative to the full week's set). We follow the RFC. | fuzz | documented in README ("deliberate divergences") + regression test pins our behaviour | documented |
| 13 | INFO | croniter treats `*/n` in a day field as *restricted* (OR semantics); Vixie cron (the reference implementation) treats any field starting with `*` as unrestricted (AND). We follow Vixie. `N-N` ranges are mis-parsed by croniter. | fuzz | documented | documented |

## Re-run gate
After the fixes the same probe script (`tests/probe_hostile.py`, kept in the repo) shows **zero**
uncaught non-`TempoError` exceptions, the 4.4 s query takes milliseconds, and both fuzzers
still agree with the reference libraries.

---

## Addendum — defects found *after* Phase 3 (Phases 4–5) and fixed

The stretch features and the test suite were themselves reviewed adversarially; they found:

| # | Sev | Finding | Found by | Fix |
|---|-----|---------|----------|-----|
| 14 | HIGH | Month view rendered only Mon–Fri: `1fr` columns grew to the min-content of `nowrap` event text, pushing Sat/Sun out of the clipped grid | screenshot review | `minmax(0,1fr)` + `min-width:0`; regression test asserts it |
| 15 | HIGH | Meeting view bars were drawn from the first slot's start time instead of local midnight, so every bar was shifted ~17 h | screenshot review (bars contradicted the text) | window always starts at local midnight of the display zone; test pins `left:37.50%;width:33.33%` |
| 16 | MED | ICS override instances (`RECURRENCE-ID` moved events) came back as *naive* datetimes while master instances were aware | probe of the sample file | all zoned occurrences are resolved to real instants (`_aware`) |
| 17 | MED | `Schedule.to_recurrence` forced DTSTART as first instance (RFC mode), so "every tuesday" starting on a Monday produced a Monday | CLI demo | `rfc_dtstart=False` for human phrases; test added |
| 18 | MED | English parser error for "every blorp" underlined `every` instead of the unknown word | new unit test | vocabulary-aware caret placement |
| 19 | LOW | English output said "every week on weekdays" / "every month on Monday, Tuesday, … and Friday" | reading output | "every weekday" / "on weekdays" |
| 20 | LOW | Stretch hours were invisible in the meeting view, so "(stretch)" slots looked out of hours | screenshot review | amber stretch band |

**Honest note on my own test mistakes:** six times a *test expectation* was wrong rather than the
engine (e.g. I mislabelled Dec 31 2026 as a Wednesday; Nov 2026 needs six calendar rows; the last
ISO week's Sunday of 2026 is in 2027). Each time the engine's answer was cross-checked against
`dateutil`/the calendar before the expectation was changed — never the other way round.

## Final gate
`./demo.sh <oracle-path>` → **ALL GREEN, 29 checks** (117 unit/property/differential tests included).
