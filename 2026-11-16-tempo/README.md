# Tempo

**A from-scratch time-recurrence engine.** It reads the three ways people say "again, later" —
iCalendar **RRULEs**, **cron** expressions and plain **English** — expands them correctly across
daylight-saving changes, and builds a **multi-timezone meeting finder** on top. Pure Python
(stdlib + `zoneinfo`), zero runtime dependencies.

```text
$ python -m tempo say every other tuesday at 9am for 3 times --tz Europe/Paris --start 2026-11-16
rule  : FREQ=WEEKLY;INTERVAL=2;COUNT=3;BYDAY=TU;BYHOUR=9;BYMINUTE=0
means : every other week on Tuesday at 09:00, 3 times
   1  Tue 2026-11-17 09:00:00 +01:00 CET
   2  Tue 2026-12-01 09:00:00 +01:00 CET
   3  Tue 2026-12-15 09:00:00 +01:00 CET

$ python -m tempo cron "*/20 2 * * *" --tz America/New_York --from 2026-03-07T12:00 -n 4
   1  Sun 2026-03-08 03:00:00 -04:00 EDT      <- 02:00-02:59 does not exist today; fires after the gap
   2  Sun 2026-03-08 03:20:00 -04:00 EDT
   3  Sun 2026-03-08 03:40:00 -04:00 EDT
   4  Mon 2026-03-09 02:00:00 -04:00 EDT
```

## Run it

Needs Python 3.9+ (tested on 3.11). No installation step:

```bash
cd 2026-11-16-tempo
python3 -m tempo --help
./demo.sh                      # 29 end-to-end checks + the whole test suite (≈12 s)
./demo.sh /path/to/site-packages   # …plus differential fuzz vs dateutil/croniter if installed there
python3 -m unittest discover -s tests -t .   # tests only
```

CLI commands:

| command | what it does |
|---|---|
| `rrule RULE --start ISO [--tz Z] [-n N] [--exdate ISO] [--rdate ISO] [--gap forward\|skip] [--strict-start]` | expand an RRULE, with an English reading |
| `cron EXPR [--tz Z] [--from ISO] [-n N] [--prev]` | next / previous fire times |
| `meet --people people.json --from ISO --to ISO --minutes N [--stretch] [--buffer M] [--html out.html]` | rank meeting slots (exit 2 + a diagnosis if none) |
| `say PHRASE… [--tz Z] [--start DATE] [-n N]` | English → RRULE → next occurrences |
| `explain RULE` | RRULE → English |
| `ics FILE [--from --to --tz] [--month YYYY-MM --html out.html]` | list events (overrides/cancellations applied) or render a month page |

Library use:

```python
from datetime import datetime
from tempo import Recurrence, Cron, english_to_rrule, parse_ics
Recurrence("FREQ=MONTHLY;BYDAY=-1FR", datetime(2026, 1, 1, 9), "Europe/Paris").take(3)
Cron("0 9 * * MON-FRI", "Asia/Tokyo").next(datetime(2026, 11, 16, 10))
```
Sample inputs live in `examples/` (`team.ics`, `people.json`).

## Features

**Required (all shipped)**
1. **RRULE engine** — FREQ YEARLY→SECONDLY, INTERVAL, COUNT/UNTIL, BYMONTH / BYWEEKNO / BYYEARDAY / BYMONTHDAY / BYDAY (with ordinals like `-2MO`, `20MO`) / BYHOUR / BYMINUTE / BYSECOND / BYSETPOS, WKST, negative indices, lazy iteration, `between/after/before`, RFC-style DTSTART semantics, strict validation with a caret under the offending character, impossible-rule detection (`BYMONTH=2;BYMONTHDAY=30`).
2. **DST-correct zoned expansion** — rules expand in wall-clock time and are resolved to instants afterwards. Nonexistent times move forward past the gap (or are skipped), repeated times take the first occurrence, shifted instants are de-duplicated and kept sorted, EXDATE/RDATE merge, UTC/zone/date `UNTIL`s are honoured exactly.
3. **Cron engine** — 5 fields, lists/ranges/steps/names, `@aliases`, `L`, `L-n`, `5L`, `MON#2`, `?`, Vixie day-of-month/day-of-week semantics, `next`/`prev`/`between`/`iter` in any zone with the same DST policy as the RRULE layer.
4. **Meeting finder** — attendees with zones, working hours (`"Mon-Fri 09:00-12:00,13:00-17:00"`), optional *stretch* hours, one-off and recurring busy blocks (any RRULE, in any zone), buffers, optional attendees, ranked + de-clustered slots, and a plain-language diagnosis when nothing fits. Built on a tested interval algebra (union/intersect/subtract/complement).

