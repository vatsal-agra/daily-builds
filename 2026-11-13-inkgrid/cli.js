#!/usr/bin/env node
'use strict';
const fs = require('fs');
const E = require('./src/engine.js');
const USAGE = `inkgrid — nonogram toolkit
  node cli.js gen <WxH> [--seed S] [--difficulty easy|medium|hard|expert|any] [--density 0.55] [--format non|json|ascii]
  node cli.js solve <file|-> [--all]      solve a .non/JSON puzzle (counts solutions up to 2)
  node cli.js rate  <file|->              measure difficulty
  node cli.js hint  <file|->              the first logical deduction from an empty board`;
function opts(args) { const o = { _: [] }; for (let i = 0; i < args.length; i++) { if (args[i].startsWith('--')) { const k = args[i].slice(2); const nx = args[i + 1]; if (nx === undefined || nx.startsWith('--')) o[k] = true; else { o[k] = nx; i++; } } else o._.push(args[i]); } return o; }
function read(f) { return fs.readFileSync(f === '-' ? 0 : f, 'utf8'); }
function main(argv) {
  const [cmd, ...rest] = argv, o = opts(rest);
  if (!cmd || cmd === 'help' || cmd === '--help') { console.log(USAGE); return 0; }
  if (cmd === 'gen') {
    const m = /^(\d+)x(\d+)$/.exec(o._[0] || ''); if (!m) throw new Error('size must look like 15x15');
    const g = E.generate({ w: +m[1], h: +m[2], seed: o.seed == null ? 1 : o.seed, difficulty: o.difficulty || 'any', density: o.density ? +o.density : 0.55, strict: !!o.strict });
    const f = o.format || 'non', p = { rows: g.rows, cols: g.cols };
    if (f === 'json') console.log(JSON.stringify(Object.assign({ rating: g.rating }, p)));
    else if (f === 'ascii') console.log(E.render(g.grid) + '\n' + g.rating.label + ' (score ' + g.rating.score + ')');
    else process.stdout.write(E.toNon(p, 'seed ' + g.seed));
    if (g.relaxed) console.error('note: requested difficulty not reached; closest unique puzzle returned (' + g.rating.label + ')');
    return 0;
  }
  if (['solve', 'rate', 'hint'].includes(cmd)) {
    if (!o._[0]) throw new Error(cmd + ' needs a file (or - for stdin)');
    const p = E.parsePuzzle(read(o._[0]));
    if (cmd === 'rate') { console.log(JSON.stringify(E.rate(p, { force: true }), null, 2)); return 0; }
    if (cmd === 'hint') { const h = E.findHint(p, new Int8Array(p.rows.length * p.cols.length).fill(-1)); console.log(h.message); return 0; }
    const r = E.solve(p, { limit: o.all ? 2 : 2 });
    if (!r.count) { console.error(r.truncated ? 'gave up: search limit reached' : 'no solution'); return 2; }
    console.log(E.render(r.solutions[0]));
    console.log(r.count === 1 && !r.truncated ? 'unique solution' : 'MULTIPLE solutions (showing first)');
    if (o.all && r.count > 1) console.log('\nanother:\n' + E.render(r.solutions[1]));
    return 0;
  }
  throw new Error('unknown command "' + cmd + '"\n' + USAGE);
}
try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error('error: ' + e.message); process.exitCode = 1; }
