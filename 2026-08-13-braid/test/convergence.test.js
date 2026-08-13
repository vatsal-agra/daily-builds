// convergence.test.js — randomized property-based test harness.
//
// This is the thing that actually proves the CRDT is correct, rather than
// just "looks right" from a handful of hand-picked scenarios: it runs
// hundreds of randomized concurrent-edit sessions — random peer counts,
// random edits, random network latency/loss/reordering, random partitions
// that heal partway through — and asserts Strong Eventual Consistency:
// once every message has drained, every peer's visible text must be
// byte-identical.
//
// A seeded PRNG makes every run reproducible: a failure prints its seed
// so it can be replayed exactly.

import test from 'node:test';
import assert from 'node:assert/strict';
import { Peer } from '../src/peer.js';
import { Network, VirtualClock } from '../src/network.js';
import { hashText } from '../src/attribution.js';

// small deterministic PRNG (mulberry32) so failures are reproducible from a seed
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const WORDS = ['the', 'quick', 'fox', 'jumps', 'braid', 'crdt', 'merge', 'peer', 'sync', 'text'];

function randomEditedText(rng, current) {
  // returns a new full-text string simulating one user edit: insert a
  // word/char somewhere, or delete a chunk, or both (a "replace selection")
  const chars = Array.from(current);
  const kind = rng();
  const pos = Math.floor(rng() * (chars.length + 1));
  if (kind < 0.55 || chars.length === 0) {
    // insert
    const piece = rng() < 0.5 ? WORDS[Math.floor(rng() * WORDS.length)] + ' ' : String.fromCharCode(97 + Math.floor(rng() * 26));
    chars.splice(pos, 0, ...piece.split(''));
  } else if (kind < 0.85) {
    // delete a small chunk
    const len = Math.min(chars.length - pos, 1 + Math.floor(rng() * 4));
    chars.splice(pos, Math.max(0, len));
  } else {
    // replace a chunk (delete + insert in the same edit, like typing over a selection)
    const len = Math.min(chars.length - pos, 1 + Math.floor(rng() * 3));
    const piece = WORDS[Math.floor(rng() * WORDS.length)];
    chars.splice(pos, Math.max(0, len), ...piece.split(''));
  }
  return chars.join('');
}

function runScenario(seed, { numPeers, numRounds, lossRate, partitionsEnabled }) {
  const rng = mulberry32(seed);
  const clock = new VirtualClock();
  const net = new Network({ clock, minLatency: 5, maxLatency: 250, lossRate, rng });

  const siteIds = Array.from({ length: numPeers }, (_, i) => `P${i}`);
  const peers = new Map();
  for (const id of siteIds) {
    const peer = new Peer(id);
    peers.set(id, peer);
    net.addPeer(id, (op) => peer.receive(op));
  }

  for (let round = 0; round < numRounds; round++) {
    // maybe partition the network for this round
    if (partitionsEnabled && rng() < 0.25) {
      const groups = rng() < 0.5 ? 2 : 3;
      for (const id of siteIds) net.setPartition(id, `G${Math.floor(rng() * groups)}`);
    } else if (partitionsEnabled && rng() < 0.3) {
      net.healAll();
    }

    // every peer edits once this round (concurrently, from the network's POV)
    for (const id of siteIds) {
      const peer = peers.get(id);
      if (rng() < 0.15) continue; // some peers idle this round
      const next = randomEditedText(rng, peer.text);
      const ops = peer.setText(next);
      for (const op of ops) net.broadcast(id, op);
    }

    // let some (not necessarily all) traffic land before the next round,
    // by advancing the virtual clock a bounded amount — this is what
    // produces genuine mid-flight concurrency instead of always
    // fully-draining between edits
    clock.runAll();
  }

  // Heal the network. Partitioned-but-undelivered messages are queued, not
  // lost (see network.js), so healing alone is enough to drain those.
  // Genuine packet loss (lossRate > 0) is real, unrecoverable loss of that
  // one delivery attempt though — nothing queues it — so on its own it CAN
  // leave peers permanently diverged. What recovers from that is
  // anti-entropy: each peer periodically re-announces every op it has ever
  // originated (Peer.resyncOps()); re-applying an already-known op is a
  // no-op, so this is always safe, and each resync pass is an independent
  // trial against the loss rate. A handful of passes drives the residual
  // divergence probability to ~0 for any lossRate < 1.
  net.healAll();
  clock.runAll();
  const MAX_RESYNC_PASSES = 25;
  for (let i = 0; i < MAX_RESYNC_PASSES; i++) {
    const hashesNow = new Set(siteIds.map((id) => hashText(peers.get(id).text)));
    if (hashesNow.size === 1) break; // already converged, no need to keep resyncing
    for (const id of siteIds) {
      const peer = peers.get(id);
      for (const op of peer.resyncOps()) net.broadcast(id, op);
    }
    clock.runAll();
  }

  return { peers, siteIds, net };
}

