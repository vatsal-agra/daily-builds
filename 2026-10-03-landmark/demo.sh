#!/usr/bin/env bash
# End-to-end demo + verification: exercises every Landmark feature through the real CLI and asserts on the output.
set -uo pipefail
cd "$(dirname "$0")"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n      %s\n' "$1" "${2:-}"; }
expect() { # expect "<name>" "<haystack>" "<regex>"
  if grep -Eq "$3" <<<"$2"; then ok "$1"; else bad "$1" "wanted /$3/ in: $(tr '\n' '|' <<<"$2" | cut -c1-300)"; fi; }
refute() { if grep -Eq "$3" <<<"$2"; then bad "$1" "did not want /$3/ in: $(tr '\n' '|' <<<"$2" | cut -c1-300)"; else ok "$1"; fi; }

echo "== build"
go build -o "$W/lm" ./cmd/landmark || { echo "build failed"; exit 1; }
LM="$W/lm"

echo "== 1. synth + index (features: synthesizer, WAV I/O, constellation, persistent index)"
out=$($LM synth -n 10 -dur 45 -out "$W/corpus"); expect "synth wrote 10 songs" "$out" 'song0010.wav'
out=$($LM index -out "$W/lib.lmk" "$W/corpus"); expect "index built" "$out" 'wrote .*lib.lmk: 10 songs'
out=$($LM info -db "$W/lib.lmk");               expect "info lists songs"  "$out" 'song0007'

echo "== 2. identification (features: hash voting, offset recovery)"
$LM degrade -in "$W/corpus/song0004.wav" -start 17 -len 8 -out "$W/clean.wav" >/dev/null
out=$($LM identify -db "$W/lib.lmk" "$W/clean.wav")
expect "clean clip -> song0004" "$out" 'MATCH +song0004'
expect "clean clip offset ≈17 s" "$out" 'starts at 1(6\.9|7\.0)[0-9]?s'

echo "== 3. robustness (features: degradation toolkit)"
declare -A Q=(
 [noise 0 dB]="-snr 0"
 [pink -3 dB]="-snr -3 -pink"
 [lowpass 1.5k]="-lowpass 1500"
 [distortion]="-distort 12"
 [reverb]="-reverb 0.8"
 [quiet -40 dB + noise]="-snr 20 -gain -40"
 [phone chain]="-lowpass 3000 -distort 4 -snr 5 -pink"
)
for k in "${!Q[@]}"; do
  $LM degrade -in "$W/corpus/song0006.wav" -start 21 -len 12 ${Q[$k]} -out "$W/q.wav" >/dev/null
  out=$($LM identify -db "$W/lib.lmk" "$W/q.wav"); expect "12 s clip, $k -> song0006" "$out" 'MATCH +song0006'
done

echo "== 4. speed tolerance (stretch)"
$LM degrade -in "$W/corpus/song0009.wav" -start 10 -len 10 -speed 1.04 -out "$W/fast.wav" >/dev/null
out=$($LM identify -db "$W/lib.lmk" "$W/fast.wav" || true)
refute "×1.04 clip is not accepted without the search" "$out" 'MATCH +song0009'
out=$($LM identify -db "$W/lib.lmk" -speed 0.06 "$W/fast.wav")
expect "speed search finds song0009" "$out" 'MATCH +song0009'
expect "speed estimate ≈1.04" "$out" 'speed ×1\.0(35|40|45)'

