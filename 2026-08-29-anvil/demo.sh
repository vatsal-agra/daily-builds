#!/usr/bin/env bash
# Anvil end-to-end verification: unit/integration test suite, then a live
# server exercised with real curl, a real raw-socket WebSocket client, and
# the reverse proxy + load test tools -- every required and stretch
# feature, driven through the real CLI/network, not re-imported and
# called in-process.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
CHAT_PID=""
PROXY_PID=""

cleanup() {
  [ -n "$CHAT_PID" ] && kill "$CHAT_PID" >/dev/null 2>&1
  [ -n "$PROXY_PID" ] && kill "$PROXY_PID" >/dev/null 2>&1
  wait >/dev/null 2>&1
}
trap cleanup EXIT

check() {
  local desc="$1"; shift
  if "$@"; then
    echo "  OK   $desc"
    PASS=$((PASS + 1))
  else
    echo "  FAIL $desc"
    FAIL=$((FAIL + 1))
  fi
}

status_is() {
  local expected="$1" url="$2"; shift 2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$@" "$url")
  [ "$code" = "$expected" ]
}

echo "=== Anvil demo.sh ==="

echo
echo "-- 1. Automated test suite (unit + integration + proxy) --"
if python3 -m unittest discover -s tests > /tmp/anvil_demo_tests.log 2>&1; then
  N=$(grep -Eo "Ran [0-9]+ test" /tmp/anvil_demo_tests.log | grep -Eo "[0-9]+")
  echo "  OK   ${N} tests passed"
  PASS=$((PASS + 1))
else
  echo "  FAIL test suite -- see /tmp/anvil_demo_tests.log"
  tail -40 /tmp/anvil_demo_tests.log
  FAIL=$((FAIL + 1))
fi

echo
echo "-- 2. Starting the live chat server --"
python3 app_demo/chat_server.py --port 8123 > /tmp/anvil_demo_chat.log 2>&1 &
CHAT_PID=$!
for i in $(seq 1 30); do
  curl -s -o /dev/null http://127.0.0.1:8123/api/status && break
  sleep 0.2
done

echo
echo "-- 3. HTTP basics (real curl against the real server) --"
check "GET / redirects (302)" status_is 302 http://127.0.0.1:8123/
check "GET /static/index.html (200)" status_is 200 http://127.0.0.1:8123/static/index.html
check "GET /nope.txt (404)" status_is 404 http://127.0.0.1:8123/static/nope.txt
check "route param echo" bash -c '[ "$(curl -s "http://127.0.0.1:8123/api/echo/anvil?x=1")" = "{\"word\": \"anvil\", \"query\": {\"x\": [\"1\"]}}" ]'
check "wrong method on static mount -> 405" status_is 405 http://127.0.0.1:8123/static/index.html -X DELETE

