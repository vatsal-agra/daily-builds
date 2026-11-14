\ Minimal T{ ... -> ... }T conformance harness, written in Forth and run on Forthwright itself.
\ The words that inspect DEPTH are inherently dynamic, so they opt out of static checking.
variable test-depth
variable actual-n
variable expected-n
variable tests
variable passed
variable failed
create actual 64 cells allot
create expected 64 cells allot

: T{ ( -- ) no-check depth test-depth ! 1 tests +! ;
: -> ( ... -- ) no-check
  depth test-depth @ - dup actual-n !
  0 ?do actual i cells + ! loop ;
: report-fail ( -- ) 1 failed +! ." FAIL test #" tests @ . ;
: compare-all ( -- f ) no-check
  actual-n @ expected-n @ <> if 0 exit then
  -1 actual-n @ 0 ?do
    actual i cells + @  expected i cells + @  <> if drop 0 leave then
  loop ;
: }T ( ... -- ) no-check
  depth test-depth @ - dup expected-n !
  0 ?do expected i cells + ! loop
  compare-all if 1 passed +! else
    report-fail ." expected " expected-n @ 0 ?do expected i cells + @ . loop
    ." got " actual-n @ 0 ?do actual i cells + @ . loop cr then ;
: results ( -- ) ." TESTS " tests @ . ." PASSED " passed @ . ." FAILED " failed @ . cr ;
