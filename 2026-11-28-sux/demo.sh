#!/usr/bin/env bash
# End-to-end demo + verification. Every sux answer is checked against an independent Unix tool.
# Usage: ./demo.sh            (needs cargo; runs the full test suite first)
set -euo pipefail
cd "$(dirname "$0")"
pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got '$2', want '$3')"; fi; }

echo "== build + test suite =="
cargo build --release --quiet
cargo test --release --quiet 2>&1 | grep -E "^test result" | awk '{p+=$4; f+=$6} END {print "  cargo test: " p " passed, " f " failed"; if (f>0) exit 1}'
S=target/release/sux
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

echo "== corpus (this repo's own Rust source + markdown, repeated for bulk) =="
for i in 1 2 3 4 5 6 7 8; do cat src/*.rs tests/*.rs *.md; done > "$W/corpus.txt"
echo "  $(wc -c < "$W/corpus.txt") bytes, $(wc -l < "$W/corpus.txt") lines"

echo "== FM-index: build, persist, query (feature 4: FM-index over SA-IS + wavelet + EF line map) =="
$S index "$W/corpus.txt" -o "$W/plain.sux" | sed 's/^/  /'
$S index "$W/corpus.txt" -o "$W/rrr.sux" -z --sample 64 | sed 's/^/  /'
for p in "WaveletMatrix" "fn rank1" "EliasFano::new" "unsafe" "Kuhn" "select_in_word"; do
  want=$(grep -nF -- "$p" "$W/corpus.txt" | md5sum || true)
  got=$($S grep "$W/plain.sux" "$p" 2>/dev/null | md5sum || true)
  gotz=$($S grep "$W/rrr.sux" "$p" 2>/dev/null | md5sum || true)
  check "grep '$p' == grep -nF (plain)" "$got" "$want"
  check "grep '$p' == grep -nF (RRR)" "$gotz" "$want"
done
want=$(grep -cF -- "fn " "$W/corpus.txt"); got=$($S grep "$W/plain.sux" "fn " -c)
check "grep -c 'fn ' (matching lines)" "$got" "$want"
want=$(grep -oF -- "pub fn" "$W/corpus.txt" | wc -l); got=$($S count "$W/plain.sux" "pub fn")
check "count 'pub fn' == grep -o | wc" "$got" "$want"
want=$(grep -obUaF -- "WaveletMatrix" "$W/corpus.txt" | cut -d: -f1 | head -50 | md5sum)
got=$($S locate "$W/plain.sux" "WaveletMatrix" | head -50 | md5sum)
check "locate offsets == grep -ob" "$got" "$want"
want=$(dd if="$W/corpus.txt" bs=1 skip=1234 count=300 2>/dev/null | md5sum)
got=$($S extract "$W/rrr.sux" 1234 1534 | head -c 300 | md5sum)
check "extract bytes 1234..1534 == dd" "$got" "$want"
check "line 17 == sed -n 17p" "$($S line "$W/plain.sux" 17)" "$(sed -n 17p "$W/corpus.txt")"
last=$(wc -l < "$W/corpus.txt")
check "last line == tail -1" "$($S line "$W/rrr.sux" "$last")" "$(tail -n 1 "$W/corpus.txt")"
full=$($S extract "$W/rrr.sux" 0 "$(wc -c < "$W/corpus.txt")" | head -c "$(wc -c < "$W/corpus.txt")" | md5sum)
check "extract whole text from RRR index reproduces the file" "$full" "$(md5sum < "$W/corpus.txt")"
p_sz=$(stat -c %s "$W/plain.sux"); z_sz=$(stat -c %s "$W/rrr.sux"); t_sz=$(stat -c %s "$W/corpus.txt")
echo "  sizes: text=$t_sz plain-index=$p_sz rrr-index=$z_sz"
[ "$z_sz" -lt "$p_sz" ] && ok "RRR index smaller than plain index" || bad "RRR index not smaller"
[ "$z_sz" -lt "$t_sz" ] && ok "RRR index smaller than the text itself" || bad "RRR index not smaller than text"

echo "== corruption is detected, never trusted =="
cp "$W/plain.sux" "$W/bad.sux"; printf '\xff' | dd of="$W/bad.sux" bs=1 seek=5000 conv=notrunc 2>/dev/null
if $S count "$W/bad.sux" fn 2>"$W/err"; then bad "corrupt index accepted"; else grep -q checksum "$W/err" && ok "bit-flip rejected: $(cat "$W/err" | sed 's/.*scratch.*sux: //;s/^sux: //' | cut -c1-60)" || bad "wrong error"; fi
head -c 1000 "$W/plain.sux" > "$W/trunc.sux"
$S info "$W/trunc.sux" 2>/dev/null && bad "truncated accepted" || ok "truncated index rejected"

echo "== LOUDS trie (feature 5) =="
cat > "$W/gen.py" <<'PY'
import random
random.seed(5)
stems=["".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(random.randint(3,7))) for _ in range(300)]
for s in stems:
    for e in ["","s","ed","ing","er","ers","ly","ness"]: print(s+e)
PY
python3 "$W/gen.py" > "$W/words.txt"
$S trie build "$W/words.txt" -o "$W/w.trie" | sed 's/^/  /'
check "distinct word count" "$($S trie info "$W/w.trie" | awk '/words/ {print $3}')" "$(sort -u "$W/words.txt" | wc -l)"
pre=$(sort -u "$W/words.txt" | sed -n 100p | cut -c1-3)
check "complete '$pre' == sort|grep ^" "$($S trie complete "$W/w.trie" "$pre" -n 100000 | md5sum)" "$(sort -u "$W/words.txt" | grep "^$pre" | LC_ALL=C sort | md5sum)"
w=$(sort -u "$W/words.txt" | sed -n 321p)
id=$($S trie lookup "$W/w.trie" "$w"); check "key(lookup(w)) == w" "$($S trie key "$W/w.trie" "$id")" "$w"
$S trie lookup "$W/w.trie" "qqqqqqqqqqq" >/dev/null && bad "absent word found" || ok "absent word rejected (exit 1)"

echo "== Elias-Fano / wavelet / bitvector / RRR (features 1-3, 6): measured =="
$S bench --quick | sed 's/^/  /'
ok "bench ran (numbers above are measured, not hard-coded)"

echo
echo "demo: $pass checks passed, $fail failed"
[ "$fail" -eq 0 ]
