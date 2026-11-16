# Tempo

Status: **Phase 3 (adversarial review) complete** — 13 findings in [REVIEW.md](REVIEW.md), all fixed or documented; core features 1–4 implemented and exercised.

(Phase 2 summary:) Required features 1–4 implemented and exercised:

| # | Feature | State |
|---|---------|-------|
| 1 | RRULE engine (`tempo/rrule.py`) | done — 359/359 random rules identical to `dateutil` |
| 2 | DST-correct zoned expansion (`tempo/recur.py`, `tempo/tz.py`) | done |
| 3 | Cron engine (`tempo/cron.py`) | done — 900+ random expressions identical to `croniter` (next and prev) |
| 4 | Multi-timezone meeting finder (`tempo/scheduler.py`) | done |

Try it: `python3 -m tempo rrule "FREQ=MONTHLY;BYDAY=-1FR" --start 2026-01-01T09:00 --tz Europe/Paris -n 5`

Plan: [PLAN.md](PLAN.md). Full README arrives at ship.
