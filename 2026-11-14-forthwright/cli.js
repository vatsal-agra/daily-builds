#!/usr/bin/env node
/* forthwright CLI */
const fs = require('fs');
const path = require('path');
const { create, Forth, Analyzer } = require('./src');
const Tracer = require('./src/tracer.js');

const HELP = `forthwright — Forth with static stack-effect inference

usage:
  forthwright run <file.fth> [--no-opt] [--lax]   run a program
  forthwright -e "<code>"                          evaluate code
  forthwright repl                                 interactive session
  forthwright effects <file.fth>                   print the inferred effect of every word
  forthwright see <file.fth> <word>                disassemble a word (after optimization)
  forthwright trace <file.fth> [--max N]           step-by-step trace (data stack per op)
  forthwright profile <file.fth>                   op counts per word
  forthwright test [dir]                           run conformance tests (*.fth) and print a summary
`;

function fail(msg) { process.stderr.write(msg + '\n'); process.exit(1); }
function mk(args) { return create({ optimize: !args.includes('--no-opt'), strict: !args.includes('--lax') }); }
function readSrc(f) { try { return fs.readFileSync(f, 'utf8'); } catch (e) { fail('cannot read ' + f + ': ' + e.code); } }
function report(vm, r, file) {
  if (!r.ok) {
    process.stdout.write(r.output || '');
    const where = r.line ? (file ? file + ':' : 'line ') + r.line + ': ' : '';
    fail((r.output && !r.output.endsWith('\n') ? '\n' : '') + 'error: ' + where + r.error);
  }
}

function effectsTable(vm) {
  const rows = [];
  for (const w of vm.dict.values()) if (w.kind === 'colon' && !w.valueAddr) rows.push(w);
  const width = Math.max(4, ...rows.map(w => w.name.length));
  return rows.map(w => w.name.padEnd(width) + '  ' + Forth.effectString(w)).join('\n');
}

function repl(vm) {
  const rl = require('readline').createInterface({ input: process.stdin, output: process.stdout, prompt: '' });
  vm.onOutput = s => process.stdout.write(s);
  console.log('Forthwright REPL — .S shows the stack, BYE or ctrl-D exits');
  rl.on('line', line => {
    const r = vm.run(line);
    if (!r.ok) {
      if (r.error === 'BYE') { rl.close(); return; }
      process.stdout.write('\n  error: ' + r.error + '\n');
    } else process.stdout.write(vm.cur ? '  compiled\n' : ' ok\n');
  });
}

function runTests(dir) {
  dir = dir || path.join(__dirname, 'test', 'forth');
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.fth')).sort();
  let pass = 0, failN = 0, errs = [];
  for (const f of files) {
    const vm = create();
    const harness = fs.readFileSync(path.join(__dirname, 'test', 'harness.fth'), 'utf8');
    let r = vm.run(harness);
    if (!r.ok) fail('harness failed: ' + r.error);
    r = vm.run(fs.readFileSync(path.join(dir, f), 'utf8'));
    const out = r.output;
    const m = /TESTS (\d+) PASSED (\d+) FAILED (\d+)/.exec(out) || [];
    const lines = out.split('\n').filter(l => l.startsWith('FAIL'));
    const p = +m[2] || 0, fl = +m[3] || 0;
    pass += p; failN += fl;
    if (!r.ok) { failN++; errs.push(f + ': ' + r.error + ' (line ' + r.line + ')'); }
    if (lines.length) errs.push(...lines.map(l => f + ': ' + l));
    console.log(f.padEnd(24) + ' ' + (m[1] || '?') + ' tests, ' + p + ' passed, ' + fl + ' failed' + (r.ok ? '' : '  ERROR ' + r.error));
  }
  console.log('TOTAL passed ' + pass + ', failed ' + failN);
  errs.forEach(e => console.log('  ' + e));
  process.exit(failN ? 1 : 0);
}

const args = process.argv.slice(2);
const cmd = args[0];
if (!cmd || cmd === '-h' || cmd === '--help') { process.stdout.write(HELP); process.exit(cmd ? 0 : 1); }
if (cmd === '-e') {
  if (!args[1]) fail('-e needs code');
  const vm = mk(args); const r = vm.run(args[1]); report(vm, r); if (r.output) process.stdout.write(r.output.endsWith('\n') ? r.output : r.output + '\n');
  if (vm.ds.length) process.stdout.write('stack: ' + vm.ds.join(' ') + '\n');
} else if (cmd === 'repl') repl(mk(args));
else if (cmd === 'run') {
  if (!args[1]) fail('run needs a file');
  const vm = mk(args); const r = vm.run(readSrc(args[1])); report(vm, r, args[1]);
  process.stdout.write(r.output); if (!r.output.endsWith('\n') && r.output) process.stdout.write('\n');
} else if (cmd === 'effects') {
  if (!args[1]) fail('effects needs a file');
  const vm = mk(args); const r = vm.run(readSrc(args[1])); report(vm, r, args[1]);
  console.log(effectsTable(vm));
} else if (cmd === 'see') {
  if (!args[2]) fail('see needs <file> <word>');
  const vm = mk(args); const r = vm.run(readSrc(args[1])); report(vm, r, args[1]);
  const w = vm.find(args[2]); if (!w) fail('no such word: ' + args[2]);
  process.stdout.write(vm.disassemble(w));
} else if (cmd === 'trace') {
  if (!args[1]) fail('trace needs a file');
  const mi = args.indexOf('--max'); const max = mi > 0 ? +args[mi + 1] : 200;
  const vm = mk(args); const t = Tracer.record(vm, readSrc(args[1]), { maxSteps: max });
  t.steps.forEach((s, i) => console.log(String(i).padStart(5) + '  ' + s.word.padEnd(10) + ' ' + s.op.padEnd(18) + ' [' + s.ds.join(' ') + ']'));
  if (t.truncated) console.log('... trace truncated at ' + max + ' steps');
  console.log('final stack: [' + t.final.ds.join(' ') + ']');
  if (t.output) console.log('output: ' + JSON.stringify(t.output));
  if (t.error) fail('error: ' + t.error);
} else if (cmd === 'profile') {
  if (!args[1]) fail('profile needs a file');
  const vm = mk(args); const p = Tracer.profile(vm, readSrc(args[1]));
  console.log('total ops: ' + p.total);
  p.rows.slice(0, 20).forEach(r => console.log(r.name.padEnd(14) + String(r.ops).padStart(10) + '  ' + (r.pct * 100).toFixed(1).padStart(5) + '%  calls ' + r.calls));
  if (p.error) fail('error: ' + p.error);
} else if (cmd === 'test') runTests(args[1]);
else { process.stdout.write(HELP); process.exit(1); }
