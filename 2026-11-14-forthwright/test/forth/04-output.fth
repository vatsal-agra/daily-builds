\ Output words are checked by capturing into memory via a tiny sink: verify with the host test (test/run.js)
\ and here only that they run and leave the stack clean.
T{ 1 . -> }T
T{ -5 u. -> }T
T{ 12 5 .r -> }T
T{ 65 emit -> }T
T{ 3 spaces -> }T
T{ s" hi" type -> }T
T{ cr -> }T
: hello ( -- ) ." hello" ;
T{ hello -> }T
T{ .s -> }T

results
