#!/usr/bin/env node
/**
 * test_integration.js — end-to-end test against the REAL relay.py server
 * (spawned as a real child process, real TCP, real HTTP, real SSE) using
 * TWO real RGA replicas (client/crdt.js, unmodified) as two independent
 * simulated browser tabs. No mocks anywhere in this file: if this passes,
 * the actual shipped server and the actual shipped engine talk to each
 * other correctly.
 *
 * Exercises, against the live server:
 *   1. basic live multi-client sync (site A types, site B sees it appear)
 *   2. offline editing + merge-on-reconnect (site B disconnects from the
 *      SSE stream, edits locally with zero network calls, reconnects, and
 *      converges with site A which kept editing while B was gone)
 *
 * Run: node tests/test_integration.js
 */
'use strict';
const http = require('http');
const { spawn } = require('child_process');
const path = require('path');
const { RGA } = require('../client/crdt.js');

const PORT = 8934 + (process.pid % 500);
const HOST = '127.0.0.1';
const DOC = 'inttest-' + process.pid;

function httpJson(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null;
    const req = http.request(
      { host: HOST, port: PORT, path, method, headers: data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {} },
      (res) => {
        let chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          try {
            resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') });
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

/** A minimal hand-rolled SSE client good enough for this test: opens the
 *  connection, parses "event: X\ndata: Y\n\n" frames as they stream in,
 *  and dispatches to `onEvent(eventName, jsonData)`. Returns a handle with
 *  `.close()`. */
function sseConnect(docId, since, onEvent) {
  return new Promise((resolveConnected) => {
    const req = http.get(
      { host: HOST, port: PORT, path: `/doc/${docId}/events?since=${since}` },
      (res) => {
        let buf = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          buf += chunk;
          let idx;
          while ((idx = buf.indexOf('\n\n')) !== -1) {
            const frame = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            if (!frame.trim() || frame.startsWith(':')) continue;
            const eventMatch = frame.match(/^event: (.*)$/m);
            const dataMatch = frame.match(/^data: (.*)$/m);
            if (!eventMatch || !dataMatch) continue;
            const eventName = eventMatch[1];
            const data = JSON.parse(dataMatch[1]);
            if (eventName === 'ready') resolveConnected({ close: () => req.destroy() });
            onEvent(eventName, data);
          }
        });
      }
    );
    req.on('error', () => {});
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitUntil(fn, timeoutMs, label) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (fn()) return;
    await sleep(20);
  }
  throw new Error('timeout waiting for: ' + label);
}

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL: ' + msg);
    process.exitCode = 1;
    throw new Error(msg);
  }
  console.log('ok - ' + msg);
}

async function main() {
  const server = spawn('python3', [path.join(__dirname, '..', 'server', 'relay.py'), HOST, String(PORT)], {
    stdio: 'ignore',
  });
  server.on('error', (e) => {
    console.error('failed to launch relay.py:', e);
    process.exitCode = 1;
  });

  try {
    await sleep(500); // let the server bind

    // ---- two independent replicas, exactly like two browser tabs ----
    const a = new RGA('clientA');
    const b = new RGA('clientB');
    let aSeq = 0,
      bSeq = 0;

    const connA = await sseConnect(DOC, aSeq, (event, data) => {
      if (event !== 'op') return;
      aSeq = data.seq;
      if (data.op.siteId === 'clientA') return; // skip own echo
      a.applyRemote(data.op.op);
    });
    const connB = await sseConnect(DOC, bSeq, (event, data) => {
      if (event !== 'op') return;
      bSeq = data.seq;
      if (data.op.siteId === 'clientB') return;
      b.applyRemote(data.op.op);
    });

    // === Part 1: basic live sync ===
    const ops1 = a.localInsert(0, 'hello concord');
    await httpJson('POST', `/doc/${DOC}/ops`, { siteId: 'clientA', ops: ops1 });
    await waitUntil(() => b.text() === 'hello concord', 2000, 'site B receives site A live typing');
    assert(b.text() === 'hello concord', 'site B text matches after live sync');

    // site B replies live
    const ops2 = b.localInsert(b.length(), '!');
    await httpJson('POST', `/doc/${DOC}/ops`, { siteId: 'clientB', ops: ops2 });
    await waitUntil(() => a.text() === 'hello concord!', 2000, 'site A receives site B live typing');
    assert(a.text() === 'hello concord!', 'site A text matches after live sync');

    // === Part 2: offline editing + merge on reconnect ===
    // Site B "goes offline": close its SSE connection and stop sending
    // anything to the relay, but keep editing its local replica — this is
    // exactly what the browser's offline toggle does via net.js.
    connB.close();
    const offlineOpsFromB = b.localInsert(b.length(), ' (written offline)');
    assert(b.text() === 'hello concord! (written offline)', "site B's own offline edit is visible to itself immediately");

    // Meanwhile site A, still connected, keeps editing and publishing.
    const opsFromA = a.localInsert(0, '[A] ');
    await httpJson('POST', `/doc/${DOC}/ops`, { siteId: 'clientA', ops: opsFromA });
    await sleep(200);
    assert(a.text() === '[A] hello concord!', "site A's own online edit lands immediately");
    // B does NOT know about this yet - it's offline.
    assert(!b.text().startsWith('[A] '), "site B hasn't seen A's edit while offline (sanity check on the test itself)");

    // Site B reconnects: (1) flush its queued offline ops to the relay,
    // (2) resubscribe from its last known seq to pick up everything it
    // missed (A's '[A] ' insert) — exactly net.js's connect()+_flushOutbox().
    await httpJson('POST', `/doc/${DOC}/ops`, { siteId: 'clientB', ops: offlineOpsFromB });
    const connB2 = await sseConnect(DOC, bSeq, (event, data) => {
      if (event !== 'op') return;
      bSeq = data.seq;
      if (data.op.siteId === 'clientB') return;
      b.applyRemote(data.op.op);
    });

    await waitUntil(
      () => b.text() === a.text(),
      3000,
      'site B converges with site A after reconnect (offline edits merged with edits made while B was gone)'
    );
    assert(b.text() === a.text(), 'final text identical after offline merge: ' + JSON.stringify(b.text()));
    assert(b.text() === '[A] hello concord! (written offline)', 'merged text is exactly what both edits should produce');
    assert(a.pendingCount() === 0 && b.pendingCount() === 0, 'no ops left permanently buffered on either replica');

    connA.close();
    connB2.close();
    console.log('\nALL INTEGRATION CHECKS PASSED');
  } finally {
    server.kill();
  }
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
