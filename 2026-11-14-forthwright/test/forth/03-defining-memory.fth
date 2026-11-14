variable v1
T{ 5 v1 ! v1 @ -> 5 }T
T{ 3 v1 +! v1 @ -> 8 }T
7 constant seven
T{ seven -> 7 }T
T{ seven seven + -> 14 }T
create arr 10 , 20 , 30 ,
T{ arr @ -> 10 }T
T{ arr 2 cells + @ -> 30 }T
T{ arr cell+ @ -> 20 }T
T{ 99 arr cell+ ! arr cell+ @ -> 99 }T
create bytes 1 c, 2 c, 255 c,
T{ bytes c@ -> 1 }T
T{ bytes 2 + c@ -> 255 }T
T{ 300 bytes c! bytes c@ -> 44 }T
: array ( n "name" -- ) create cells allot does> ( i -- a ) swap cells + ;
5 array a5
T{ 11 3 a5 ! 3 a5 @ -> 11 }T
: counter ( "name" -- ) create 0 , does> ( -- n ) dup @ 1+ dup rot ! ;
counter c1
T{ c1 c1 c1 -> 1 2 3 }T
: adder ( n "name" -- ) create , does> ( x -- y ) @ + ;
10 adder +10
T{ 5 +10 -> 15 }T
5 value val
T{ val -> 5 }T
T{ 9 to val val -> 9 }T
: set-val ( n -- ) to val ;
T{ 1 set-val val -> 1 }T
create buf 8 allot
T{ buf 8 65 fill buf c@ buf 7 + c@ -> 65 65 }T
T{ buf 8 erase buf c@ -> 0 }T
T{ s" abcdef" buf swap move buf c@ -> 97 }T
T{ s" abc" drop c@ -> 97 }T
T{ s" abc" nip -> 3 }T
: sa s" abc" ; : sb s" abd" ;
T{ sa sa compare -> 0 }T
T{ sa sb compare -> -1 }T
T{ sb sa compare -> 1 }T
T{ here 4 allot here swap - -> 4 }T
T{ 11 22 buf 2! buf 2@ -> 11 22 }T
: str ( -- a n ) s" hello" ;
T{ str nip -> 5 }T
T{ str drop 1+ c@ -> 101 }T
T{ char A -> 65 }T
: ch ( -- n ) [char] z ;
T{ ch -> 122 }T
: sq ( n -- n ) dup * ;
T{ 6 ' sq execute -> 36 }T
: apply-twice ( n xt -- n ) dup >r execute r> execute ;
T{ 3 ' sq apply-twice -> 81 }T
: lit-test ( -- n ) [ 6 7 * ] literal ;
T{ lit-test -> 42 }T
T{ 4 cells -> 16 }T
: early ( -- n ) 1 ;
: use-early ( -- n ) early ;
: early ( -- n ) 2 ;
T{ use-early -> 1 }T
T{ early -> 2 }T

results