echo "== 5. rejection (features: reject logic)"
$LM synth -n 3 -seed 9000 -dur 30 -out "$W/unknown" >/dev/null
for f in "$W"/unknown/*.wav; do
  $LM degrade -in "$f" -start 8 -len 10 -out "$W/u.wav" >/dev/null
  out=$($LM identify -db "$W/lib.lmk" -speed 0.06 "$W/u.wav"); rc=$?
  expect "$(basename "$f") (never indexed) -> NO MATCH" "$out" 'NO MATCH'
  [ "$rc" = 3 ] && ok "exit code 3 on no match" || bad "exit code 3 on no match" "rc=$rc"
done

echo "== 6. timeline (stretch)"
$LM mix -out "$W/mix.wav" -snr 12 "$W/corpus/song0003.wav:5-30" "$W/corpus/song0001.wav:20-45" "$W/corpus/song0008.wav:0-25" >/dev/null
out=$($LM timeline -db "$W/lib.lmk" "$W/mix.wav")
expect "segment 1 = song0003" "$out" ' 0\.0–2[34]\.[05] +song0003 +5\.0s'
expect "segment 2 = song0001" "$out" 'song0001'
expect "segment 3 = song0008" "$out" 'song0008'
[ "$(grep -c 'song00' <<<"$out")" = 3 ] && ok "exactly 3 segments" || bad "exactly 3 segments" "$out"

echo "== 7. HTML visualizer (stretch)"
$LM viz -db "$W/lib.lmk" -out "$W/report.html" "$W/clean.wav" >/dev/null
[ -s "$W/report.html" ] && ok "report written" || bad "report written"
expect "report names the song" "$(cat "$W/report.html")" '"Song":"song0004"'
refute "report has no unresolved placeholders" "$(cat "$W/report.html")" '__(DATA|TITLE)__'

echo "== 8. incremental indexing + eval harness"
$LM synth -n 1 -seed 77 -dur 30 -out "$W/extra" >/dev/null
out=$($LM index -add -out "$W/lib.lmk" "$W/extra" "$W/corpus/song0001.wav"); expect "-add indexes new song" "$out" '\+ song0077'
expect "-add skips known song" "$out" 'song0001 +already indexed'
out=$($LM eval -songs 8 -negatives 3 -dur 30 -trials 4 -only clean 2>/dev/null); expect "eval table renders" "$out" '\| clean \| 100% correct'
expect "eval reports false accepts" "$out" 'False accepts on never-indexed songs: \*\*0 / '

echo "== 9. hostile inputs"
echo "not audio" > "$W/bad.wav"
out=$($LM identify -db "$W/lib.lmk" "$W/bad.wav" 2>&1); expect "garbage WAV -> clear error" "$out" 'not a RIFF/WAVE'
out=$($LM identify -db "$W/missing.lmk" "$W/clean.wav" 2>&1); expect "missing index -> clear error" "$out" 'no such file'
cp "$W/lib.lmk" "$W/c.lmk"; printf 'X' | dd of="$W/c.lmk" bs=1 seek=200 conv=notrunc 2>/dev/null
out=$($LM identify -db "$W/c.lmk" "$W/clean.wav" 2>&1); expect "corrupt index -> checksum error" "$out" 'checksum mismatch'
$LM degrade -in "$W/corpus/song0002.wav" -start 3 -len 0.4 -out "$W/short.wav" >/dev/null
out=$($LM identify -db "$W/lib.lmk" "$W/short.wav" 2>&1 || true); expect "0.4 s clip -> NO MATCH, not a crash" "$out" 'NO MATCH'
python3 - "$W/sil.wav" <<'PY'
import sys,wave
w=wave.open(sys.argv[1],'wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*40000);w.close()
PY
out=$($LM identify -db "$W/lib.lmk" "$W/sil.wav" 2>&1 || true); expect "silence -> explained NO MATCH" "$out" 'no usable landmarks'
out=$($LM identify "$W/clean.wav" -db "$W/lib.lmk" 2>&1); expect "flags may follow positionals" "$out" 'MATCH'
out=$($LM degrade -in "$W/clean.wav" -start 999 -out "$W/z.wav" 2>&1 || true); expect "crop past end -> clear error" "$out" 'crop is empty'
out=$($LM bogus 2>&1 || true); expect "unknown command -> usage" "$out" 'unknown command'

echo
echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
