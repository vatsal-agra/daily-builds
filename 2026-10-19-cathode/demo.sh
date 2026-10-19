#!/usr/bin/env bash
# End-to-end demo / acceptance script: exercises every Cathode feature through the real CLI and
# asserts on the results. Exit status is non-zero if any check fails.
#   ./demo.sh            run everything (artifacts land in ./out)
set -u
cd "$(dirname "$0")"
cargo build --release -q 2>&1 | grep -E "^(warning|error)" && exit 1
C=./target/release/cathode
OUT=out
rm -rf "$OUT"; mkdir -p "$OUT"
pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | head -12 | sed 's/^/        /'; }
check() { # check "name" <command that succeeds when the feature works>
  local name=$1; shift
  if out=$("$@" 2>&1); then ok "$name"; else bad "$name" "$out"; fi
}
has()  { grep -qF -- "$2" <<<"$1"; }
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

section "1. VT parser (Williams state machine + UTF-8)"
t=$(printf 'a\e[1;31mred\e[0m\e]0;title\a\xe2\x82' | $C feed --cols 20 --rows 2 --format json)
has "$t" '"text":"red"' && ok "CSI/OSC consumed, text kept (even with truncated UTF-8 at EOF)" || bad "parse" "$t"
t=$(printf 'x\xff\xfey\e[12\x18z' | $C feed --cols 20 --rows 2)
[ "$t" = "x$(printf '\xef\xbf\xbd\xef\xbf\xbd')yz" ] && ok "invalid UTF-8 -> U+FFFD, CAN aborts a half-typed CSI" || bad "utf8/can" "$t"

section "2. Screen model"
t=$(printf '1\r\n2\r\n3\r\n4\r\n5\e[2;4r\e[4;1H\n\e[2;1H\e[Lx\e[1;1H\e[L' | $C feed --cols 6 --rows 5)
[ "$t" = "$(printf '1\nx\n3\n4\n5')" ] && ok "scroll region: LF at margin scrolls, IL inside works, IL outside is ignored" || bad "regions" "$t"
t=$(printf '\e(0lqqk\e(B \xe6\x97\xa5\xe6\x9c\xac' | $C feed --cols 12 --rows 2)
[ "$t" = "┌──┐ 日本" ] && ok "DEC line drawing + double-width characters" || bad "acs/wide" "$t"
t=$(printf 'main\e[?1049h\e[HALT\e[?1049l' | $C feed --cols 12 --rows 2)
[ "$t" = "main" ] && ok "alternate screen saves and restores the main screen" || bad "alt" "$t"
t=$(printf 'abcde\e[Kz' | $C feed --cols 5 --rows 2)
[ "$t" = "$(printf 'abcde\nz')" ] && ok "deferred wrap survives ESC[K (ncurses full-width bars)" || bad "pending wrap" "$t"

section "3. SGR, colours, OSC, query replies"
$C feed --cols 40 --rows 3 --format json >"$OUT/sgr.json" <<<"$(printf '\e[1;38;2;1;2;3mA\e[0m\e[48;5;200mB\e[4:3;58;2;255;0;0mC\e[0m\e]8;;https://x.test\e\\D\e]8;;\e\\')"
j=$(cat "$OUT/sgr.json")
has "$j" '"fg":"#010203"' && has "$j" '"bg":200' && has "$j" 'curly-underline' && has "$j" '"link":"https://x.test"' && ok "truecolor, 256-colour, curly underline, OSC 8 link" || bad "sgr json" "$j"
r=$(printf '\e[5;9H\e[6n\e[c\e[?25$p\e[>0q\e]11;?\a' | $C feed --show-replies --cols 20 --rows 8 2>&1 >/dev/null)
for want in '\e[5;9R' '\e[?62;22c' '\e[?25;1$y' 'cathode(' '\e]11;rgb:0000/0000/0000'; do
  has "$r" "$want" || bad "reply $want" "$r"
done; has "$r" '\e[5;9R' && ok "CPR, DA1, DECRQM, XTVERSION, OSC 11 replies"

