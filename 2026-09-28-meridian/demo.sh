#!/usr/bin/env bash
# End-to-end demo/verification script for Meridian: exercises every
# feature (required + stretch) against a real multi-process cluster and
# prints a pass/fail tally. Run from this directory: ./demo.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
STATE=".meridian/demo-cluster.json"
PY=python3

pass() { PASS=$((PASS+1)); echo "  [PASS] $1"; }
fail() { FAIL=$((FAIL+1)); echo "  [FAIL] $1"; }

cleanup() {
  $PY -m meridian.cli --state "$STATE" cluster-stop >/dev/null 2>&1 || true
  rm -f trace.json
}
trap cleanup EXIT

echo "== Meridian end-to-end demo =============================="
echo
echo "-- 0. unit + integration test suite (26 tests: hashing math,"
echo "      the Chord paper's own worked 3-bit example, dead-node"
echo "      fallback regressions, and a real multi-process cluster)"
if $PY -m unittest discover -s tests > /tmp/meridian_demo_tests.log 2>&1; then
  pass "full test suite (see /tmp/meridian_demo_tests.log for detail)"
else
  fail "test suite failed -- see /tmp/meridian_demo_tests.log"
  tail -n 40 /tmp/meridian_demo_tests.log
fi
echo

echo "-- 1. required: real multi-process cluster starts and converges"
rm -rf .meridian trace.json
if $PY -m meridian.cli --state "$STATE" cluster-start 15 --base-port 21000 --fast --join-pause 0.02 > /tmp/meridian_demo_start.log 2>&1; then
  pass "cluster-start spawned 15 real node processes"
else
  fail "cluster-start failed -- see /tmp/meridian_demo_start.log"
  cat /tmp/meridian_demo_start.log
fi
sleep 2

RING_CHECK=$($PY - "$STATE" <<'PYEOF'
import json, sys
from meridian import client, hashing
from meridian.node import NodeRef, RPCError
state = json.load(open(sys.argv[1]))
m = state["m_bits"]
refs = [NodeRef(id=hashing.node_id_for_addr(e["host"], e["port"], m), host=e["host"], port=e["port"]) for e in state["nodes"]]
ids_sorted = sorted(r.id for r in refs)
ok = True
for r in refs:
    try:
        snap = client.call(r, "snapshot", {})
    except RPCError:
        ok = False
        break
    idx = ids_sorted.index(r.id)
    if snap["successor_list"][0]["id"] != ids_sorted[(idx+1) % len(ids_sorted)]:
        ok = False
    if (snap["predecessor"]["id"] if snap["predecessor"] else None) != ids_sorted[idx-1]:
        ok = False
print("OK" if ok else "BROKEN")
PYEOF
)
if [ "$RING_CHECK" = "OK" ]; then
  pass "ring converged to the exact sorted successor/predecessor cycle (consistent hashing + routing)"
else
  fail "ring did NOT converge correctly"
fi
echo

echo "-- 2. required: finger-table routing gives O(log N) hops, not a linear scan"
for i in $(seq 1 30); do $PY -m meridian.cli --state "$STATE" put "demokey$i" "demoval$i" >/dev/null; done
HOPS=$($PY - "$STATE" <<'PYEOF'
import json, sys
from meridian import client, node as node_mod, hashing
from meridian.node import NodeRef
state = json.load(open(sys.argv[1]))
m = state["m_bits"]
start = NodeRef(id=hashing.node_id_for_addr(state["nodes"][0]["host"], state["nodes"][0]["port"], m), host=state["nodes"][0]["host"], port=state["nodes"][0]["port"])
ok = True
maxhops = 0
for i in range(1, 31):
    v, hops = node_mod.get(f"demokey{i}", start, client.call, m_bits=m)
    if v != f"demoval{i}":
        ok = False
    maxhops = max(maxhops, len(hops))
print(f"{'OK' if ok else 'BROKEN'} {maxhops}")
PYEOF
)
read -r HOPOK MAXHOPS <<< "$HOPS"
if [ "$HOPOK" = "OK" ] && [ "$MAXHOPS" -le 8 ]; then
  pass "30/30 keys correct, max hop count $MAXHOPS for 15 nodes (log2(15)=3.9)"
else
  fail "get() correctness or hop bound violated (status=$HOPOK, maxhops=$MAXHOPS)"
fi
echo

