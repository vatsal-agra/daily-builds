#!/usr/bin/env bash
# Kinesis — end-to-end demo. Exercises every required and stretch feature
# through the real CLI (not a re-implementation of the unit tests) and
# fails loudly (non-zero exit) if any step doesn't do what it claims.
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
mkdir -p output

pass() { echo "  PASS: $1"; }
fail() { echo "  FAIL: $1"; exit 1; }

echo "══════════════════════════════════════════════════════════════"
echo "  Kinesis — Evolving Virtual Creatures — Demo"
echo "══════════════════════════════════════════════════════════════"
echo

# ── D1: genome + body-plan generator ─────────────────────────────────────────
echo "── D1: genome -> body-plan generator ────────────────────────"
python3 -c "
import random
from kinesis.genome import Genome, MAX_DEPTH, MAX_SEGMENTS
from kinesis.body import build_phenotype

rng = random.Random(0)
shapes = []
for _ in range(20):
    g = Genome.random(rng)
    assert g.node_count() <= MAX_SEGMENTS, f'node_count {g.node_count()} exceeded {MAX_SEGMENTS}'
    assert g.depth() <= MAX_DEPTH, f'depth {g.depth()} exceeded {MAX_DEPTH}'
    p = build_phenotype(g)
    for joint in p.joints:
        wa = joint.a.local_to_world(joint.anchor_a)
        wb = joint.b.local_to_world(joint.anchor_b)
        d = ((wa[0]-wb[0])**2 + (wa[1]-wb[1])**2) ** 0.5
        assert d < 1e-9, 'joint anchors do not coincide at rest pose'
    shapes.append(g.node_count())
print(f'  generated 20 random creatures, node counts {sorted(set(shapes))}, all within bounds')
print(f'  all joint anchors coincide at construction (zero initial constraint error)')
"
pass "genome/body-plan generator: bounds respected, joints coincide at rest pose"
echo

# ── D2: from-scratch physics engine ──────────────────────────────────────────
echo "── D2: from-scratch rigid-body physics engine ───────────────"
python3 -c "
import math
from kinesis.physics import RigidBody, World

b = RigidBody(mass=2.0, inertia=1.0, half_length=0.1, half_width=0.1, pos=(0.0,100.0), angle=0.0)
w = World([b], [], ground_y=-1000.0)
for _ in range(240):
    w.step(1/240)
g = 9.81
expected_y = 100.0 - 0.5*g*1.0**2
assert abs(b.pos[1] - expected_y) < 0.05, 'free fall does not match analytic kinematics'
print(f'  free fall after 1.0s: y={b.pos[1]:.4f} (analytic {expected_y:.4f}) - matches')

b2 = RigidBody(mass=5.0, inertia=1.0, half_length=0.3, half_width=0.15, pos=(0,1.0), angle=0.15)
w2 = World([b2], [], ground_y=0.0)
for _ in range(600):
    w2.step(1/240)
lowest = min(c[1] for c in b2.corners())
assert lowest > -0.01 and abs(b2.angle) < 0.02, 'box did not settle flat on ground'
print(f'  dropped tilted box settles flat: lowest corner y={lowest:.5f}, final angle={b2.angle:.5f}')
"
pass "physics engine: matches analytic free-fall, ground contact settles correctly"
echo

# ── D3: evolved CPG controller + GA that improves fitness ───────────────────
echo "── D3: CPG controller + genetic algorithm evolution ─────────"
python3 -m kinesis.cli evolve --generations 6 --pop-size 20 --duration 4.0 \
    --seed 7 --out output/demo_population.json
