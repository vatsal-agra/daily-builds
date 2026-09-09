#!/usr/bin/env node
/**
 * fuzz_convergence.js — the real correctness gate for crdt.js.
 *
 * `require`s the exact file that ships to the browser (no separate
 * reimplementation to drift out of sync — same pattern as this repo's Kiln
 * differentially testing against Node's real WASM engine, or Graft testing
 * against real `git`). Simulates N independent sites concurrently editing
 * the same document with zero coordination, replicates every operation to
 * every other site in an independently-randomized order per receiving site
 * (including fully-reversed and randomly-scrambled orders that force the
 * causal-buffering path), and asserts the one property that actually
 * matters for a CRDT: every replica that has seen the same set of
 * operations ends up with byte-identical visible text, regardless of the
 * order operations arrived in.
 *
 * Exit code 0 = every trial converged. Exit code 1 = a counterexample was
 * found (printed with enough detail to reproduce and debug).
 */
'use strict';
const { RGA } = require('../client/crdt.js');

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

function shuffle(arr, rand) {
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    const tmp = out[i];
    out[i] = out[j];
    out[j] = tmp;
  }
  return out;
}

const ALPHABET = 'abcdefghij 日本語🎉'.split(''); // ascii + multi-byte unicode + emoji

function randomEditScript(rand, siteId, numOps, currentLenGetter) {
  const rga = new RGA(siteId);
  const allOps = [];
  for (let i = 0; i < numOps; i++) {
    const len = currentLenGetter();
    const doInsert = rand() < 0.7 || len === 0;
    if (doInsert) {
      const pos = Math.floor(rand() * (len + 1));
      const runLen = 1 + Math.floor(rand() * 4);
      let text = '';
      for (let k = 0; k < runLen; k++) {
        text += ALPHABET[Math.floor(rand() * ALPHABET.length)];
      }
      allOps.push({ site: rga, pos, text });
    } else {
      const pos = Math.floor(rand() * len);
      const runLen = 1 + Math.floor(rand() * Math.min(3, len - pos));
      allOps.push({ site: rga, pos, del: runLen });
    }
  }
  return { rga, allOps };
}

