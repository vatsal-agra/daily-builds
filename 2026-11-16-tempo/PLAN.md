# Tempo — Plan

## Concept
Tempo is a from-scratch **time-recurrence engine** in pure Python (stdlib + `zoneinfo`): it
understands the three languages people use to say "again, later" — iCalendar RRULEs
(RFC 5545), cron expressions, and plain English — and builds a scheduler on top of them that
finds meeting times across people in different time zones whose calendars are themselves
recurring events.

## Why it's interesting
Recurrence is deceptively hard: "the last weekday of every month", "every other week on
Mon/Wed starting in a week that straddles New Year", "02:30 daily" on the night DST skips
02:30. Most code leans on `dateutil`/`croniter`; here every rule is expanded by an
independent implementation (own week-numbering, own BYSETPOS, own DST resolution), then
differentially tested against those libraries on thousands of random rules.

## Architecture
```
tempo/
  dates.py      calendar math: weekday, ISO weeks, yearday, month lengths, WKST weeks
  tz.py         wall-clock -> instant resolution (gap/fold policy), zone helpers
  rrule.py      RRULE parser, validator, expander (iterator, lazy, bounded)
  cron.py       5-field cron (+ L, W-less, names, @aliases) next/prev/iter
  ics.py        iCalendar reader/writer: VEVENT, RRULE/EXDATE/RDATE, RECURRENCE-ID overrides
  nlp.py        English -> RRULE, RRULE -> English
  scheduler.py  busy-interval algebra + multi-timezone meeting-slot finder
  render.py     self-contained HTML month/agenda renderer
  cli.py        `python -m tempo ...`
tests/          unit + differential (vs dateutil/croniter when installed) + CLI demo
```
Core design: an RRULE expands in *floating wall-clock time* (naive datetimes) period by
period (year/month/week/day...), exactly like the RFC's candidate-set + BYSETPOS model, and
only afterwards is each wall-clock occurrence resolved to an instant in the event's zone.
That separation is what makes DST behaviour explicit and testable.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **RRULE engine**: FREQ YEARLY→SECONDLY, INTERVAL, COUNT/UNTIL, BYMONTH/BYWEEKNO/BYYEARDAY/BYMONTHDAY/BYDAY (with ordinals)/BYHOUR/BYMINUTE/BYSECOND/BYSETPOS, WKST, lazy iteration, `between/after/before`, strict validation with positioned errors | **required** |
| 2 | **DST-correct zoned expansion**: wall-clock rules resolved in an IANA zone; nonexistent times shift forward, ambiguous times take the first occurrence; EXDATE/RDATE merge | **required** |
| 3 | **Cron engine**: 5-field + `@daily` etc., names, ranges/steps/lists, `L`, `#`-nth weekday, standard day-of-month/day-of-week OR semantics, `next`/`prev`/iterate in a zone with DST rules | **required** |
| 4 | **Meeting finder**: attendees with time zones, working hours and recurring busy events → ranked common free slots; busy-interval union/complement algebra | **required** |
| 5 | **ICS import/export**: parse VEVENT with RRULE/EXDATE/RDATE/TZID, line unfolding, RECURRENCE-ID overrides & cancellations; write valid ICS | stretch |
| 6 | **English ⇄ RRULE**: "every other Tuesday until Dec 31" → RRULE and back to prose | stretch |
| 7 | **HTML calendar renderer** (month grid, styled, self-contained) | stretch |
| 8 | CLI tying everything together | stretch |

Required = 1–4. Stretch = 5–8 (goal: ship at least 1; aim for all).
