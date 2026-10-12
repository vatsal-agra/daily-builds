#!/usr/bin/env bash
# Hostile-input battery: every case must end with a clean diagnostic (exit 1 or 2), never a crash
# (exit >= 100 / signal) and never a hang (timeout).
set -u
W="$(dirname "$0")/../target/release/wick"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
expect() { # name expected_exit cmd...
  local name=$1 want=$2; shift 2
  timeout 30 "$@" >"$T/out" 2>&1; local got=$?
  if [ "$got" != "$want" ]; then echo "FAIL $name: exit $got (wanted $want)"; head -3 "$T/out"; fail=1; else echo "ok   $name"; fi
}
w() { printf '%s\n' "$2" > "$T/$1.wat"; }

w mem   '(module (memory 65536) (func (export "f")))'
expect "4 GiB memory is a link error"        1 "$W" run "$T/mem.wat"
w tab   '(module (table 4294967295 funcref))'
expect "4G-element table is a link error"    1 "$W" run "$T/tab.wat"
python3 -c "print('(module (func ' + '('*5000 + 'nop' + ')'*5000 + '))')" > "$T/nest.wat"
expect "5000-deep nesting"                   1 "$W" validate "$T/nest.wat"
w rec   '(module (func $f (export "f") (result i32) (i32.add (call $f) (i32.const 1))))'
expect "unbounded recursion traps"           2 "$W" run "$T/rec.wat" --invoke f
python3 -c "print('(module (func \$f (export \"f\") (result i32) (local ' + 'i64 '*40000 + ') (i32.add (call \$f) (i32.const 1))))')" > "$T/fat.wat"
expect "huge frames cannot eat memory"       2 "$W" run "$T/fat.wat" --invoke f
w spin  '(module (func (export "f") (loop (br 0))))'
expect "infinite loop stopped by fuel"       2 "$W" run "$T/spin.wat" --invoke f --fuel 100000
w lit   '(module (func (f32.const 1e39) (drop)))'
expect "overflowing float literal"           1 "$W" validate "$T/lit.wat"
w trunc '(module (func (export "f") (result i32) (i32.trunc_f64_s (f64.const nan))))'
expect "nan truncation traps"                2 "$W" run "$T/trunc.wat" --invoke f
printf '\0asm\1\0\0\0\1\377\377\377\377\17' > "$T/bad1.wasm"
expect "type section with 4G entries"        1 "$W" validate "$T/bad1.wasm"
printf '\0asm\1\0\0\0\12\4\1\2\0\13' > "$T/bad2.wasm"
expect "code body without function decl"    1 "$W" validate "$T/bad2.wasm"
printf '\0asm\2\0\0\0' > "$T/bad3.wasm"
expect "wrong version"                       1 "$W" validate "$T/bad3.wasm"
head -c 100 /dev/urandom > "$T/rand.wasm"
expect "random bytes (not wasm)"             1 "$W" validate "$T/rand.wasm"
: > "$T/empty.wasm"
expect "empty .wasm file"                    1 "$W" validate "$T/empty.wasm"
: > "$T/empty.wat"
expect "empty .wat file"                     1 "$W" validate "$T/empty.wat"
expect "missing file"                        1 "$W" run "$T/nope.wat"
w args  '(module (func (export "f") (param i32) (result i32) (local.get 0)))'
expect "wrong arity"                         1 "$W" run "$T/args.wat" --invoke f
expect "bad number"                          1 "$W" run "$T/args.wat" --invoke f 12abc
expect "unknown export"                      1 "$W" run "$T/args.wat" --invoke g 1
exit $fail