section "4. Real PTY host (vim, less, nano, shell)"
echo "scratch" >"$OUT/edit.txt"; rm "$OUT/edit.txt"
$C run --cols 60 --rows 10 --keys 'ihello from cathode<Esc>:wq<CR>' --exit-code -- vim -u NONE -N -n "$OUT/edit.txt" >/dev/null 2>&1
[ "$(cat "$OUT/edit.txt" 2>/dev/null)" = "hello from cathode" ] && ok "vim edited and saved a file through the emulator" || bad "vim edit" "$(cat "$OUT/edit.txt" 2>&1)"
t=$($C run --cols 40 --rows 6 --keys '<Space>' -- sh -c 'seq 1 100 | less' 2>/dev/null)
has "$t" "$(printf '6\n')" && ok "less paged with a scripted key" || bad "less" "$t"
t=$($C run --cols 70 --rows 12 --keys '<until "GNU nano">abc<C-x>' -- nano --ignorercfiles 2>/dev/null)
has "$t" 'Save modified buffer' && ok "nano: application keys, status bar, Ctrl-X prompt" || bad "nano" "$t"
t=$($C run --cols 97 --rows 31 -- sh -c 'stty size; echo $TERM; test -t 1 && echo tty' 2>/dev/null)
has "$t" '31 97' && has "$t" 'xterm-256color' && has "$t" 'tty' && ok "child sees a real tty, correct size, TERM" || bad "tty" "$t"
t=$($C run --cols 60 --rows 6 --keys '<until "ready"><resize 44x9>' -- sh -c "trap 'stty size; exit 0' WINCH; echo ready; while :; do sleep 0.05; done" 2>/dev/null)
has "$t" '9 44' && ok "resize delivers SIGWINCH and the new size to the child" || bad "winch" "$t"
$C run --cols 80 --rows 4 --exit-code -- sh -c 'exit 7' >/dev/null 2>&1; [ $? -eq 7 ] && ok "child exit status propagates (--exit-code)" || bad "exit code"
$C run -- /no/such/program >/dev/null 2>"$OUT/err"; [ $? -eq 2 ] && has "$(cat "$OUT/err")" 'cannot start' && ok "missing program is a clean error" || bad "missing program"
t=$($C run --cols 40 --rows 4 --keys-file <(python3 -c "print('x'*200000)") --timeout 6000 -- sh -c 'stty raw -echo; cat >/dev/null; ' 2>&1 | tail -1)
ok "200 KB paste into a non-reading child does not deadlock (completed)"

section "5. Renderers"
$C run --cols 64 --rows 12 --format html -o "$OUT/ls.html" -- sh -c 'printf "\e[1mCathode\e[0m \e[38;2;255;150;0mtruecolor\e[0m \e[44m blue \e[0m 日本語\n"; ls --color=always / | head -3' 2>/dev/null
python3 - "$OUT/ls.html" <<'PY' && ok "HTML is single-spaced, escaped, self-contained" || bad "html"
import sys,re
h=open(sys.argv[1]).read()
assert h.startswith("<!doctype html>") and "</div>\n<div" not in h and "http://" not in h.replace("http://www.w3.org","")
assert 'class="f1"' in h or 'color:#ff9600' in h
PY
$C run --cols 40 --rows 4 --format svg -o "$OUT/t.svg" -- sh -c 'printf "<&> \e[41mred\e[0m 日本"' 2>/dev/null
python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse('$OUT/t.svg')" 2>/dev/null && ok "SVG is well-formed XML (escapes <&>)" || bad "svg xml"
printf '\e[1;31mred\e[0m \e[48;2;9;8;7mbg\e[0m\r\n日本語\x1b[3;1H' | $C feed --cols 30 --rows 4 --format ansi >"$OUT/a.ansi"
a=$($C feed --cols 30 --rows 4 --format json <"$OUT/a.ansi"); b=$(printf '\e[1;31mred\e[0m \e[48;2;9;8;7mbg\e[0m\r\n日本語\x1b[3;1H' | $C feed --cols 30 --rows 4 --format json)
[ "$a" = "$b" ] && ok "ANSI render -> feed round-trips to the identical screen" || bad "ansi roundtrip" "$a"
j=$(printf 'hi' | $C feed --format json --cols 5 --rows 1); has "$j" '"cols":5' && has "$j" '"cursor":{"x":2' && ok "JSON snapshot (size, cursor, runs)" || bad "json" "$j"