function runTrial(seed, numSites, opsPerSite) {
  const rand = mulberry32(seed);
  const sites = [];
  for (let s = 0; s < numSites; s++) {
    sites.push(new RGA('site' + s + '-' + seed));
  }

  // Each site independently generates a script of local edits against its
  // OWN evolving view (so positions are always valid for that site at the
  // time it made the edit), collecting the wire ops it produced.
  const opsFromSite = sites.map(() => []);
  for (let round = 0; round < opsPerSite; round++) {
    for (let s = 0; s < numSites; s++) {
      const rga = sites[s];
      const len = rga.length();
      const doInsert = rand() < 0.7 || len === 0;
      let generated;
      if (doInsert) {
        const pos = Math.floor(rand() * (len + 1));
        const runLen = 1 + Math.floor(rand() * 4);
        let text = '';
        for (let k = 0; k < runLen; k++) {
          text += ALPHABET[Math.floor(rand() * ALPHABET.length)];
        }
        generated = rga.localInsert(pos, text);
      } else {
        const pos = Math.floor(rand() * len);
        const runLen = 1 + Math.floor(rand() * Math.min(3, len - pos));
        generated = rga.localDelete(pos, runLen);
      }
      opsFromSite[s].push.apply(opsFromSite[s], generated);
    }
  }

  // Every op that was ever generated anywhere, in generation order per
  // origin site (a real network preserves per-connection/per-site order —
  // TCP doesn't reorder a single stream — but ACROSS sites, arrival order
  // is unconstrained, which is exactly what we fuzz).
  const allOpsInOrder = [];
  for (let s = 0; s < numSites; s++) allOpsInOrder.push.apply(allOpsInOrder, opsFromSite[s]);

  // Build N *fresh* replicas and replicate the full op set to each one in
  // an independently shuffled order (but preserving each origin site's own
  // relative op order, matching a real single-connection-per-site network).
  const replicas = [];
  for (let s = 0; s < numSites; s++) {
    const replica = new RGA('replica' + s + '-' + seed);
    // Interleave per-site queues in a random order while respecting each
    // queue's internal order.
    const queues = opsFromSite.map((q) => q.slice());
    const order = [];
    let remaining = queues.reduce((n, q) => n + q.length, 0);
    while (remaining > 0) {
      const nonEmpty = [];
      for (let k = 0; k < queues.length; k++) if (queues[k].length) nonEmpty.push(k);
      const pick = nonEmpty[Math.floor(rand() * nonEmpty.length)];
      order.push(queues[pick].shift());
      remaining -= 1;
    }
    for (const op of order) replica.applyRemote(op);
    // Idempotence check: redeliver the whole stream once more (simulates a
    // relay redelivering on reconnect). Must be a complete no-op.
    const before = replica.text();
    for (const op of order) replica.applyRemote(op);
    if (replica.text() !== before) {
      return { ok: false, reason: 'not idempotent under redelivery', seed };
    }
    if (replica.pendingCount() !== 0) {
      return { ok: false, reason: 'ops left permanently buffered', seed, pending: replica.pendingCount() };
    }
    replicas.push(replica);
  }

  // Also feed one replica the FULLY REVERSED order, to specifically force
  // every insert/delete through the causal-buffering path (this is the
  // adversarial case: a dependency's op is always the LAST thing to
  // arrive).
  const reversedReplica = new RGA('reversed-' + seed);
  const reversedOrder = allOpsInOrder.slice().reverse();
  for (const op of reversedOrder) reversedReplica.applyRemote(op);
  if (reversedReplica.pendingCount() !== 0) {
    return { ok: false, reason: 'reversed-order replica has leaked pending ops', seed };
  }
  replicas.push(reversedReplica);

  // And one replica fed a TOTAL scramble that doesn't even respect each
  // origin site's own op order — stronger than any real network actually
  // does (a single TCP connection can't reorder itself), but strictly
  // more adversarial, and it's cheap to also prove the engine survives it:
  // a delete can arrive before its own insert, in the middle of an
  // unrelated site's multi-character run, etc.
  const scrambledReplica = new RGA('scrambled-' + seed);
  const scrambledOrder = shuffle(allOpsInOrder, rand);
  for (const op of scrambledOrder) scrambledReplica.applyRemote(op);
  if (scrambledReplica.pendingCount() !== 0) {
    return { ok: false, reason: 'fully-scrambled-order replica has leaked pending ops', seed };
  }
  replicas.push(scrambledReplica);

  const texts = replicas.map((r) => r.text());
  const first = texts[0];
  for (let i = 1; i < texts.length; i++) {
    if (texts[i] !== first) {
      return {
        ok: false,
        reason: 'divergent replicas',
        seed,
        texts: texts,
      };
    }
  }
  return { ok: true, text: first, opCount: allOpsInOrder.length };
}

function main() {
  const TRIALS = parseInt(process.argv[2] || '1500', 10);
  let longestConvergedText = '';
  let totalOps = 0;
  for (let t = 0; t < TRIALS; t++) {
    const numSites = 2 + (t % 4); // 2..5 sites
    const opsPerSite = 1 + (t % 12); // 1..12 edits per site per trial
    const result = runTrial(1000000 + t, numSites, opsPerSite);
    if (!result.ok) {
      console.error('FAIL trial ' + t + ': ' + result.reason);
      console.error(JSON.stringify(result, null, 2));
      process.exit(1);
    }
    totalOps += result.opCount;
    if (result.text.length > longestConvergedText.length) longestConvergedText = result.text;
  }
  console.log(
    'OK: ' + TRIALS + ' trials converged (' + totalOps + ' total ops replicated across randomized delivery orders, incl. reversed-order causal-buffering stress)'
  );
  console.log('Example converged text (' + longestConvergedText.length + ' chars): ' + JSON.stringify(longestConvergedText.slice(0, 80)) + (longestConvergedText.length > 80 ? '...' : ''));
}

main();
