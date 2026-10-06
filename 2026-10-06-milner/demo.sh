#!/usr/bin/env bash
# End-to-end demo: builds the CLI and exercises every feature through it, asserting on the output.
# Usage: ./demo.sh        (exit status 0 = everything works)
set -u
cd "$(dirname "$0")"
BIN="$(mktemp -d)/milner"
go build -o "$BIN" ./cmd/milner || { echo "build failed"; exit 1; }
pass=0; fail=0
export NO_COLOR=1

ok()   { pass=$((pass+1)); printf '  ok    %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  FAIL  %s\n        %s\n' "$1" "$2"; }
# expect NAME EXPECTED-SUBSTRING COMMAND...   (stdout+stderr are searched)
expect() {
  local name="$1" want="$2"; shift 2
  local out; out="$("$@" 2>&1)"
  if grep -qF -- "$want" <<<"$out"; then ok "$name"; else bad "$name" "missing: $want   got: $(head -c 300 <<<"$out" | tr '\n' '|')"; fi
}
# expect_not NAME FORBIDDEN-SUBSTRING COMMAND...
expect_not() {
  local name="$1" nope="$2"; shift 2
  local out; out="$("$@" 2>&1)"
  if grep -qF -- "$nope" <<<"$out"; then bad "$name" "unexpected: $nope"; else ok "$name"; fi
}
exit_code() { # exit_code NAME EXPECTED COMMAND...
  local name="$1" want="$2"; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" = "$want" ]; then ok "$name"; else bad "$name" "exit $got, wanted $want"; fi
}
run_src() { printf '%s\n' "$1" | "$BIN" run -v - ; }
check_src() { printf '%s\n' "$1" | "$BIN" check - ; }

echo "== 1. parser: syntax, layout rule, positioned errors"
expect "layout rule needs no ;;"        "- : int = 3"                 run_src $'let f x = x + 1\nf 2'
expect "match arms at column 1"         "val g : int -> int"          run_src $'let g x = match x with\n| 0 -> 1\n| _ -> 2'
expect "syntax error has a caret"       "^"                           run_src 'let x = (1, 2'
expect "syntax error is positioned"     "<stdin>:1:"                  run_src 'let x = 5 +'
expect "nested comments"                "val x : int = 1"             run_src 'let x = (* a (* b *) c *) 1'

echo "== 2. Hindley-Milner inference"
expect "compose"                        "('a -> 'b) -> ('c -> 'a) -> 'c -> 'b"   "$BIN" type 'fun f g x -> f (g x)'
expect "let-polymorphism"               "int * string"                "$BIN" type 'let id x = x in (id 1, id "a")'
expect "higher-order"                   "('a -> 'b) -> 'a list list -> 'b list list" "$BIN" type 'fun f -> map (map f)'
expect "mismatch caret under operand"   "operand 2 of \`+\`"          run_src 'let x = 1 + "a"'
expect "occurs check"                   "infinite type"               run_src 'let f x = x x'
expect "did-you-mean"                   "did you mean \`length\`"     run_src 'let n = lenght [1]'
expect "value restriction: weak var"    "'_a list ref"                run_src 'let r = ref []'
expect "value restriction: rejection"   "mismatched types"            run_src $'let r = ref []\nlet _ = r := [1]\nlet _ = r := ["a"]'
expect "list element error"             "all elements of a list"      run_src 'let l = [1; 2; "x"]'

echo "== 3. algebraic data types + exhaustiveness"
T=$'type shape = Circle of int | Rect of int * int | Tri of int * int * int | Dot'
expect "ADT declared"                   "type shape = Circle of"      run_src "$T"
expect "missing constructor witness"    "missing: \`Rect (_, _)\`"    check_src "$T"$'\nlet f s = match s with Circle _ -> 1 | Tri _ -> 3 | Dot -> 0'
expect "nested witness"                 "Some None"                   check_src 'let f x = match x with Some (Some _) -> 1 | None -> 0'
expect "list witness"                   "_ :: _ :: _"                 check_src 'let f l = match l with [] -> 0 | [_] -> 1'
expect "redundant arm"                  "can never match"             check_src 'let f x = match x with _ -> 1 | None -> 2'
expect "refutable let"                  "refutable"                   check_src 'let (Some x) = Some 1'
expect_not "exhaustive match is silent" "warning"                     check_src 'let f x = match x with None -> 0 | Some _ -> 1'
exit_code  "--deny-warnings fails"      1  bash -c "printf '%s\n' 'let f x = match x with None -> 0' | '$BIN' check --deny-warnings -"
expect "mutually recursive types"       "val x : a"                   run_src $'type a = A of b | ANil\nand b = B of a | BNil\nlet x = A (B ANil)'
expect "type aliases"                   "type 'a pair = 'a * 'a"      run_src "type 'a pair = 'a * 'a"