**Stretch (all shipped)**
5. **ICS import/export** — unfolding, parameters, TEXT escapes, DATE / floating / UTC / `TZID` (IANA + common Windows names), DTEND/DURATION, RRULE/EXDATE/RDATE, `RECURRENCE-ID` overrides (including moved-out-of-window instances) and `STATUS:CANCELLED`, folded writer with a lossless round-trip.
6. **English ⇄ RRULE** — ~25 phrase shapes ("the last friday of every month at noon", "every 3 days until dec 31", "monthly on the 1st and 15th"), strict errors that underline the unknown word, and RRULE → prose.
7. **HTML renderers** — a self-contained, dark-mode-aware month calendar and a 24-hour meeting-slot view (working / stretch / busy / proposed).
8. **CLI** — six commands, clean one-line errors, meaningful exit codes (0 ok, 1 error, 2 no slot / bad usage).

## How it works (the interesting bits)

* **Candidate-pool expansion.** Each period (a year, month, week, day, hour…) yields a pool of candidate days; every `BYxxx` part is a filter on that pool (which is exactly the RFC's "expand vs limit" table); times of day come from `BYHOUR/MINUTE/SECOND`; `BYSETPOS` picks from the period's sorted result. Week numbers are computed from first principles (`week1 = the wkst-week containing Jan 4`).
* **Skip-ahead.** `between`/`after` jump straight to the right period arithmetically (no COUNT), so a `FREQ=MINUTELY` series from 2020 answers a one-hour query in ~4 ms instead of 4.4 s.
* **Wall clock first, instants second.** `tz.resolve` is the single place where gap/fold policy lives; cron and RRULE share it, so they cannot disagree about DST.
* **Verification by oracle.** 359+ random rules are identical to `dateutil`, 900+ random cron expressions (next *and* prev) identical to `croniter`; the meeting finder is checked against an independent minute-by-minute brute force; interval algebra against a bitmap oracle.

### Deliberate divergences (documented, tested)
* `WEEKLY` + `BYSETPOS`: `dateutil` truncates the first week at DTSTART before applying BYSETPOS; Tempo follows the RFC (positions are relative to the whole week). Pinned by a regression test.
* Cron day fields: any field *starting with* `*` (even `*/4`) ANDs with the other day field, as in Vixie cron; `croniter` ORs when a step is present. `croniter` also mis-parses `N-N` ranges.
* Cron/RRULE fire a repeated (fall-back) wall time **once**; sub-hourly jobs therefore do not run twice in the repeated hour.
* DTSTART is the first instance by default (RFC); pass `--strict-start` / `rfc_dtstart=False` for dateutil behaviour. Human phrases (`say`) use the strict behaviour.
* Not supported: leap seconds (`BYSECOND=60`), `BYEASTER`, `RDATE` periods, `RANGE=THISANDFUTURE` (treated as one instance, with a warning), VTIMEZONE parsing (TZIDs resolve through the IANA database; the writer emits TZIDs without VTIMEZONE), expansion past year 9990.

## Why I chose this today

Nothing in the ledger touches calendars, and time is the classic "looks easy, is a swamp" domain:
`dateutil` and `croniter` disagree with each other and with the RFC in documented ways, so a
from-scratch implementation that can be *differentially tested against both* is a real
correctness exercise rather than a toy. It also scales into a complete product — three input
languages, one DST policy, and a scheduler people actually use (finding a meeting across
Los Angeles, London and Tokyo with recurring stand-ups in the way).

## Where a human could take this next

* Emit real `VTIMEZONE` blocks and parse incoming ones (custom/historic zones, Outlook quirks).
* `RANGE=THISANDFUTURE` overrides, `RDATE;VALUE=PERIOD`, `BYEASTER`, other calendars (lunar, fiscal 4-4-5).
* Free/busy from live sources (CalDAV, Google/Microsoft Graph) feeding `find_slots`; a small web service/UI around the meeting finder with shareable links.
* Smarter scoring: per-person preference curves, fairness across a series of meetings ("rotate the pain"), travel/holiday calendars per country.
* Cron: seconds field / Quartz syntax, `W` weekday-nearest, DST policy switch (`run twice` vs `run once`).
* English: more phrases ("every other friday starting next week"), localisation, and a reverse mapping that always round-trips.
* Packaging: `pyproject.toml`, type hints/`py.typed`, property-based tests with Hypothesis, PyPI release.

## Layout

```
tempo/        dates.py tz.py rrule.py recur.py cron.py scheduler.py ics.py nlp.py render.py cli.py errors.py
tests/        unit, RFC 5545 worked examples, DST, property/oracle tests, CLI, render, differential fuzz, hostile probe
examples/     team.ics  people.json
demo.sh       end-to-end verification (ALL GREEN)
PLAN.md  REVIEW.md   design plan and the adversarial-review log (20 findings, all fixed or documented)
```
