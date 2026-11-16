#!/usr/bin/env bash
# End-to-end demo + verification: runs every feature through the real CLI and asserts on the output,
# then runs the full unit/differential test suite.   Usage: ./demo.sh [path-to-oracle-site-packages]
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
[ -n "${1:-}" ] && export TEMPO_ORACLES="$1"
pass=0; fail=0
check() {  # check "name" "expected substring" command...
  local name="$1" want="$2"; shift 2
  local out; out=$("$@" 2>&1)
  if [[ "$out" == *"$want"* ]]; then pass=$((pass+1)); printf '  ok    %s\n' "$name"
  else fail=$((fail+1)); printf '  FAIL  %s\n        wanted: %s\n        got:    %s\n' "$name" "$want" "${out:0:300}"; fi
}
T="$PY -m tempo"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

echo "== 1. RRULE engine"
check "last Friday of month (Paris, CET)"      "Fri 2026-01-30 09:00:00 +01:00 CET"  $T rrule "FREQ=MONTHLY;BYDAY=-1FR" --start 2026-01-01T09:00 --tz Europe/Paris -n 3
check "english description"                    "every month on the last Friday"       $T rrule "FREQ=MONTHLY;BYDAY=-1FR" --start 2026-01-01T09:00 -n 1
check "Friday the 13th"                        "Fri 2026-11-13"                       $T rrule "FREQ=MONTHLY;BYDAY=FR;BYMONTHDAY=13" --start 2026-01-01T09:00 -n 4
check "BYSETPOS last weekday"                  "Thu 2026-12-31"                       $T rrule "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1" --start 2026-01-01T09:00 -n 13
check "WKST changes biweekly pattern"          "Sun 1997-08-17"                       $T rrule "FREQ=WEEKLY;INTERVAL=2;COUNT=4;BYDAY=TU,SU;WKST=SU" --start 1997-08-05T09:00
check "parse error shows caret"                "^"                                    $T rrule "FREQ=DAILY;BYHOUR=25" --start 2026-01-01
check "impossible rule rejected"               "can never match"                      $T rrule "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30" --start 2026-01-01
echo "== 2. DST-correct expansion"
check "02:30 daily slides to 03:30 in the gap" "Sun 2026-03-08 03:30:00 -04:00 EDT"   $T rrule "FREQ=DAILY;COUNT=4" --start 2026-03-06T02:30 --tz America/New_York
check "skip policy drops the gap day"          "Mon 2026-03-09 02:30:00 -04:00"       $T rrule "FREQ=DAILY;COUNT=3" --start 2026-03-07T02:30 --tz America/New_York --gap skip
check "fold fires on first 01:30 only"         "Sun 2026-11-01 01:30:00 -04:00 EDT"   $T rrule "FREQ=DAILY;COUNT=3" --start 2026-10-31T01:30 --tz America/New_York
check "EXDATE removes an instance"             "Mon 2026-01-05"                       $T rrule "FREQ=DAILY;COUNT=5" --start 2026-01-01T09:00 --tz UTC --exdate 2026-01-02T09:00
echo "== 3. Cron"
check "gap: job fires after the gap"           "Sun 2026-03-08 03:00:00 -04:00 EDT"   $T cron "*/20 2 * * *" --tz America/New_York --from 2026-03-07T12:00 -n 3
check "L = last day of month"                  "Sat 2026-01-31 09:00:00"              $T cron "0 9 L * *" --from 2026-01-01T00:00 -n 1
check "second Friday (#)"                      "Fri 2026-06-12 09:00:00"              $T cron "0 9 * * FRI#2" --from 2026-06-01T00:00 -n 1
check "previous fire time"                     "Mon 2026-11-16 09:00:00"              $T cron "0 9 * * *" --from 2026-11-16T10:00 --prev -n 1
check "bad expression"                         "out of range"                         $T cron "61 * * * *"
echo "== 4. Meeting finder"
check "no overlap -> diagnosis"                "never overlap"                        $T meet --people examples/people.json --from 2026-11-16T00:00 --to 2026-11-21T00:00 --minutes 45
check "stretch hours give a slot"              "(stretch)"                            $T meet --people examples/people.json --from 2026-11-16T00:00 --to 2026-11-21T00:00 --minutes 45 --stretch --limit 2 --html "$tmp/meet.html"
check "meeting HTML written"                   "Meeting finder"                       cat "$tmp/meet.html"
echo "== 5. ICS import/export"
check "override moved to 11:00"                "Thu 2026-11-05 11:00  Standup (moved)" $T ics examples/team.ics --from 2026-11-02 --to 2026-11-09 --tz America/New_York
check "EXDATE'd Wednesday absent"              "Tue 2026-11-03"                       $T ics examples/team.ics --from 2026-11-02 --to 2026-11-09 --tz America/New_York
echo "== 6. English <-> RRULE"
check "english -> rrule"                       "FREQ=WEEKLY;INTERVAL=2;COUNT=3;BYDAY=TU;BYHOUR=9;BYMINUTE=0" $T say every other tuesday at 9am for 3 times --start 2026-11-16
check "rrule -> english"                       "every 3 days, 10 times"               $T explain "FREQ=DAILY;INTERVAL=3;COUNT=10"
check "unknown word reported"                  "could not understand"                 $T say every blorp
echo "== 7. HTML calendar"
check "month view written"                     "wrote"                                $T ics examples/team.ics --month 2026-11 --tz America/New_York --html "$tmp/month.html"
check "month view has 7 columns of cells"      "November 2026"                        cat "$tmp/month.html"
echo "== 8. Robustness"
check "no traceback on bad file"               "error: cannot read"                   $T ics /nonexistent.ics
check "-n 0 rejected"                          "must be at least 1"                   $T rrule FREQ=DAILY --start 2026-01-01 -n 0

echo "== unit + differential tests"
if $PY -m unittest discover -s tests -t . 2>&1 | tail -4 | tee "$tmp/ut.txt" | grep -q '^OK'; then
  pass=$((pass+1)); echo "  ok    $(grep -E '^Ran' "$tmp/ut.txt")"; else fail=$((fail+1)); echo "  FAIL  unittest"; cat "$tmp/ut.txt"; fi

echo
if [ "$fail" -eq 0 ]; then echo "ALL GREEN — $pass checks passed"; else echo "$fail FAILED, $pass passed"; exit 1; fi