echo "== 4. evaluator"
expect "arithmetic"                     "- : int = 7"                 run_src '1 + 2 * 3'
expect "closures + partial application" "- : int = 42"                run_src 'let add x y = x + y in let inc = add 1 in inc 41'
expect "tail calls: 1e6 iterations"     "500000500000"                run_src 'let rec go i acc = if i = 0 then acc else go (i - 1) (acc + i) in go 1000000 0'
expect "mutual recursion"               "(true, false)"               run_src 'let rec even n = if n = 0 then true else odd (n-1) and odd n = if n = 0 then false else even (n-1) in (even 10, even 7)'
expect "refs"                           "- : int = 10"                run_src 'let r = ref 0 in r := !r + 5; r := !r * 2; !r'
expect "prelude: sort"                  "[1; 2; 3; 4; 5]"             run_src 'sort compare [3; 1; 2; 5; 4]'
expect "stack overflow is graceful"     "stack overflow"              run_src 'let rec f n = 1 + f n in f 0'
expect "runtime error is positioned"    "Division_by_zero"            run_src 'print_endline "x"; 1 / 0'
expect "fuel limit stops loops"         "step limit"                  "$BIN" run --fuel 10000 <(echo 'let rec spin n = spin (n + 1) in spin 0')
expect "static scoping"                 "- : int = 6"                 run_src $'let f x = x + 1\nlet g y = f y\nlet f x = x * 100\ng 5'
expect "output flushed before error"    "before"                      run_src 'print_endline "before"; failwith "boom"'

echo "== 5. row-polymorphic records"
expect "open record type"               "{ x : int; y : int; .. } -> int"  "$BIN" type 'fun r -> r.x + r.y'
expect "update + pun"                   "{ x = 1; y = 20 }"           run_src 'let x = 1 in let p = { x; y = 2 } in { p with y = 20 }'
expect "same function, two shapes"      "int * string"                "$BIN" type 'let get r = r.k in (get { k = 1 }, get { k = "s"; z = true })'
expect "missing field"                  "no field \`z\`"              run_src 'let p = { x = 1 } in p.z'
expect "record patterns"                "- : int = 12"                run_src '(fun { a; b; .. } -> a * b) { b = 4; a = 3; c = 0 }'
expect "record exhaustiveness"          "b = false"                   check_src 'let f r = match r with { b = true; n } -> n'

echo "== 6. explain"
expect "explain shows instantiation"    "instantiate \`id\`"          "$BIN" explain 'let id x = x in (id 1, id "a")'
expect "explain shows bindings"         "t2 := int"                   "$BIN" explain 'let id x = x in id 1'
expect "explain shows failure"          "✗ fails"                     "$BIN" explain 'fun x -> x + "a"'
expect "explain result"                 "result: 'a -> 'a"            "$BIN" explain 'fun x -> x'

echo "== 7. typed holes"
expect "hole reports the type"          "must be filled with a value of type \`int\`"  run_src 'let f (n : int) = n + _'
expect "hole lists fitting bindings"    "n : int"                     run_src 'let f (n : int) (s : string) = n + _'

echo "== 8. example gallery (golden outputs)"
for f in examples/*.ml; do
  want="${f%.ml}.out"
  if "$BIN" run --deny-warnings "$f" 2>&1 | cmp -s - "$want"; then ok "$(basename "$f")"; else bad "$(basename "$f")" "output differs from $want"; fi
done

echo "== REPL, CLI polish"
expect "repl evaluates"                 "val x : int = 20"            bash -c "printf 'let x = 20;;\n' | '$BIN' repl"
expect "repl :type"                     "int list -> int list"        bash -c "printf 'let sq x = x * x;;\n:type map sq\n' | '$BIN' repl"
expect "repl survives errors"           "- : int = 3"                 bash -c "printf '1 + true;;\n1 + 2;;\n' | '$BIN' repl"
expect "repl: ;; inside a string"       'val s : string = "a;;b"'     bash -c "printf 'let s = \"a;;b\";;\n' | '$BIN' repl"
exit_code  "empty program is fine"      0  bash -c "printf '' | '$BIN' run -"
exit_code  "type error exits 1"         1  bash -c "printf 'let x = 1 + true' | '$BIN' run -"
exit_code  "bad usage exits 2"          2  "$BIN" frobnicate
expect "CRLF + BOM input"               "- : int = 2"                 bash -c "printf '\xef\xbb\xbflet x = 1\r\nx + 1\r\n' | '$BIN' run -v -"

echo
echo "== go test (unit, fuzz, differential, golden)"
if go test -count=1 ./... >/tmp/milner-demo-test.log 2>&1; then ok "go test ./..."; else bad "go test ./..." "see /tmp/milner-demo-test.log"; fi

echo
echo "demo: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