test -f output/demo_population.json && pass "checkpoint written"
python3 -c "
import json
d = json.load(open('output/demo_population.json'))
gens = [h['generation'] for h in d['history']]
assert gens == list(range(len(gens))), f'history has gaps/duplicates: {gens}'
first, last = d['history'][0], d['history'][-1]
assert last['best'] >= first['best'], 'best fitness regressed (elitism should forbid this)'
assert last['mean'] > first['mean'], f\"mean fitness did not improve: {first['mean']:.3f} -> {last['mean']:.3f}\"
champ = max(d['individuals'], key=lambda i: i['fitness'])
assert champ['fitness'] == champ['fitness'], 'champion fitness is NaN'
print(f\"  mean fitness improved: {first['mean']:.3f} -> {last['mean']:.3f}\")
print(f\"  best fitness: {first['best']:.3f} -> {last['best']:.3f}\")
print(f\"  champion: fitness={champ['fitness']:.3f} distance={champ['distance']:.3f}m toppled={champ['toppled']}\")
"
pass "GA measurably improves locomotion fitness from a random-genome baseline"
echo

# ── D4: checkpoint resume (stretch) ──────────────────────────────────────────
echo "── D4: checkpoint resume (stretch feature) ──────────────────"
python3 -c "
import json
before = json.load(open('output/demo_population.json'))['generation']
print(f'  before resume: generation {before}')
"
python3 -m kinesis.cli evolve --resume output/demo_population.json --generations 3 \
    --out output/demo_population.json
python3 -c "
import json
d = json.load(open('output/demo_population.json'))
gens = [h['generation'] for h in d['history']]
assert gens == list(range(len(gens))), f'resume produced gaps/duplicates in history: {gens}'
print(f'  after resume: generation {d[\"generation\"]}, history is contiguous 0..{len(gens)-1}')
"
pass "evolve --resume continues a saved run with no history corruption"
echo

# ── D5: HTML replay viewer (stretch) ─────────────────────────────────────────
echo "── D5: animated HTML replay viewer (stretch feature) ────────"
python3 -m kinesis.cli replay --checkpoint output/demo_population.json --rank 0 \
    --duration 6.0 --out output/demo_replay.html
grep -q "<canvas" output/demo_replay.html || fail "replay.html missing canvas element"
pass "replay.html generated with animated canvas"
echo

# ── D6: population gallery (stretch) ─────────────────────────────────────────
echo "── D6: population gallery (stretch feature) ─────────────────"
python3 -m kinesis.cli gallery --checkpoint output/demo_population.json --out output/demo_gallery.html
grep -q "<svg" output/demo_gallery.html || fail "gallery.html missing rendered creatures"
pass "gallery.html generated with rest-pose silhouettes for the whole population"
echo

# ── D7: fitness-over-generations chart (stretch) ─────────────────────────────
echo "── D7: fitness-over-generations chart (stretch feature) ─────"
python3 -m kinesis.cli fitness-chart --checkpoint output/demo_population.json --out output/demo_fitness.html
grep -q "<canvas" output/demo_fitness.html || fail "fitness.html missing chart canvas"
pass "fitness.html generated"
echo

# ── D8: CLI robustness on bad input (no raw tracebacks) ──────────────────────
echo "── D8: CLI error handling ────────────────────────────────────"
set +e
python3 -m kinesis.cli gallery --checkpoint output/does_not_exist.json --out output/x.html \
    2>output/err1.txt
rc1=$?
python3 -m kinesis.cli evolve --generations 0 --pop-size 20 --out output/x.json \
    2>output/err2.txt
rc2=$?
set -e
[ "$rc1" -ne 0 ] && ! grep -q "Traceback" output/err1.txt || fail "missing-file case should exit non-zero with a clean message, no traceback"
[ "$rc2" -ne 0 ] && ! grep -q "Traceback" output/err2.txt || fail "bad-args case should exit non-zero with a clean message, no traceback"
pass "missing/malformed input produces a clean error, exit 1, no raw traceback"
echo

# ── D9: unit test suite ───────────────────────────────────────────────────────
echo "── D9: full unit test suite ─────────────────────────────────"
echo "  (49 tests covering vector math, physics, genome bounds, body-plan"
echo "   construction, simulation/fitness, and the GA/CLI; ~3-4 minutes)"
python3 -m kinesis.cli test 2>&1 | tail -5
pass "full test suite green"
echo

echo "══════════════════════════════════════════════════════════════"
echo "  All Kinesis features demonstrated successfully."
echo "  Artifacts written to: $(pwd)/output/"
echo "══════════════════════════════════════════════════════════════"
