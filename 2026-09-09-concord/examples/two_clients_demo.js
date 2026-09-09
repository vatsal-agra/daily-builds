#!/usr/bin/env node
/**
 * examples/two_clients_demo.js — a narrated, runnable walkthrough of every
 * required feature against the real relay server, printing what's
 * happening at each step. Good starting point if you want to see the
 * system work without opening a browser.
 *
 *   node examples/two_clients_demo.js
 */
'use strict';
const http = require('http');
const { spawn } = require('child_process');
const path = require('path');
const { RGA } = require('../client/crdt.js');

const PORT = 8955;
const HOST = '127.0.0.1';
const DOC = 'walkthrough';

function post(path, body) {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const req = http.request(
      { host: HOST, port: PORT, path, method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': data.length } },
      (res) => { res.resume(); res.on('end', resolve); }
    );
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

function sseConnect(since, onOp) {
  return new Promise((resolveReady) => {
    const req = http.get({ host: HOST, port: PORT, path: `/doc/${DOC}/events?since=${since}` }, (res) => {
      let buf = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        buf += chunk;
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const ev = frame.match(/^event: (.*)$/m);
          const d = frame.match(/^data: (.*)$/m);
          if (!ev || !d) continue;
          if (ev[1] === 'ready') resolveReady({ close: () => req.destroy() });
          if (ev[1] === 'op') onOp(JSON.parse(d[1]));
        }
      });
    });
  });
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function waitUntil(fn) { while (!fn()) await sleep(15); }

async function main() {
  console.log('Starting server/relay.py on port ' + PORT + ' ...');
  const server = spawn('python3', [path.join(__dirname, '..', 'server', 'relay.py'), HOST, String(PORT)], { stdio: 'ignore' });
  await sleep(500);

  const alice = new RGA('alice');
  const bob = new RGA('bob');
  let aliceSeq = 0, bobSeq = 0;

  const aliceConn = await sseConnect(0, (e) => { aliceSeq = e.seq; alice.applyRemote(e.op.op); });
  const bobConn = await sseConnect(0, (e) => { bobSeq = e.seq; bob.applyRemote(e.op.op); });

  console.log('\n--- 1. Live sync ---');
  const greeting = "Let's write together";
  console.log('Alice types ' + JSON.stringify(greeting) + ' ...');
  await post(`/doc/${DOC}/ops`, { siteId: 'alice', ops: alice.localInsert(0, greeting) });
  await waitUntil(() => bob.text() === greeting);
  console.log('Bob sees:', JSON.stringify(bob.text()));

  console.log('\n--- 2. Concurrent edit at the same position ---');
  const expectedLen = greeting.length + 2;
  const aliceOps = alice.localInsert(alice.length(), '!');
  const bobOps = bob.localInsert(bob.length(), '?');
  console.log("Alice and Bob BOTH append to the end at the same instant (Alice: '!', Bob: '?') ...");
  await Promise.all([
    post(`/doc/${DOC}/ops`, { siteId: 'alice', ops: aliceOps }),
    post(`/doc/${DOC}/ops`, { siteId: 'bob', ops: bobOps }),
  ]);
  await waitUntil(() => alice.text().length === expectedLen && bob.text().length === expectedLen);
  console.log('Alice ends up with:', JSON.stringify(alice.text()));
  console.log('Bob   ends up with:', JSON.stringify(bob.text()));
  console.log('Identical, no conflict dialog, no coordinator picked a winner:', alice.text() === bob.text());

  console.log('\n--- 3. Offline editing + merge on reconnect ---');
  console.log('Bob goes offline (closes SSE connection) ...');
  bobConn.close();
  const bobOffline = bob.localInsert(bob.length(), ' (from the offline train)');
  console.log('Bob keeps typing locally with zero network calls:', JSON.stringify(bob.text()));
  console.log('Meanwhile Alice keeps editing online ...');
  await post(`/doc/${DOC}/ops`, { siteId: 'alice', ops: alice.localInsert(0, '[live] ') });
  await sleep(200);
  console.log('Alice now has:', JSON.stringify(alice.text()));
  console.log('Bob reconnects: flushes queued ops + catches up on everything missed ...');
  await post(`/doc/${DOC}/ops`, { siteId: 'bob', ops: bobOffline });
  const bobConn2 = await sseConnect(bobSeq, (e) => { bobSeq = e.seq; bob.applyRemote(e.op.op); });
  await waitUntil(() => bob.text() === alice.text());
  console.log('Bob converges to:', JSON.stringify(bob.text()));
  console.log('Alice still at:  ', JSON.stringify(alice.text()));
  console.log('Converged with no manual merge:', bob.text() === alice.text());

  aliceConn.close();
  bobConn2.close();
  server.kill();
}

main().catch((e) => { console.error(e); process.exit(1); });