echo "-- 3. required: successor-list replication survives a real SIGKILL"
KILL_TARGET_PORT=$($PY - "$STATE" <<'PYEOF'
import json, sys
from meridian import client, hashing
from meridian.node import NodeRef
state = json.load(open(sys.argv[1]))
m = state["m_bits"]
best = None
for e in state["nodes"]:
    r = NodeRef(id=hashing.node_id_for_addr(e["host"], e["port"], m), host=e["host"], port=e["port"])
    snap = client.call(r, "snapshot", {})
    if best is None or snap["num_primary_keys"] > best[1]:
        best = (e["port"], snap["num_primary_keys"])
print(best[0])
PYEOF
)
$PY -m meridian.cli --state "$STATE" kill "$KILL_TARGET_PORT" > /tmp/meridian_demo_kill.log 2>&1
AFTER_KILL=$($PY - "$STATE" <<'PYEOF'
import json, sys
from meridian import client, node as node_mod, hashing
from meridian.node import NodeRef
state = json.load(open(sys.argv[1]))
m = state["m_bits"]
alive = [e for e in state["nodes"] if not e.get("killed")]
start = NodeRef(id=hashing.node_id_for_addr(alive[0]["host"], alive[0]["port"], m), host=alive[0]["host"], port=alive[0]["port"])
ok = 0
fail = 0
for i in range(1, 31):
    try:
        v, hops = node_mod.get(f"demokey{i}", start, client.call, m_bits=m)
        if v == f"demoval{i}":
            ok += 1
        else:
            fail += 1
    except Exception:
        fail += 1
print(f"{ok} {fail}")
PYEOF
)
read -r OKCOUNT FAILCOUNT <<< "$AFTER_KILL"
if [ "$FAILCOUNT" = "0" ] && [ "$OKCOUNT" = "30" ]; then
  pass "all 30/30 keys still correct immediately after SIGKILLing the node with the most primary keys"
else
  fail "$FAILCOUNT/30 keys lost after kill"
fi
echo

echo "-- 4. required: ring self-heals (join/stabilization) after the kill"
sleep 2
RING_CHECK2=$($PY - "$STATE" <<'PYEOF'
import json, sys
from meridian import client, hashing
from meridian.node import NodeRef, RPCError
state = json.load(open(sys.argv[1]))
m = state["m_bits"]
alive = [e for e in state["nodes"] if not e.get("killed")]
refs = [NodeRef(id=hashing.node_id_for_addr(e["host"], e["port"], m), host=e["host"], port=e["port"]) for e in alive]
ids_sorted = sorted(r.id for r in refs)
ok = True
for r in refs:
    try:
        snap = client.call(r, "snapshot", {})
    except RPCError:
        ok = False
        break
    idx = ids_sorted.index(r.id)
    if snap["successor_list"][0]["id"] != ids_sorted[(idx+1) % len(ids_sorted)]:
        ok = False
    if (snap["predecessor"]["id"] if snap["predecessor"] else None) != ids_sorted[idx-1]:
        ok = False
print("OK" if ok else "BROKEN")
PYEOF
)
if [ "$RING_CHECK2" = "OK" ]; then
  pass "ring self-healed to the exact correct cycle over the 14 remaining live nodes"
else
  fail "ring did not self-heal correctly"
fi
echo

echo "-- 5. stretch: capture a trace and render the interactive HTML visualizer"
if $PY -m meridian.cli --state "$STATE" trace demokey1 demokey15 --out trace.json > /tmp/meridian_demo_trace.log 2>&1 \
   && $PY -m meridian.visualize trace.json /tmp/meridian_demo_ring.html > /tmp/meridian_demo_viz.log 2>&1; then
  pass "trace captured and HTML visualizer rendered to /tmp/meridian_demo_ring.html"
else
  fail "trace/visualize step failed"
fi
echo

echo "-- 6. polish: CLI handles empty/invalid input without a raw traceback"
if $PY -m meridian.cli --state "$STATE" kill "$KILL_TARGET_PORT" >/tmp/meridian_demo_edge1.log 2>&1; then
  fail "killing an already-killed node should have failed cleanly"
else
  grep -q "already" /tmp/meridian_demo_edge1.log && pass "double-kill reports a clear error instead of crashing" \
    || fail "double-kill error message unclear"
fi
if $PY -m meridian.cli --state "$STATE" get this-key-does-not-exist >/tmp/meridian_demo_edge2.log 2>&1; then
  fail "getting a nonexistent key should have failed cleanly"
else
  grep -q "not found" /tmp/meridian_demo_edge2.log && pass "missing-key get() reports a clear error instead of a traceback" \
    || fail "missing-key error message unclear"
fi
echo

echo "-- 7. required: a non-default ring width (--m-bits) still works end-to-end"
$PY -m meridian.cli --state "$STATE" cluster-stop >/dev/null 2>&1
rm -f "$STATE"
if $PY -m meridian.cli --state "$STATE" cluster-start 6 --base-port 21100 --fast --m-bits 12 --join-pause 0.05 > /tmp/meridian_demo_start2.log 2>&1; then
  sleep 1.5
  $PY -m meridian.cli --state "$STATE" put smallring works >/dev/null
  RESULT=$($PY -m meridian.cli --state "$STATE" get smallring)
  if echo "$RESULT" | grep -q "'works'"; then
    pass "12-bit ring (regression test for the m_bits threading bug, REVIEW.md #3) works correctly"
  else
    fail "12-bit ring produced wrong result: $RESULT"
  fi
else
  fail "12-bit ring cluster-start failed"
fi
$PY -m meridian.cli --state "$STATE" cluster-stop >/dev/null 2>&1
rm -f "$STATE"

echo
echo "============================================================"
echo "RESULTS: $PASS passed, $FAIL failed"
if [ "$FAIL" -eq 0 ]; then
  echo "ALL CHECKS PASSED"
  exit 0
else
  echo "SOME CHECKS FAILED"
  exit 1
fi
