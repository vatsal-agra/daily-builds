\ A tour of Forthwright: every word below gets a statically inferred stack effect.
: square ( n -- n )  dup * ;
: cube   ( n -- n )  dup square * ;
: fib    ( n -- n )  dup 2 < if exit then dup 1- recurse swap 2 - recurse + ;
: gcd    ( a b -- g ) begin dup while tuck mod repeat drop ;
: fact   ( n -- n )  1 swap 1+ 1 ?do i * loop ;
: fizz   ( n -- )
  dup 15 mod 0= if drop ." FizzBuzz " exit then
  dup  3 mod 0= if drop ." Fizz " exit then
  dup  5 mod 0= if drop ." Buzz " exit then
  . ;
: fizzbuzz ( n -- ) 1+ 1 do i fizz loop cr ;

variable counter
: bump ( -- )  1 counter +! ;
: prime? ( n -- f )  \ n >= 2
  1 swap  dup 2 / 1+ 2 ?do  dup i mod 0= if swap drop 0 swap leave then  loop  drop ;
: primes ( n -- )  2 ?do  i prime? if i . then  loop cr ;

: table ( n -- ) 1+ 1 do i dup cube . square . cr loop ;

." fib(20) = " 20 fib . cr
." gcd(1071,462) = " 1071 462 gcd . cr
." 10! = " 10 fact . cr
15 fizzbuzz
30 primes
5 table
