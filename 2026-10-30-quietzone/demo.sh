#!/usr/bin/env bash
# End-to-end demo with assertions: exercises every feature through the CLI.
set -euo pipefail
cd "$(dirname "$0")"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
go build -o "$W/qz" ./cmd/qz
qz="$W/qz"; pass=0
ok() { pass=$((pass+1)); echo "  ok  $*"; }
eq() { [ "$1" = "$2" ] || { echo "FAIL: $3: got [$1] want [$2]"; exit 1; }; ok "$3"; }
has() { grep -q -- "$1" <<<"$2" || { echo "FAIL: $3: missing [$1] in [$2]"; exit 1; }; ok "$3"; }

echo "1. Reed–Solomon workbench"
out=$($qz rs demo -ecc 10 -errors 3 -erasures 4)
has "identical to sent: true" "$out" "RS repairs 3 errors + 4 erasures (cost 10/10)"
out=$($qz rs demo -ecc 10 -errors 6)
has "FAILED" "$out" "RS refuses 6 errors with 10 parity bytes"
par=$($qz rs encode -ecc 10 "10 20 0c 56 61 80 ec 11 ec 11 ec 11 ec 11 ec 11")
eq "$par" "a524d4c1ed36c7872c55" "ISO 18004 Annex I parity bytes"

echo "2. Encode"
T="https://example.com/quietzone?demo=1&n=0123456789"
$qz encode -ecc Q -o "$W/a.png" "$T"; $qz encode -o "$W/a.svg" "$T"
[ -s "$W/a.png" ] && head -c 4 "$W/a.svg" | grep -q '<svg' && ok "PNG and SVG written"
has "version 3\|version 4\|version 5" "$($qz encode -info -ecc Q -o "$W/b.png" "$T" 2>&1)" "encode -info reports a version"
eq "$($qz encode -v 40 -ecc L -o "$W/c.png" x 2>&1; echo rc=$?)" "rc=0" "forced version 40"
err=$($qz encode -v 1 -ecc H "$(printf 'x%.0s' {1..50})" 2>&1 || true)
has "too long" "$err" "overflow is a clean error"

echo "3. Decode / scan"
eq "$($qz decode "$W/a.png")" "$T" "decode round trip"
has "version" "$($qz scan "$W/a.png")" "scan prints statistics"
$qz encode -invert -o "$W/inv.txt" "text art" ; eq "$($qz decode -text "$W/inv.txt")" "text art" "inverted terminal art decodes"
printf 'a\0b\377' | $qz encode -o "$W/bin.png" - ; eq "$($qz decode -raw "$W/bin.png" | od -An -tx1 | tr -d ' \n')" "610062ff" "binary payload is byte-exact"

echo "4. Camera distortion (scanner)"
$qz distort -roll 37 -tiltx 28 -tilty -18 -blur 1.3 -noise 14 -salt 0.005 -light 0.4 -jpeg 40 -seed 3 "$W/a.png" "$W/d.png"
eq "$($qz decode "$W/d.png")" "$T" "rotated+tilted+blurred+noisy+JPEG"
$qz distort -mirror -roll 200 "$W/a.png" "$W/m.png"; eq "$($qz decode "$W/m.png")" "$T" "mirrored upside-down capture"
has "mirrored capture fixed" "$($qz scan "$W/m.png")" "scan reports the mirror fix"
if $qz decode "$W/bin.png" >/dev/null 2>&1 && ! $qz decode /dev/null >/dev/null 2>&1; then ok "garbage input rejected"; fi

echo "5. Damage lab"
out=$($qz damage -ecc H -flips 25 -seed 2 "$T"); has "decode (errors only): *OK" "$out" "25 random flips survive at H"
out=$($qz damage -ecc L -flips 200 -seed 2 "$T"); has "FAILED" "$out" "200 flips destroy an L symbol"
out=$($qz damage -ecc H -logo 0.2 "https://example.com/a/long/enough/payload/for/logo/test"); has "logo as erasures): *OK" "$out" "logo blanked and recovered via erasures"
out=$($qz damage -sweep -trials 8 "https://example.com/resilience?x=1"); has "median flips" "$out" "resilience sweep table"

echo "6. Anatomy"
out=$($qz explain -map -ecc Q "$T"); has "chosen" "$out" "explain shows the chosen mask"; has "Reed–Solomon blocks" "$out" "explain lists RS blocks"
$qz html -ecc Q -o "$W/x.html" "$T"; has "anatomy explorer" "$(cat "$W/x.html")" "explorer HTML generated"

echo "7. Payloads and structured append"
$qz payload wifi -ssid 'Cafe;Guest' -pass 's3:cret' | $qz encode -o "$W/w.png" -
eq "$($qz decode "$W/w.png")" 'WIFI:T:WPA;S:Cafe\;Guest;P:s3\:cret;;' "WIFI payload with escapes"
$qz payload vcard -name "Ada Lovelace" -email ada@example.org | grep -q BEGIN:VCARD && ok "vCard payload"
$qz payload mailto -to a@b.co -subject "hi there" | grep -q 'subject=hi%20there' && ok "mailto payload"
LONG=$(printf 'structured append payload %02d. ' $(seq 1 12))
$qz encode -parts 3 -ecc L -o "$W/sa.png" "$LONG" >/dev/null
[ -s "$W/sa-1.png" ] && [ -s "$W/sa-2.png" ] && [ -s "$W/sa-3.png" ] && ok "three linked symbols written"
has "structured-append" "$($qz scan "$W/sa-2.png")" "a part carries its sequence header"

echo "8. Benchmark (subset)"
out=$($qz bench -n 6 -only "rotation any angle" -strict); has "100.0%" "$out" "bench: rotation scenario"
echo "demo: $pass assertions passed"