echo
echo "-- 4. Static file Range + conditional GET (curl -r / -H) --"
FULL_LEN=$(curl -s http://127.0.0.1:8123/static/style.css | wc -c)
RANGE_OUT=$(curl -s -r 0-9 http://127.0.0.1:8123/static/style.css)
check "range request returns exactly 10 bytes" bash -c "[ \"${#RANGE_OUT}\" = 10 ]"
check "range request status is 206" status_is 206 http://127.0.0.1:8123/static/style.css -r 0-9
ETAG=$(curl -sI http://127.0.0.1:8123/static/style.css | grep -i '^etag:' | tr -d '\r' | cut -d' ' -f2-)
check "conditional GET with matching ETag -> 304" status_is 304 http://127.0.0.1:8123/static/style.css -H "If-None-Match: ${ETAG}"

echo
echo "-- 5. Concurrency: single event-loop thread serving many clients --"
python3 loadtest.py --port 8123 --path /api/status --workers 30 --requests 10 > /tmp/anvil_demo_load.log 2>&1
check "load test: 300/300 requests succeeded" grep -q "300/300 ok, 0 errors" /tmp/anvil_demo_load.log
tail -5 /tmp/anvil_demo_load.log | sed 's/^/       /'

echo
echo "-- 6. Expect: 100-continue (real deadlock-risk protocol path) --"
python3 - > /tmp/anvil_demo_100.log 2>&1 <<'PYEOF'
import socket, sys, time
s = socket.create_connection(("127.0.0.1", 8123), timeout=5)
body = b"y" * 4000
req = (f"POST /echo HTTP/1.1\r\nHost: h\r\nContent-Length: {len(body)}\r\n"
       "Expect: 100-continue\r\nConnection: close\r\n\r\n").encode()
s.sendall(req)
interim = b""
deadline = time.time() + 3
while time.time() < deadline and b"\r\n\r\n" not in interim:
    interim += s.recv(4096)
assert interim.startswith(b"HTTP/1.1 100 Continue"), f"no 100-continue: {interim!r}"
s.sendall(body)
final = b""
deadline = time.time() + 3
while time.time() < deadline:
    chunk = s.recv(65536)
    if not chunk:
        break
    final += chunk
assert final.endswith(body), "echoed body mismatch"
s.close()
print("ok")
PYEOF
check "server answers 100-continue before body, then echoes it" grep -q "^ok$" /tmp/anvil_demo_100.log

echo
echo "-- 7. WebSocket end-to-end (real RFC 6455 handshake + framing) --"
python3 - > /tmp/anvil_demo_ws.log 2>&1 <<'PYEOF'
import socket, base64, os, sys, json, time
sys.path.insert(0, ".")
from anvil import websocket as ws

def handshake(sock, path):
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:8123\r\n"
           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode()
    sock.sendall(req)
    data = b""
    while b"\r\n\r\n" not in data:
        data += sock.recv(4096)
    head, _, rest = data.partition(b"\r\n\r\n")
    assert b"101" in head, head
    return rest

s = socket.create_connection(("127.0.0.1", 8123), timeout=5)
leftover = handshake(s, "/ws/demo-room")
parser = ws.WebSocketParser(require_mask=False)
msgs = parser.feed(leftover)
while not msgs:
    msgs = parser.feed(s.recv(4096))
welcome = json.loads(msgs[0].payload)
assert welcome["type"] == "welcome" and welcome["room"] == "demo-room", welcome

s.sendall(ws.encode_frame(ws.OP_TEXT, json.dumps({"type": "join", "name": "demo.sh"}).encode(), mask=True))
msgs = []
while not msgs:
    msgs = parser.feed(s.recv(4096))
assert b"joined" in msgs[0].payload

s.sendall(ws.encode_frame(ws.OP_TEXT, json.dumps({"type": "chat", "text": "hello from demo.sh"}).encode(), mask=True))
msgs = []
while not msgs:
    msgs = parser.feed(s.recv(4096))
chat = json.loads(msgs[0].payload)
assert chat["type"] == "chat" and chat["text"] == "hello from demo.sh", chat

s.sendall(ws.encode_frame(ws.OP_PING, b"hi", mask=True))
msgs = []
while not msgs:
    msgs = parser.feed(s.recv(4096))
assert msgs[0].opcode == ws.OP_PONG and msgs[0].payload == b"hi"

s.close()
print("ok")
PYEOF
check "WS handshake, join, chat broadcast, ping/pong all real" grep -q "^ok$" /tmp/anvil_demo_ws.log

kill "$CHAT_PID" >/dev/null 2>&1
wait "$CHAT_PID" 2>/dev/null
CHAT_PID=""

echo
echo "-- 8. Reverse proxy / load balancer (stretch feature) --"
python3 app_demo/run_proxy.py --proxy-port 8124 > /tmp/anvil_demo_proxy.log 2>&1 &
PROXY_PID=$!
for i in $(seq 1 30); do
  curl -s -o /dev/null http://127.0.0.1:8124/whoami && break
  sleep 0.2
done
R1=$(curl -s http://127.0.0.1:8124/whoami)
R2=$(curl -s http://127.0.0.1:8124/whoami)
check "two requests alternate between backends A and B" bash -c "[ '$R1' != '$R2' ]"
check "proxied response is valid JSON with a backend field" bash -c "echo '$R1' | grep -qE '\"backend\": \"[AB]\"'"
kill "$PROXY_PID" >/dev/null 2>&1
wait "$PROXY_PID" 2>/dev/null
PROXY_PID=""

echo
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
