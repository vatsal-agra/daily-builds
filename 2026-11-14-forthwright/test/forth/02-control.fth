: t1 ( n -- n ) dup 0< if negate then ;
T{ -5 t1 -> 5 }T
T{ 5 t1 -> 5 }T
: t2 ( n -- n ) 0= if 111 else 222 then ;
T{ 0 t2 -> 111 }T
T{ 9 t2 -> 222 }T
: t3 ( n -- n ) 0 swap 0 ?do 1+ loop ;
T{ 0 t3 -> 0 }T
T{ 7 t3 -> 7 }T
: t4 ( -- n ) 0 10 0 do i + loop ;
T{ t4 -> 45 }T
: t5 ( -- n ) 0 10 0 do i + 2 +loop ;
T{ t5 -> 20 }T
: t6 ( -- n ) 0 0 10 do i + -3 +loop ;
T{ t6 -> 22 }T
: t7 ( -- n ) 0 3 0 do 3 0 do i j * + loop loop ;
T{ t7 -> 9 }T
: t8 ( -- n ) 100 0 do i 7 = if i unloop exit then loop -1 ;
T{ t8 -> 7 }T
: t9 ( -- n ) 0 10 0 do i 5 = if leave then 1+ loop ;
T{ t9 -> 5 }T
: t10 ( n -- n ) begin dup 100 < while 2* repeat ;
T{ 3 t10 -> 192 }T
: t11 ( n -- n ) begin 1+ dup 10 >= until ;
T{ 0 t11 -> 10 }T
: t12 ( n -- n ) begin 1+ dup 5 = if exit then again ;
T{ 0 t12 -> 5 }T
: grade ( n -- n )
  case 1 of 10 endof 2 of 20 endof 3 of 30 endof 0 swap endcase ;
T{ 1 grade -> 10 }T
T{ 3 grade -> 30 }T
T{ 9 grade -> 0 }T
: fact ( n -- n ) dup 2 < if drop 1 exit then dup 1- recurse * ;
T{ 10 fact -> 3628800 }T
: fib ( n -- n ) dup 2 < if exit then dup 1- recurse swap 2 - recurse + ;
T{ 20 fib -> 6765 }T
: ack ( m n -- n ) over 0= if nip 1+ exit then dup 0= if drop 1- 1 recurse exit then 1- over swap recurse swap 1- swap recurse ;
T{ 2 3 ack -> 9 }T
: nested ( n -- n ) dup 0> if dup 5 > if drop 3 else drop 2 then else drop 1 then ;
T{ 10 nested -> 3 }T
T{ 4 nested -> 2 }T
T{ -4 nested -> 1 }T
: loops-in-loops ( -- n ) 0 5 0 do 5 0 do 1+ loop loop ;
T{ loops-in-loops -> 25 }T
: leave-inner ( -- n ) 0 3 0 do 10 0 do i 2 = if leave then 1+ loop loop ;
T{ leave-inner -> 6 }T
: rs-loop ( -- n ) 5 >r 0 r@ 0 ?do i + loop r> drop ;
T{ rs-loop -> 10 }T

results
