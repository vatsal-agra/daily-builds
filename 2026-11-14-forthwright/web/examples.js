window.EXAMPLES = {
  'Tour (fib, gcd, primes)': `\\ Every word gets a statically inferred stack effect (see the Words tab).
: square ( n -- n )  dup * ;
: cube   ( n -- n )  dup square * ;
: fib    ( n -- n )  dup 2 < if exit then dup 1- recurse swap 2 - recurse + ;
: gcd    ( a b -- g ) begin dup while tuck mod repeat drop ;
: fact   ( n -- n )  1 swap 1+ 1 ?do i * loop ;
: prime? ( n -- f )  \\ n >= 2
  1 swap  dup 2 / 1+ 2 ?do  dup i mod 0= if swap drop 0 swap leave then  loop  drop ;
: primes ( n -- )  2 ?do  i prime? if i . then  loop cr ;

." fib(12) = " 12 fib . cr
." gcd(1071,462) = " 1071 462 gcd . cr
." 10! = " 10 fact . cr
." primes < 40: " 40 primes
`,
  'FizzBuzz': `: fizz ( n -- )
  dup 15 mod 0= if drop ." FizzBuzz " exit then
  dup  3 mod 0= if drop ." Fizz " exit then
  dup  5 mod 0= if drop ." Buzz " exit then
  . ;
: fizzbuzz ( n -- ) 1+ 1 do i fizz loop cr ;
20 fizzbuzz
`,
  'Towers of Hanoi': `variable moves
: hanoi ( n from to via -- )
  3 pick 0= if 2drop 2drop exit then
  3 pick 1-  3 pick  2 pick  4 pick  recurse      \\ move n-1 from -> via
  1 moves +!
  3 pick 1-  1 pick  3 pick  5 pick  recurse         \\ move n-1 via -> to
  2drop 2drop ;
: solve ( n -- ) 0 moves !  1 2 3 hanoi  moves @ . ." moves" cr ;
3 solve  6 solve
`,
  'Collatz (BEGIN/WHILE)': `: collatz-step ( n -- n )  dup 1 and if 3 * 1+ else 2/ then ;
: collatz-len ( n -- len )  0 swap begin dup 1 > while collatz-step swap 1+ swap repeat drop ;
: lengths ( n -- )  1+ 1 do i collatz-len . loop cr ;
." steps to reach 1 for 1..15: " 15 lengths
." 27 takes " 27 collatz-len . ." steps" cr
`,
  'CREATE / DOES>': `: array ( n "name" -- ) create cells allot does> ( i -- addr ) swap cells + ;
10 array squares
: fill-squares 10 0 do i i * i squares ! loop ;
: show-squares 10 0 do i squares @ . loop cr ;
fill-squares show-squares
: const-adder create , does> @ + ;
100 const-adder +100
5 +100 .
`,
  'Lying stack comment': `\\ The comment claims ( a b -- a ) but the body really leaves two items.
\\ The analyzer proves it and refuses to compile the word.
: leaky ( a b -- a )  over + swap ;
`,
  'Branch imbalance': `: oops ( n -- )  dup 0= if drop drop then . ;
`,
  'Loop that leaks': `: ten-ones  10 0 do 1 loop ;
`,
};
