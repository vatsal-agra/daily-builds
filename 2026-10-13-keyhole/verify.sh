#!/usr/bin/env bash
# End-to-end verification of Keyhole. Builds the CLI, runs the unit/integration/interop suite under
# the race detector, smoke-fuzzes every parser, then drives the real binary against independent
# TLS stacks (openssl, curl, Python's ssl, Go's crypto/tls via the test suite) and asserts on output.
#   ./verify.sh                  everything
#   SKIP_GO_TESTS=1 ./verify.sh  skip 'go test' (CLI scenarios only)
#   FUZZTIME=30s ./verify.sh     longer fuzzing (default 4s per fuzzer)
set -u
cd "$(dirname "$0")"
WORK=$(mktemp -d); PIDS=()
pass=0; fail=0
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null; done; rm -rf "$WORK"; }
trap cleanup EXIT

say()    { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()     { pass=$((pass+1)); printf '  \033[32mok\033[0m   %s\n' "$*"; }
bad()    { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
expect() { if grep -qF -- "$3" <<<"$2"; then ok "$1"; else bad "$1 (missing: $3)"; printf '%s\n' "$2" | head -15 | sed 's/^/        /'; fi; }
absent() { if grep -qF -- "$3" <<<"$2"; then bad "$1 (unexpected: $3)"; else ok "$1"; fi; }
port()   { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])'; }
waitport() { for _ in $(seq 100); do (exec 3<>/dev/tcp/127.0.0.1/$1) 2>/dev/null && return 0; sleep 0.05; done; return 1; }

say "build"
go build -o "$WORK/keyhole" ./cmd/keyhole && ok "go build" || { bad "go build"; exit 1; }
go vet ./... && ok "go vet" || bad "go vet"
[ -z "$(gofmt -l .)" ] && ok "gofmt clean" || bad "gofmt: $(gofmt -l .)"
K="$WORK/keyhole"

if [ -z "${SKIP_GO_TESTS:-}" ]; then
  say "unit + integration + interop tests (race detector)"
  out=$(go test -race -count=1 ./... 2>&1); echo "$out" | grep -E '^(ok|FAIL|---|panic)' | sed 's/^/  /'
  grep -qE '^(FAIL|panic)' <<<"$out" && { bad "go test -race"; echo "$out" | tail -30; } || ok "go test -race"
  say "native fuzzers (${FUZZTIME:-4s} each)"
  for fz in FuzzHandshakeParsers FuzzClientHelloRoundTrip FuzzRecordOpen FuzzServerStream FuzzClientStream; do
    o=$(go test ./tls13 -run XXX -fuzz "^$fz\$" -fuzztime "${FUZZTIME:-4s}" -fuzzminimizetime 0s 2>&1 | tail -2)
    grep -q PASS <<<"$o" && ok "$fz" || { bad "$fz"; echo "$o"; }
  done
fi

say "certgen + keyhole server/client (CLI)"
"$K" certgen -dir "$WORK/pki" >/dev/null && ok "certgen" || bad "certgen"
P=$(port)
"$K" server -listen 127.0.0.1:$P -cert "$WORK/pki/server.pem" -key "$WORK/pki/server.key" -keylog "$WORK/srv.keys" -alpn http/1.1 >"$WORK/srv.log" 2>&1 & PIDS+=($!)
waitport $P || bad "server did not start"
out=$("$K" client -connect 127.0.0.1:$P -servername localhost -ca "$WORK/pki/ca.pem" -alpn http/1.1 -trace -resume 1 -key-update 2>&1)
expect "client handshake succeeds"            "$out" "handshake complete"
expect "negotiated TLS_AES_128_GCM_SHA256"   "$out" "cipher suite    TLS_AES_128_GCM_SHA256"
expect "ALPN negotiated"                      "$out" "ALPN            http/1.1"
expect "full handshake first"                 "$out" "session         full handshake, ecdsa_secp256r1_sha256"
expect "second connection resumes via PSK"    "$out" "resumed with PSK (no certificate exchanged)"
expect "trace shows KeyUpdate"                "$out" "KeyUpdate"
expect "server answered over TLS"             "$out" "keyhole says hello over TLS 1.3"

say "client rejects bad certificates (CLI)"
out=$("$K" client -connect 127.0.0.1:$P -servername localhost 2>&1); rc=$?
[ $rc -ne 0 ] && ok "unknown CA → non-zero exit" || bad "unknown CA accepted"
expect "unknown_ca alert named" "$out" "unknown_ca"
out=$("$K" client -connect 127.0.0.1:$P -servername wrong.example -ca "$WORK/pki/ca.pem" 2>&1); rc=$?
[ $rc -ne 0 ] && ok "hostname mismatch → non-zero exit" || bad "hostname mismatch accepted"
expect "bad_certificate alert named" "$out" "bad_certificate"
out=$("$K" client -connect 127.0.0.1:$P -servername wrong.example -insecure 2>&1)
expect "-insecure skips verification" "$out" "handshake complete"

say "interop: OpenSSL s_client → keyhole server"
out=$(printf 'hello from openssl\n' | timeout 8 openssl s_client -connect 127.0.0.1:$P -tls1_3 -CAfile "$WORK/pki/ca.pem" -servername localhost -verify_return_error -verify_hostname localhost -alpn http/1.1 2>&1 </dev/stdin)
expect "openssl: TLSv1.3"        "$out" "New, TLSv1.3, Cipher is"
expect "openssl: verify ok"      "$out" "Verification: OK"
expect "openssl: ALPN"           "$out" "ALPN protocol: http/1.1"

say "interop: curl → keyhole server"
out=$(curl -sS --max-time 8 --tlsv1.3 --cacert "$WORK/pki/ca.pem" https://localhost:$P/hello 2>&1)
expect "curl got the page"       "$out" "keyhole says hello over TLS 1.3"
expect "curl request line seen"  "$out" "GET /hello HTTP/1.1"
out=$(curl -sS --max-time 8 --tlsv1.3 --cacert "$WORK/pki/ca.pem" https://127.0.0.1:$P/ip 2>&1)
expect "curl by IP (IP SAN)"     "$out" "GET /ip HTTP/1.1"

say "interop: Python ssl (OpenSSL) client → keyhole server"
out=$(python3 - "$P" "$WORK/pki/ca.pem" <<'PY' 2>&1
import ssl, socket, sys
port, ca = int(sys.argv[1]), sys.argv[2]
ctx = ssl.create_default_context(cafile=ca); ctx.minimum_version = ssl.TLSVersion.TLSv1_3
with socket.create_connection(("127.0.0.1", port)) as s, ctx.wrap_socket(s, server_hostname="localhost") as t:
    print("py-version", t.version(), t.cipher()[0])
    t.sendall(b"GET /py HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    data = b""
    while True:
        d = t.recv(4096)
        if not d: break
        data += d
    print("py-got", b"GET /py HTTP/1.1" in data)
PY
)
expect "python negotiated TLS 1.3"  "$out" "py-version TLSv1.3"
expect "python got keyhole's reply" "$out" "py-got True"

say "interop: keyhole client → openssl s_server / Python ssl server"
P2=$(port)
openssl s_server -accept $P2 -cert "$WORK/pki/server.pem" -key "$WORK/pki/server.key" -tls1_3 -www >/dev/null 2>&1 & PIDS+=($!)
waitport $P2 || bad "openssl s_server did not start"
out=$("$K" get --ca "$WORK/pki/ca.pem" https://localhost:$P2/ 2>&1)
expect "keyhole get ← openssl s_server" "$out" "New, TLSv1.3, Cipher is"
P3=$(port)
python3 - "$P3" "$WORK/pki/server.pem" "$WORK/pki/server.key" >"$WORK/pysrv.log" 2>&1 <<'PY' & PIDS+=($!)
import ssl, socket, sys
port, cert, key = int(sys.argv[1]), sys.argv[2], sys.argv[3]
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.minimum_version = ssl.TLSVersion.TLSv1_3; ctx.load_cert_chain(cert, key)
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", port)); srv.listen(5)
while True:
    c, _ = srv.accept()
    try:
        t = ctx.wrap_socket(c, server_side=True)
        req = t.recv(4096)
        body = b"python-server saw: " + req.split(b"\r\n")[0]
        t.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        t.close()
    except Exception as e:
        print("err", e, flush=True)
PY
waitport $P3 || bad "python server did not start"
out=$("$K" get --ca "$WORK/pki/ca.pem" https://localhost:$P3/from-keyhole 2>&1)
expect "keyhole get ← python ssl server" "$out" "python-server saw: GET /from-keyhole HTTP/1.1"

say "mutual TLS (CLI)"
P4=$(port)
"$K" server -listen 127.0.0.1:$P4 -cert "$WORK/pki/server.pem" -key "$WORK/pki/server.key" -client-ca "$WORK/pki/ca.pem" -require-client-cert >"$WORK/mtls.log" 2>&1 & PIDS+=($!)
waitport $P4 || bad "mTLS server did not start"
out=$("$K" client -connect 127.0.0.1:$P4 -servername localhost -ca "$WORK/pki/ca.pem" 2>&1); rc=$?
[ $rc -ne 0 ] && ok "client without certificate refused" || bad "anonymous client accepted"
expect "certificate_required alert" "$out" "certificate_required"
out=$("$K" client -connect 127.0.0.1:$P4 -servername localhost -ca "$WORK/pki/ca.pem" -cert "$WORK/pki/client.pem" -key "$WORK/pki/client.key" 2>&1)
expect "client with certificate accepted" "$out" "client cert     CN=keyhole client"
out=$(curl -sS --max-time 8 --tlsv1.3 --cacert "$WORK/pki/ca.pem" --cert "$WORK/pki/client.pem" --key "$WORK/pki/client.key" https://localhost:$P4/ 2>&1)
expect "curl with client cert accepted" "$out" "client cert     CN=keyhole client"

say "HelloRetryRequest and cipher selection (CLI)"
P5=$(port)
"$K" server -listen 127.0.0.1:$P5 -cert "$WORK/pki/server.pem" -key "$WORK/pki/server.key" -groups p256 -suites CHACHA20_POLY1305_SHA256 >/dev/null 2>&1 & PIDS+=($!)
waitport $P5 || bad "HRR server did not start"
out=$("$K" client -connect 127.0.0.1:$P5 -servername localhost -ca "$WORK/pki/ca.pem" 2>&1)
expect "HRR performed"                 "$out" "key exchange    secp256r1  (after HelloRetryRequest)"
expect "ChaCha20-Poly1305 negotiated"  "$out" "TLS_CHACHA20_POLY1305_SHA256"
out=$(openssl s_client -connect 127.0.0.1:$P5 -tls1_3 -CAfile "$WORK/pki/ca.pem" -servername localhost </dev/null 2>&1)
expect "openssl also lands on ChaCha20 via HRR" "$out" "TLS_CHACHA20_POLY1305_SHA256"

say "keyhole inspect: decrypt a real session from a key log"
PI=$(port)
"$K" inspect -listen 127.0.0.1:$PI -upstream 127.0.0.1:$P -keylog "$WORK/cli.keys" -data 40 -html "$WORK/timeline.html" >"$WORK/inspect.log" 2>&1 & IPID=$!; PIDS+=($IPID)
waitport $PI || bad "inspector did not start"
"$K" client -connect 127.0.0.1:$PI -servername localhost -ca "$WORK/pki/ca.pem" -keylog "$WORK/cli.keys" -path /secret-path >/dev/null 2>&1
sleep 0.6; kill -INT $IPID; wait $IPID 2>/dev/null
out=$(cat "$WORK/inspect.log")
expect "inspector sees ClientHello"               "$out" "ClientHello"
expect "inspector decrypts Certificate"          "$out" "1 certificate(s) leaf=CN=keyhole server"
expect "inspector decrypts the HTTP request"     "$out" "GET /secret-path HTTP/1.1"
expect "inspector decrypts the HTTP response"    "$out" "HTTP/1.1 200 OK"
[ -s "$WORK/timeline.html" ] && grep -q "secret-path" "$WORK/timeline.html" && ok "HTML timeline written" || bad "HTML timeline missing/empty"

say "summary"
printf '  %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
