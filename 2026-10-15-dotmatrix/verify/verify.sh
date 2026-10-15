#!/usr/bin/env bash
# Runs every check for Dotmatrix: static analysis, unit tests, CLI end-to-end
# demos for every command, abuse cases, and (when Node + Playwright are
# available) the browser player. MUTANTS=1 also runs mutation testing.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT="${OUT:-$(mktemp -d)}"
PASS=0; FAIL=0
ok()   { echo "  ok    $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
check() { local desc="$1"; shift; if "$@" >"$OUT/last.log" 2>&1; then ok "$desc"; else bad "$desc"; sed 's/^/        /' "$OUT/last.log" | head -15; fi; }
expect_fail() { local desc="$1"; shift; "$@" >"$OUT/last.log" 2>&1; local rc=$?; if [ $rc -ne 0 ] && ! grep -q "goroutine\|panic:" "$OUT/last.log"; then ok "$desc (exit $rc, clean message)"; else bad "$desc (rc=$rc)"; head -5 "$OUT/last.log"; fi; }

echo "== build"
check "go build ./..." go build ./...
go build -o "$OUT/dm" ./cmd/dotmatrix || exit 1
DM="$OUT/dm"
check "gofmt clean" test -z "$(gofmt -l .)"
check "go vet ./..." go vet ./...

echo "== unit + integration tests"
check "go test ./... (asm, gb, cli)" go test ./... -count=1

echo "== assembler / disassembler"
for r in cputest snake mbc1test; do
  check "asm roms/$r.asm" "$DM" asm roms/$r.asm -o "$OUT/$r.gb" -sym "$OUT/$r.sym"
  check "info $r.gb (header + checksums valid)" "$DM" info "$OUT/$r.gb"
done
check "dis prints real instructions" bash -c "'$DM' dis '$OUT/snake.gb' -from 0x150 -len 24 | grep -q 'ldh \[\$FF01\], a'"
check "symbol file has labels" grep -q "put_text" "$OUT/snake.sym"
check "round trip: asm → dis → asm is byte-identical" go test ./asm -run 'RoundTrip' -count=1

echo "== CPU / peripherals inside the emulator"
check "cputest ROM: PASS" "$DM" test roms/cputest.asm
check "mbc1test ROM: bank switching + RAM: PASS" "$DM" test roms/mbc1test.asm
rm -f "$OUT/battery.sav"
for n in 1 2 3; do "$DM" run roms/mbc1test.asm -frames 40 -serial -save "$OUT/battery.sav" 2>/dev/null | grep BOOTS= > "$OUT/boot$n.txt"; done
check "battery RAM persists across runs (BOOTS=01,02,03)" bash -c "grep -q 'BOOTS=01' '$OUT/boot1.txt' && grep -q 'BOOTS=02' '$OUT/boot2.txt' && grep -q 'BOOTS=03' '$OUT/boot3.txt'"

echo "== PPU / game"
check "snake: title screen → PNG" "$DM" run roms/snake.asm -frames 30 -png "$OUT/title.png"
check "snake: scripted play → PNG + WAV" "$DM" run roms/snake.asm -frames 400 -keys "5:start,6:-start,60:down,100:left,140:up" -png "$OUT/play.png" -scale 3 -wav "$OUT/play.wav"
check "PNG is 480x432" bash -c "python3 - <<PY
import struct,sys
d=open('$OUT/play.png','rb').read(); w,h=struct.unpack('>II',d[16:24]); sys.exit(0 if (w,h)==(480,432) else 1)
PY"
check "WAV has audio (peak > 1000)" bash -c "python3 - <<PY
import wave,struct,sys
w=wave.open('$OUT/play.wav'); n=w.getnframes(); d=struct.unpack('<%dh'%(n*2), w.readframes(n))
sys.exit(0 if max(map(abs,d))>1000 and w.getframerate()==44100 else 1)
PY"
check "ASCII render shows the board" bash -c "'$DM' run roms/snake.asm -frames 60 -keys 5:start -ascii 2>/dev/null | grep -q '#'"

echo "== save states"
check "save state at frame 60" "$DM" run roms/snake.asm -frames 60 -keys "5:start,6:-start" -savestate "$OUT/s.dmst"
check "resume from the state" "$DM" run roms/snake.asm -frames 20 -loadstate "$OUT/s.dmst"
expect_fail "state for another ROM is rejected" "$DM" run roms/cputest.asm -frames 1 -loadstate "$OUT/s.dmst"

echo "== debugger / trace"
check "trace prints N instructions" bash -c "[ \$('$DM' trace roms/cputest.asm -n 20 | wc -l) -eq 20 ]"
cat > "$OUT/dbg.txt" <<DBG
b print_char if a == 0x50
c 3000
r
w total
hist 3
bl
u print_hex8 3
x 0xC000 16
q
DBG
check "scripted debugger session (conditional bp, watch, history)" bash -c "'$DM' debug roms/cputest.asm < '$OUT/dbg.txt' | grep -q 'breakpoint 1 at' && '$DM' debug roms/cputest.asm < '$OUT/dbg.txt' | grep -q 'watch write C000'"

echo "== abuse / error handling (clean messages, no panics)"
head -c 100 /dev/urandom > "$OUT/junk.gb"
printf '\tld a, (hl)\n\tld b, 300\n\tjr nowhere\n' > "$OUT/bad.asm"
expect_fail "tiny junk file" "$DM" run "$OUT/junk.gb"
expect_fail "missing file" "$DM" run /no/such/file.gb
expect_fail "assembly errors" "$DM" asm "$OUT/bad.asm"
check "…reports all three errors" bash -c "'$DM' asm '$OUT/bad.asm' 2>&1 | grep -c 'bad.asm:' | grep -q 3"
expect_fail "bad key script" "$DM" run roms/snake.asm -keys "x:nope"
expect_fail "negative frames" "$DM" run roms/snake.asm -frames -3
expect_fail "unknown command" "$DM" frobnicate
expect_fail "dis past end of ROM" "$DM" dis "$OUT/cputest.gb" -from 0xFFFF
printf '\t.org 0x100\n\tjp 0x150\n\t.org 0x150\n\txor a\n\tldh [0x40], a\n\tjr $\n' > "$OUT/lcdoff.asm"
check "program that switches the LCD off doesn't hang run" timeout 20 "$DM" run "$OUT/lcdoff.asm" -frames 10

echo "== browser player"
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null || [ -d /opt/node22/lib/node_modules/playwright ]; then
  PORT=$((20000 + RANDOM % 20000))
  "$DM" serve -addr 127.0.0.1:$PORT >"$OUT/serve.log" 2>&1 &
  SERVER=$!
  sleep 1
  check "web e2e (Playwright: load, play, debug, assemble, errors, save/load, mobile)" node verify/web_e2e.js "http://127.0.0.1:$PORT/" "$OUT"
  kill $SERVER 2>/dev/null
else
  echo "  skip  Playwright not installed"
fi

if [ "${MUTANTS:-0}" = "1" ]; then
  echo "== mutation testing"
  check "all mutants killed" python3 verify/mutants.py
fi

echo
echo "artifacts in $OUT"
echo "passed: $PASS   failed: $FAIL"
[ $FAIL -eq 0 ]
