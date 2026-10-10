#!/usr/bin/env bash
# Runnable end-to-end demo that exercises every Namewright feature through the CLI and
# asserts on real output. Exit status is non-zero if any assertion fails.
#   ./demo.sh            full demo (builds, unit tests, CLI scenarios, fuzz smoke, dnspython cross-check if available)
#   SKIP_GO_TESTS=1 ./demo.sh   skip `go test` (it takes ~10 s)
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d); PIDS=()
pass=0; fail=0
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null; done; rm -rf "$WORK"; }
trap cleanup EXIT

say()    { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()     { pass=$((pass+1)); printf '  \033[32mok\033[0m   %s\n' "$*"; }
bad()    { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
expect() { # expect <description> <haystack> <needle>
  if grep -qF -- "$3" <<<"$2"; then ok "$1"; else bad "$1 (missing: $3)"; printf '%s\n' "$2" | head -12 | sed 's/^/        /'; fi
}
absent() { if grep -qF -- "$3" <<<"$2"; then bad "$1 (unexpected: $3)"; else ok "$1"; fi; }

say "build"
go build -o "$WORK/nw" ./cmd/namewright && ok "go build" || { bad "go build"; exit 1; }
NW="$WORK/nw"
go vet ./... && ok "go vet" || bad "go vet"

if [ -z "${SKIP_GO_TESTS:-}" ]; then
  say "unit + integration tests (race detector)"
  out=$(go test -race -count=1 ./... 2>&1); echo "$out" | grep -E '^(ok|FAIL|---)' | sed 's/^/  /'
  grep -q '^FAIL' <<<"$out" && bad "go test -race" || ok "go test -race"
fi

start_server() { # start_server <logfile> args... ; sets ADDR
  local log=$1; shift
  "$NW" serve -listen 127.0.0.1:0 "$@" >"$log" 2>&1 & PIDS+=($!)
  for _ in $(seq 50); do ADDR=$(sed -n 's/^namewright serving on \([0-9.:]*\) .*/\1/p' "$log" | head -1); [ -n "$ADDR" ] && return 0; sleep 0.1; done
  echo "server failed to start:"; cat "$log"; return 1
}

say "feature 1 — wire codec (hand-built packet + hostile input)"
q='beef0100000100000000000003777777076578616d706c6503636f6d0000010001'
out=$(echo "$q" | "$NW" decode)
expect "decodes a hand-assembled query"          "$out" "www.example.com.	IN	A"
expect "re-encodes byte-for-byte"                "$out" "wire: $q"
out=$(echo 'abcd01000001000000000000c00c00010001' | "$NW" decode 2>&1 || true)
expect "compression-pointer loop is rejected"    "$out" "bad compression pointer"

say "feature 2 — zone-file parser and validation"
out=$("$NW" check miniverse/internet/example.com.zone)
expect "checks the sample zone"                  "$out" "zone example.com. OK"
printf '$ORIGIN bad.test.\n$TTL 60\n@ SOA n h 1 1 1 1 1\nw CNAME x\nw A 1.2.3.4\n' >"$WORK/bad.zone"
out=$("$NW" check "$WORK/bad.zone" 2>&1 || true)
expect "rejects CNAME + other data"              "$out" "has a CNAME and also A data"
printf '$ORIGIN e.test.\n$TTL 60\n@ SOA n h 1 1 1 1 1\n\nx A 999.1.1.1\n' >"$WORK/e.zone"
out=$("$NW" check "$WORK/e.zone" 2>&1 || true)
expect "syntax errors carry file:line"           "$out" "e.zone:5:"

say "feature 3 — authoritative server (UDP+TCP, EDNS, truncation, AXFR)"
start_server "$WORK/auth.log" -zone example.com.=miniverse/internet/example.com.zone -zone sub.example.com.=miniverse/internet/sub.example.com.zone -axfr-allow 127.0.0.0/8
out=$("$NW" dig @"$ADDR" www2.example.com A +norec); expect "CNAME chain answered with AA"  "$out" "flags: qr aa"; expect "chain followed in-zone" "$out" "web.example.com.	600	IN	A	192.0.2.80"
out=$("$NW" dig @"$ADDR" nope.example.com A +norec); expect "NXDOMAIN carries the SOA"   "$out" "status: NXDOMAIN"; expect "negative TTL = min(SOA ttl, minimum)" "$out" "example.com.	300	IN	SOA"
out=$("$NW" dig @"$ADDR" anything.dev.example.com A +norec); expect "wildcard synthesis"  "$out" "anything.dev.example.com.	3600	IN	A	192.0.2.99"
out=$("$NW" dig @"$ADDR" b.c.example.com A +norec); expect "empty non-terminal is NODATA" "$out" "status: NOERROR"; expect "…with ANSWER: 0" "$out" "ANSWER: 0"
out=$("$NW" dig @"$ADDR" big.example.com TXT +norec); expect "oversize answer retried over TCP" "$out" "ANSWER: 10"
out=$("$NW" dig @"$ADDR" www.google.com A +norec); expect "out-of-zone is REFUSED" "$out" "status: REFUSED"
out=$("$NW" axfr @"$ADDR" example.com.); expect "AXFR streams the whole zone" "$out" "records transferred"; expect "…bracketed by SOA" "$(head -1 <<<"$out")" "SOA"
out=$("$NW" dig @"$ADDR" example.com. MX +short); expect "+short prints rdata" "$out" "10 mail.example.com."
out=$("$NW" dig @"$ADDR" version.bind TXT CH 2>&1 || true)

say "feature 4 — iterative caching resolver (root → TLD → authoritative)"
out=$("$NW" resolve blog.example.com A)
expect "walks root, com., example.com."          "$out" "referral to example.com."
expect "follows a CNAME into another zone"       "$out" "follow CNAME -> blog.glueless.com."
expect "resolves a glueless nameserver"          "$out" "glueless NS ns.dnshost.net.: resolving address"
expect "final answer"                            "$out" "blog.glueless.com.	3600	IN	A	192.0.2.201"
out=$("$NW" resolve -quiet nothere.example.com A 2>&1 || true); expect "NXDOMAIN end-to-end" "$out" "status: NXDOMAIN"
("$NW" testnet -listen 127.0.0.1:0 >"$WORK/tn.log" 2>&1 & echo $! >"$WORK/tn.pid"); PIDS+=("$(cat "$WORK/tn.pid")")
for _ in $(seq 50); do FRONT=$(sed -n 's/.*listening on \([0-9.:]*\) .*/\1/p' "$WORK/tn.log"); [ -n "$FRONT" ] && break; sleep 0.1; done
out=$("$NW" dig @"$FRONT" www.example.com A); expect "recursive front end answers real clients (ra set)" "$out" "flags: qr rd ra"; expect "…with the full chain" "$out" "web.example.com."
out=$("$NW" dig @"$FRONT" nope.example.com A); expect "recursive NXDOMAIN"  "$out" "status: NXDOMAIN"
grep -q 'nope.example.com' "$WORK/tn.log" && ok "front end logged the query"

say "stretch — DNSSEC: keygen, sign, verify, validating resolver"
"$NW" keygen -zone demo.test. -ksk -out "$WORK" >"$WORK/ksk.out"; "$NW" keygen -zone demo.test. -alg ecdsap256 -out "$WORK" >/dev/null
expect "keygen prints the DS for the parent" "$(cat "$WORK/ksk.out")" "IN	DS"
KSK=$(head -1 "$WORK/ksk.out"); ZSK=$(ls "$WORK"/Kdemo.test.+013+*.key | sed 's/\.key$//')
printf '$ORIGIN demo.test.\n$TTL 300\n@ SOA ns h 1 3600 600 86400 120\n@ NS ns\nns A 192.0.2.1\nwww A 192.0.2.2\n' >"$WORK/demo.zone"
"$NW" sign -origin demo.test. -ksk "$KSK" -zsk "$ZSK" -o "$WORK/demo.signed" "$WORK/demo.zone" 2>/dev/null && ok "sign"
expect "signed zone has RRSIG/NSEC/DNSKEY" "$(cat "$WORK/demo.signed")" "NSEC"
out=$("$NW" verify -origin demo.test. "$WORK/demo.signed"); expect "verify accepts the fresh zone" "$out" "verifies"
sed 's/192.0.2.2/6.6.6.6/' "$WORK/demo.signed" >"$WORK/forged"
out=$("$NW" verify -origin demo.test. "$WORK/forged" 2>&1 || true); expect "verify catches a forged record" "$out" "FAIL"
out=$("$NW" resolve -signed -quiet web.example.com A); expect "secure chain of trust validated" "$out" "dnssec: secure"
out=$("$NW" resolve -signed -quiet nope.example.com A 2>&1 || true); expect "signed NXDOMAIN validated via NSEC" "$out" "dnssec: secure"
out=$("$NW" resolve -signed -quiet host.sub.example.com A); expect "unsigned child is insecure, not bogus" "$out" "dnssec: insecure"
out=$("$NW" resolve -signed -quiet nosuch.nosuchtld A 2>&1 || true); expect "signed root proves a TLD does not exist" "$out" "status: NXDOMAIN"

say "stretch — secondary server follows its primary"
sed 's/2026101001/2026101001/' miniverse/internet/example.com.zone >"$WORK/prim.zone"
start_server "$WORK/prim.log" -zone example.com.="$WORK/prim.zone" -axfr-allow 127.0.0.0/8; PRIM=$ADDR
start_server "$WORK/sec.log" -secondary example.com.="$PRIM"; SEC=$ADDR
sleep 1; out=$("$NW" dig @"$SEC" web.example.com A +norec +short); expect "replica serves the transferred zone" "$out" "192.0.2.80"
expect "replica logged the transfer" "$(cat "$WORK/sec.log")" "zone example.com. loaded from"

say "stretch — rate limiting and response policy"
printf 'ads.example.test. NXDOMAIN\n*.tracker.test. NXDOMAIN\nportal.test. A 10.9.9.9\n' >"$WORK/policy"
start_server "$WORK/pol.log" -zone example.com.=miniverse/internet/example.com.zone -policy "$WORK/policy" -rate 1 -burst 3 -q
ans=$(python3 -I - "$ADDR" <<'PY'
import socket, sys
h, p = sys.argv[1].rsplit(":", 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(0.4)
def q(i): return bytes([0, i, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 3]) + b"web" + bytes([7]) + b"example" + bytes([3]) + b"com" + bytes([0, 0, 1, 0, 1])
for i in range(1, 9): s.sendto(q(i), (h, int(p)))
n = 0
try:
    while True:
        s.recv(2048); n += 1
except socket.timeout:
    pass
print(n)
PY
)
[ "$ans" -ge 3 ] && [ "$ans" -le 4 ] && ok "token bucket: burst of 8 queries -> $ans answered (burst 3, ~1/s refill)" || bad "rate limit ($ans/8 answered)"
out=$("$NW" dig @"$ADDR" ads.example.test A +norec 2>&1 || true)
sleep 4; out=$("$NW" dig @"$ADDR" ads.example.test A +norec 2>&1 || true); expect "policy blocks a listed name" "$out" "status: NXDOMAIN"
out=$("$NW" dig @"$ADDR" deep.sub.tracker.test A +norec 2>&1 || true); expect "policy wildcard blocks subdomains" "$out" "status: NXDOMAIN"
out=$("$NW" dig @"$ADDR" portal.test A +norec +short 2>&1 || true); expect "policy redirect answers with the fixed address" "$out" "10.9.9.9"

say "stretch — fuzzing smoke test (5 s per target)"
go test ./dns -run xxx -fuzz FuzzUnpack -fuzztime 5s >/dev/null 2>&1 && ok "FuzzUnpack" || bad "FuzzUnpack"
go test ./dns -run xxx -fuzz FuzzZoneFile -fuzztime 5s >/dev/null 2>&1 && ok "FuzzZoneFile" || bad "FuzzZoneFile"

say "independent oracle — dnspython cross-check"
PY=${PYTHON:-python3}
if "$PY" -c 'import dns.dnssec, cryptography' 2>/dev/null; then
  NAMEWRIGHT="$NW" "$PY" -I tests/crosscheck.py | tail -4 | sed 's/^/  /'
  [ "${PIPESTATUS[0]}" = 0 ] && ok "dnspython cross-check" || bad "dnspython cross-check"
else
  echo "  (skipped: pip install dnspython cryptography, or set PYTHON=/path/to/venv/bin/python)"
fi

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" = 0 ]