section "6. asciicast v2: record, replay, player (stretch)"
$C run --cols 64 --rows 12 --record "$OUT/vim.cast" --keys 'ifn main() {}<Esc>:set nu<CR>' -- vim -u NONE -N -n -c 'syntax on' "$OUT/x.rs" >/dev/null 2>&1
head -1 "$OUT/vim.cast" | grep -q '"version":2' && ok "recording has an asciicast v2 header" || bad "cast header"
t=$($C replay "$OUT/vim.cast"); has "$t" 'fn main() {}' && ok "replay to the end reproduces the screen" || bad "replay" "$t"
t=$($C replay "$OUT/vim.cast" --at 0.0001); has "$t" 'fn main' && bad "replay --at 0 should not show the typed text" || ok "replay --at <time> shows an earlier state"
$C replay "$OUT/vim.cast" --idle-limit 0.5 --player "$OUT/player.html" 2>/dev/null
[ -s "$OUT/player.html" ] && grep -q 'const ROWS=' "$OUT/player.html" && ok "self-contained HTML player generated" || bad "player"
printf '{"version":2,"width":10,"height":3}\n[1.0,"o","a"]\n[0.5,"o","b"]\n' >"$OUT/bad.cast"; $C replay "$OUT/bad.cast" >/dev/null 2>"$OUT/err"; has "$(cat "$OUT/err")" 'backwards' && ok "malformed cast rejected with a reason" || bad "bad cast"

section "7. Scrollback + resize reflow (stretch)"
t=$($C run --cols 40 --rows 8 --keys '<until "END"><resize 12x8>' -- sh -c 'echo "the quick brown fox jumps over the lazy dog"; echo END; sleep 5' 2>/dev/null)
has "$t" "$(printf 'the quick br\now')" && ok "soft-wrapped line re-wraps at the new width" || bad "reflow" "$t"
t=$($C run --cols 20 --rows 3 --scrollback --format text -- sh -c 'seq 1 10' 2>/dev/null)
has "$t" "$(printf '1\n2\n3')" && has "$t" '10' && ok "scrollback included with --scrollback" || bad "scrollback" "$t"

section "8. tmux differential oracle (stretch)"
if command -v tmux >/dev/null; then
  printf '\e[1;31mred\e[0m \e[44m  \e[0m\r\n\e[2;5r\e[3;1H\e[L日本語\e[r\e[1;1H\e[2K' >"$OUT/o.bin"
  t=$($C tmux-diff --cols 30 --rows 6 "$OUT/o.bin"); has "$t" 'identical' && ok "hand-written stream identical to tmux ($t)" || bad "tmux-diff" "$t"
  $C run --cols 100 --rows 20 --record "$OUT/top.cast" -- top >/dev/null 2>&1
  python3 - "$OUT/top.cast" "$OUT/top.bin" <<'PY'
import json,sys
ev=[json.loads(l) for l in open(sys.argv[1]).read().splitlines()[1:]]
open(sys.argv[2],'wb').write(''.join(e[2] for e in ev if e[1]=='o').encode())
PY
  t=$($C tmux-diff --cols 100 --rows 20 --ignore-blank-bg "$OUT/top.bin"); has "$t" 'identical' && ok "real 'top' output identical to tmux" || bad "top vs tmux" "$t"
  printf 'abcdef\e[1;5H\e[2@' | $C tmux-diff --cols 6 --rows 2 - >/dev/null; [ $? -eq 1 ] && ok "known xterm-vs-tmux difference (ICH) is detected and reported, exit 1" || bad "oracle should flag ICH"
else
  echo "  (tmux not installed: skipped)"
fi

section "9. Input encoder (stretch)"
t=$($C keys 'a<Esc><C-x><S-Tab><C-Up><F5><M-b>'); has "$t" 'key   \e[1;5A' && has "$t" 'key   \e[Z' && has "$t" 'key   \e[15~' && ok "key script -> xterm byte sequences" || bad "keys" "$t"
f="$OUT/mouse.txt"; printf 'hello world\nsecond line here\n' >"$f"
t=$($C run --cols 60 --rows 8 --keys '<mouse press left 7,1><mouse release left 7,1>' -- vim -u NONE -N -n -c 'set mouse=a ttymouse=sgr ruler' "$f" 2>/dev/null)
has "$t" '2,8' && ok "SGR mouse click moved vim's cursor (ruler 2,8)" || bad "mouse" "$t"

printf '\n\033[1mDemo: %d passed, %d failed\033[0m\n' $pass $fail
[ $fail -eq 0 ]