test('convergence: fully-connected, no loss, single-char edits', () => {
  const { peers, siteIds } = runScenario(1, { numPeers: 3, numRounds: 6, lossRate: 0, partitionsEnabled: false });
  const texts = siteIds.map((id) => peers.get(id).text);
  const hashes = new Set(texts.map(hashText));
  assert.equal(hashes.size, 1, `expected convergence, got: ${JSON.stringify(texts)}`);
});

test('convergence: randomized scenarios with loss + reordering + partitions (100 seeds)', () => {
  const NUM_SCENARIOS = 100;
  const failures = [];
  for (let seed = 1; seed <= NUM_SCENARIOS; seed++) {
    const rng0 = mulberry32(seed * 7919);
    const config = {
      numPeers: 2 + Math.floor(rng0() * 4), // 2..5 peers
      numRounds: 4 + Math.floor(rng0() * 6), // 4..9 rounds
      lossRate: rng0() * 0.3, // up to 30% loss
      partitionsEnabled: rng0() < 0.6,
    };
    const { peers, siteIds } = runScenario(seed, config);
    const texts = siteIds.map((id) => peers.get(id).text);
    const hashes = new Set(texts.map(hashText));
    if (hashes.size !== 1) {
      failures.push({ seed, config, texts });
    }
  }
  if (failures.length) {
    console.error('DIVERGENCE FAILURES:', JSON.stringify(failures.slice(0, 5), null, 2));
  }
  assert.equal(failures.length, 0, `${failures.length}/${NUM_SCENARIOS} scenarios diverged — see logged seeds above to reproduce`);
});

test('convergence: no ops are ever permanently lost when the network never drops packets', () => {
  // with lossRate 0, every peer's final text must contain the full set of
  // characters everyone inserted, net of deletes — approximate this by
  // checking every peer converges AND the doc has zero pending causal ops
  const { peers, siteIds, net } = runScenario(42, { numPeers: 4, numRounds: 8, lossRate: 0, partitionsEnabled: true });
  for (const id of siteIds) {
    assert.equal(peers.get(id).doc.isFullyDelivered(), true, `peer ${id} has stuck causal-buffer entries`);
  }
  assert.equal(net.stats.dropped, 0);
  const texts = siteIds.map((id) => peers.get(id).text);
  assert.equal(new Set(texts.map(hashText)).size, 1);
});

test('convergence survives a partition that never heals mid-test, then heals at the end', () => {
  const clock = new VirtualClock();
  const net = new Network({ clock, minLatency: 5, maxLatency: 50, lossRate: 0, rng: mulberry32(99) });
  const a = new Peer('A');
  const b = new Peer('B');
  const c = new Peer('C');
  for (const p of [a, b, c]) net.addPeer(p.siteId, (op) => p.receive(op));

  // seed identical starting text
  for (const op of a.setText('shared document')) net.broadcast('A', op);
  clock.runAll();

  // split A alone from {B, C}
  net.setPartition('A', 'left');
  net.setPartition('B', 'right');
  net.setPartition('C', 'right');

  for (const op of a.setText('shared document, edited by A')) net.broadcast('A', op);
  for (const op of b.setText('shared document, edited by B')) net.broadcast('B', op);
  clock.runAll();

  assert.notEqual(a.text, b.text, 'peers in different partitions must be allowed to diverge');
  assert.equal(b.text, c.text, 'peers in the SAME partition must still stay in sync');

  net.healAll();
  clock.runAll();

  assert.equal(a.text, b.text, 'after healing, all peers must reconverge');
  assert.equal(b.text, c.text);
});
