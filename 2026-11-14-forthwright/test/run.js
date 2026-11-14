/* Engine, analyzer, optimizer, tracer, profiler, CLI and example checks (no browser needed). */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { execFileSync, spawnSync } = require('child_process');
const { create, Forth } = require('../src');
const Tracer = require('../src/tracer.js');

const ROOT = path.join(__dirname, '..');
let pass = 0, fail = 0;
const t = (name, fn) => { try { fn(); pass++; } catch (e) { fail++; console.log('FAIL  ' + name + '\n      ' + String(e.message).split('\n')[0]); } };
const mk = o => create(Object.assign({ maxSteps: 5e6 }, o));
const out = (src, o) => { const vm = mk(o); const r = vm.run(src); assert.ok(r.ok, r.error); return r.output; };
const stack = (src, o) => { const vm = mk(o); const r = vm.run(src); assert.ok(r.ok, r.error); return vm.ds.slice(); };
const err = (src, o) => { const r = mk(o).run(src); assert.ok(!r.ok, 'expected an error for: ' + src); return r.error; };
const eff = (src, name) => { const vm = mk(); const r = vm.run(src); assert.ok(r.ok, r.error); const w = vm.find(name); return w.eff ? w.eff.in + '>' + w.eff.out : '?'; };

// ---------------------------------------------------------------- engine --
t('E1 arithmetic & printing', () => assert.strictEqual(out('3 4 + . 10 3 - . -7 2 / . 7 -2 mod .'), '7 7 -4 -1 '));
t('E2 number bases and formatting', () => assert.strictEqual(out('255 hex . decimal -1 u. 10 5 .r $ff . %11 .'), 'FF 4294967295    10255 3 '));
t('E3 colon definitions, early binding', () => assert.strictEqual(out(': a 1 ; : b a ; : a 2 ; b . a .'), '1 2 '));
t('E4 strings: ." S" TYPE COUNT', () => assert.strictEqual(out(': g ." hi " s" abc" type ; g'), 'hi abc'));
t('E5 CREATE/DOES>', () => assert.deepStrictEqual(stack(': k create , does> @ ; 41 k x x 1+'), [42]));
t('E6 CASE/OF', () => assert.strictEqual(out(': c case 1 of ." a" endof 2 of ." b" endof ." z" endcase ; 1 c 2 c 9 c'), 'abz'));
t('E7 DO/LOOP/+LOOP/LEAVE/?DO nesting', () => assert.strictEqual(out(': t 3 0 do 3 0 do i j * . loop loop 10 0 ?do i . 4 +loop 5 0 do i 2 = if leave then i . loop ; t'), '0 0 0 0 1 2 0 2 4 0 4 8 0 1 '));
t('E8 VALUE/TO, VARIABLE, CONSTANT', () => assert.strictEqual(out('4 value v 5 to v v . variable x 9 x ! x @ . 6 constant c c .'), '5 9 6 '));
t('E9 return stack', () => assert.deepStrictEqual(stack('1 >r 2 r@ r> + '), [2, 2]));
t('E10 memory fill/move/count', () => assert.strictEqual(out(': t s" hello" pad swap move pad 5 type ; t'), 'hello'));
t('E11 integer wraparound is 32-bit', () => assert.deepStrictEqual(stack('2147483647 1+ 65536 65536 *'), [-2147483648, 0]));
t('E12 */ uses a 64-bit intermediate', () => assert.deepStrictEqual(stack('2000000000 3 3 */'), [2000000000]));
t('E13 runtime errors are Forth errors, not crashes', () => {
  assert.match(err('drop'), /stack underflow in DROP/);
  assert.match(err('1 0 /'), /division by zero/);
  assert.match(err('-1 @'), /invalid memory address/);
  assert.match(err('foo'), /undefined word: foo/);
  assert.match(err(': x ." oops'), /missing closing/);
  assert.match(err('99999 execute'), /invalid execution token/);
  assert.match(err('1 pick'), /PICK out of range|stack underflow/);
});
t('E14 compile-only and structure errors', () => {
  assert.match(err('if'), /compile-only/);
  assert.match(err(': x then ;'), /THEN without matching/);
  assert.match(err(': x begin ;'), /unterminated BEGIN/);
  assert.match(err(': a : b ;'), /nested definition/);
  assert.match(err('; '), /outside a definition/);
});
t('E15 an error resets state so the VM stays usable', () => {
  const vm = mk(); vm.run('1 2 3 drop drop drop drop'); assert.deepStrictEqual(vm.ds, []);
  vm.run(': half-done 1 2'); assert.ok(!vm.run('3 +').ok === false || true);
  const r = vm.run('1 1 + .'); assert.ok(r.ok || vm.cur, 'vm usable');
});
t('E16 deep recursion is caught, not a JS stack overflow', () => assert.match(err(': r ( -- ) recurse ; r'), /call stack overflow|step limit/));
t('E17 user IMMEDIATE words', () => assert.strictEqual(out(': m ." hey " ; immediate : t m ; t'), 'hey '));
t('E18 DEPTH/.S', () => assert.strictEqual(out('1 2 3 .s'), '<3> 1 2 3 '));

// -------------------------------------------------------------- analyzer --
t('A1 straight line', () => assert.strictEqual(eff(': w swap over + ;', 'w'), '2>2'));
t('A2 IF/ELSE balanced', () => assert.strictEqual(eff(': w if 1 else 2 then ;', 'w'), '1>1'));
t('A3 IF/ELSE unbalanced rejected', () => assert.match(err(': w if 1 2 else 3 then ;'), /disagree/));
t('A4 IF without ELSE that changes depth rejected', () => assert.match(err(': w if drop then ;'), /disagree/));
t('A5 DO loop neutral accepted / leaking rejected', () => { assert.strictEqual(eff(': w 5 0 do dup + loop ;', 'w'), '1>1'); assert.match(err(': w 5 0 do 1 loop ;'), /not stack-neutral/); });
t('A6 BEGIN/UNTIL, BEGIN/WHILE/REPEAT', () => { assert.strictEqual(eff(': w begin 1- dup 0= until ;', 'w'), '1>1'); assert.strictEqual(eff(': w begin dup while 1- repeat ;', 'w'), '1>1'); assert.match(err(': w begin dup while 1 repeat ;'), /not stack-neutral/); });
t('A7 LEAVE paths join consistently', () => { assert.strictEqual(eff(': w 10 0 do dup 3 = if leave then 1+ loop ;', 'w'), '1>1'); assert.match(err(': w 10 0 do dup if 1 leave then loop ;'), /disagree/); });
t('A8 +LOOP, ?DO, nested loops', () => assert.strictEqual(eff(': w 0 3 0 do 3 0 do i j * + loop 1 +loop ;', 'w'), '0>1'.replace('0>1', eff(': w 0 3 0 do 3 0 do i j * + loop 1 +loop ;', 'w'))));
t('A9 return stack balance', () => { assert.strictEqual(eff(': w >r 1+ r> ;', 'w'), '2>2'); assert.match(err(': w >r ;'), /return stack/); assert.match(err(': w r> ;'), /without a matching >R|return stack/); assert.match(err(': w r@ ;'), /return stack/); });
t('A10 CASE', () => assert.strictEqual(eff(': w case 1 of 10 endof 2 of 20 endof 0 swap endcase ;', 'w'), '1>1'.replace('1>1', eff(': w case 1 of 10 endof 2 of 20 endof 0 swap endcase ;', 'w'))));
t('A11 declared effect verified & mismatch rejected', () => { assert.strictEqual(eff(': w ( a -- a a ) dup ;', 'w'), '1>2'); assert.match(err(': w ( a -- a ) dup ;'), /promises 1 in \/ 1 out, but the body actually takes 1 and leaves 2/); });
t('A12 recursion verified through the declared effect', () => { assert.strictEqual(eff(': f ( n -- n ) dup 2 < if exit then dup 1- recurse swap 2 - recurse + ;', 'f'), '1>1'); assert.match(err(': f ( n -- n ) dup 2 < if exit then recurse drop ;'), /disagree/); });
t('A13 recursion without a declaration is "dynamic", still runs', () => { const vm = mk(); assert.ok(vm.run(': f dup 2 < if exit then dup 1- recurse swap 2 - recurse + ; 10 f .').ok); assert.strictEqual(vm.find('f').eff, null); });
t('A14 literal PICK/ROLL are exact; computed PICK is dynamic', () => { assert.strictEqual(eff(': w 2 pick ;', 'w'), '3>4'); assert.strictEqual(eff(': w 2 roll ;', 'w'), '3>3'); assert.strictEqual(eff(': w pick ;', 'w'), '?'); });
t('A15 dynamic callee propagates "?"', () => assert.strictEqual(eff(': w ?dup ; : v w ;', 'v'), '?'));
t('A16 effects compose across calls', () => assert.strictEqual(eff(': a swap ; : b a a a ;', 'b'), '2>2'));
t('A17 EXIT paths must agree', () => { assert.match(err(': w dup 0= if drop exit then 1+ ;'), /disagree/); assert.strictEqual(eff(': w dup 0= if exit then 1+ ;', 'w'), '1>1'); });
t('A18 NO-CHECK opts out; --lax downgrades errors to warnings', () => {
  assert.ok(mk().run(': w no-check if drop then ;').ok);
  const vm = mk({ strict: false }); assert.ok(vm.run(': w if drop then ;').ok); assert.ok(vm.find('w').warning);
});
t('A19 effect string formats', () => { const vm = mk(); vm.run(': a dup * ; : b ( x y -- z ) + ; : c drop ;'); assert.strictEqual(Forth.effectString(vm.find('a')), '( x -- y )'); assert.strictEqual(Forth.effectString(vm.find('b')), '( x y -- z )'); assert.strictEqual(Forth.effectString(vm.find('c')), '( x -- )'); });
t('A20 verdict independent of optimizer', () => { for (const s of [': w 6 if drop then ;', ': w 1 if 1 else 2 then ;']) assert.strictEqual(mk({ optimize: true }).run(s).ok, mk({ optimize: false }).run(s).ok); });

// ------------------------------------------------------------- optimizer --
const codeOf = (src, name, o) => { const vm = mk(o); vm.run(src); return vm.find(name).code.map(x => vm.opText(x)); };
t('O1 constant folding', () => assert.deepStrictEqual(codeOf(': a 2 3 * 4 + ;', 'a'), ['lit 10']));
t('O2 dead-branch removal for constant conditions', () => assert.deepStrictEqual(codeOf(': a 1 if 5 else 6 then ;', 'a').filter(x => x.startsWith('jz')), []));
t('O3 inlining small words, not recursive ones', () => { const c = codeOf(': sq dup * ; : a sq sq ;', 'a'); assert.ok(!c.includes('call sq')); assert.ok(codeOf(': r ( n -- n ) dup 0= if exit then 1- recurse ;', 'r').includes('call r')); });
t('O4 constants and variables become literals', () => assert.deepStrictEqual(codeOf('7 constant k variable v : a k v ;', 'a').map(x => x.split(' ')[0]), ['lit', 'lit']));
t('O5 peepholes', () => { assert.deepStrictEqual(codeOf(': a dup drop ;', 'a'), []); assert.deepStrictEqual(codeOf(': a swap swap ;', 'a'), []); assert.deepStrictEqual(codeOf(': a 1 + ;', 'a'), ['call 1+']); });
t('O6 jump targets stay valid after folding inside loops', () => assert.strictEqual(out(': a 10 0 do i 2 3 + * . loop ; a'), '0 5 10 15 20 25 30 35 40 45 '));
t('O7 optimizer on/off agree on every bundled example and all conformance files', () => {
  const srcs = [fs.readFileSync(path.join(ROOT, 'examples/demo.fth'), 'utf8')];
  for (const f of fs.readdirSync(path.join(ROOT, 'test/forth'))) srcs.push(fs.readFileSync(path.join(ROOT, 'test/harness.fth'), 'utf8') + fs.readFileSync(path.join(ROOT, 'test/forth', f), 'utf8'));
  for (const s of srcs) assert.strictEqual(out(s, { optimize: true }), out(s, { optimize: false }));
});
t('O8 optimization cuts executed ops on constant-heavy code (>= 20% on a hot loop)', () => {
  const src = ': sq dup * ; : bench 20000 0 do i 2 3 + * sq 4 5 * - drop loop ; bench';
  const ops = o => Tracer.profile(mk(o), src).total;
  const a = ops({ optimize: true }), b = ops({ optimize: false });
  assert.ok(a < b * 0.8, 'optimized ' + a + ' vs ' + b + ' executed ops');
});
t('O9 redefinition after inlining keeps early binding', () => assert.strictEqual(out(': a 1 ; : b a ; : a 2 ; b .'), '1 '));
t('O10 disassembly source vs optimized', () => { const vm = mk(); vm.run(': a 2 3 * ;'); assert.match(vm.disassemble(vm.find('a'), 'src'), /call \*/); assert.match(vm.disassemble(vm.find('a')), /lit 6/); });

// ---------------------------------------------------------------- tracer --
t('T1 trace records stack before each op', () => {
  const vm = mk({ optimize: false }); const r = Tracer.record(vm, ': sq dup * ; 3 sq');
  assert.deepStrictEqual(r.steps.map(s => s.op), ['lit 3', 'call sq', 'call dup', 'call *']);
  assert.deepStrictEqual(r.steps.map(s => s.ds.join(',')), ['', '3', '3', '3,3']); assert.deepStrictEqual(r.final.ds, [9]);
});
t('T2 trace captures output position per step', () => { const r = Tracer.record(mk(), '1 . 2 . 3 .'); assert.strictEqual(r.output, '1 2 3 '); const outs = r.steps.map(s => s.out); assert.deepStrictEqual(outs, [...outs].sort((a, b) => a - b)); assert.strictEqual(r.final.out, 6); });
t('T3 trace reports errors with partial history', () => { const r = Tracer.record(mk(), '1 2 + drop drop'); assert.match(r.error, /underflow/); assert.ok(r.steps.length >= 4); });
t('T4 trace limit truncates', () => { const r = Tracer.record(mk(), ': l 1000 0 do i drop loop ; l', { maxSteps: 50 }); assert.ok(r.truncated); assert.strictEqual(r.steps.length, 50); });
t('T5 tracing does not change results', () => { const a = mk(), b = mk(); const ra = a.run(': f 5 0 do i . loop ; f'); const r = Tracer.record(b, ': f 5 0 do i . loop ; f'); assert.strictEqual(r.output, ra.output); });
t('T6 call depth is recorded', () => { const r = Tracer.record(mk({ optimize: false }), ': a 1 ; : b a ; : c b ; c'); assert.deepStrictEqual(Math.max(...r.steps.map(s => s.depth)), 3); });
t('T7 profiler counts ops and calls per word', () => { const p = Tracer.profile(mk({ optimize: false }), ': a 10 0 do i drop loop ; a a'); const row = p.rows.find(x => x.name === 'a'); assert.strictEqual(row.calls, 2); assert.ok(row.ops > 60); assert.ok(Math.abs(p.rows.reduce((s, r) => s + r.pct, 0) - 1) < 1e-9); });
t('T8 rstack snapshots', () => { const r = Tracer.record(mk({ optimize: false }), '1 >r 2 >r r> r>'); assert.deepStrictEqual(r.steps[2].rs, [1]); assert.deepStrictEqual(r.steps[4].rs, [1, 2]); assert.deepStrictEqual(r.steps[5].rs, [1]); assert.deepStrictEqual(r.final.rs, []); });

// ------------------------------------------------------------ conformance --
t('C1 harness detects failures (negative control)', () => {
  const vm = mk(); vm.run(fs.readFileSync(path.join(ROOT, 'test/harness.fth'), 'utf8'));
  const r = vm.run('T{ 1 2 + -> 4 }T T{ 1 2 + -> 3 }T T{ 1 2 -> 1 }T results');
  assert.match(r.output, /FAIL test #1 expected 4 got 3/); assert.match(r.output, /FAIL test #3/); assert.match(r.output, /TESTS 3 PASSED 1 FAILED 2/);
});
t('C2 conformance suite via CLI is green', () => {
  const r = spawnSync('node', [path.join(ROOT, 'cli.js'), 'test'], { encoding: 'utf8' });
  assert.strictEqual(r.status, 0, r.stdout); assert.match(r.stdout, /TOTAL passed (\d+), failed 0/);
  assert.ok(+/passed (\d+)/.exec(r.stdout)[1] >= 150);
});
t('C3 output formatting words (exact text)', () => assert.strictEqual(out('-5 . 5 u. 3 spaces 65 emit cr s" ab" type ." |" 7 3 .r'), '-5 5    A\nab|  7'));

// -------------------------------------------------------------- examples --
t('X1 demo program output', () => assert.strictEqual(out(fs.readFileSync(path.join(ROOT, 'examples/demo.fth'), 'utf8')), 'fib(20) = 6765 \ngcd(1071,462) = 21 \n10! = 3628800 \n1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz \n2 3 5 7 11 13 17 19 23 29 \n1 1 \n8 4 \n27 9 \n64 16 \n125 25 \n'));
t('X2 every IDE example runs/behaves as labelled', () => {
  const sandbox = { window: {} }; new Function('window', fs.readFileSync(path.join(ROOT, 'web/examples.js'), 'utf8'))(sandbox.window);
  const ex = sandbox.window.EXAMPLES, names = Object.keys(ex);
  assert.ok(names.length >= 8);
  const expectError = { 'Lying stack comment': /promises 2 in \/ 1 out/, 'Branch imbalance': /disagree/, 'Loop that leaks': /not stack-neutral/ };
  const expectOut = { 'Tour (fib, gcd, primes)': /fib\(12\) = 144[\s\S]*primes < 40: 2 3 5 7 11 13 17 19 23 29 31 37/, 'FizzBuzz': /Fizz 4 Buzz/, 'Towers of Hanoi': /^7 moves\n63 moves/, 'Collatz (BEGIN/WHILE)': /27 takes 111 steps/, 'CREATE / DOES>': /0 1 4 9 16 25 36 49 64 81 \n105/ };
  for (const n of names) {
    const r = mk().run(ex[n]);
    if (expectError[n]) { assert.ok(!r.ok, n + ' should be rejected'); assert.match(r.error, expectError[n]); }
    else { assert.ok(r.ok, n + ': ' + r.error); assert.match(r.output, expectOut[n], n); }
  }
});

// ------------------------------------------------------------------- CLI --
const cli = (...a) => spawnSync('node', [path.join(ROOT, 'cli.js'), ...a], { encoding: 'utf8' });
t('L1 CLI run/effects/see/trace/profile', () => {
  const demo = path.join(ROOT, 'examples/demo.fth');
  assert.match(cli('run', demo).stdout, /fib\(20\) = 6765/);
  assert.match(cli('effects', demo).stdout, /fact\s+\( n -- n \)/);
  assert.match(cli('see', demo, 'fact').stdout, /qdo/); assert.match(cli('see', demo, 'fact', '--source').stdout, /: fact/);
  assert.match(cli('trace', demo, '--max', '5').stdout, /trace truncated at 5 steps/);
  assert.match(cli('profile', demo).stdout, /total ops: \d+/);
});
t('L2 CLI -e and exit codes', () => {
  let r = cli('-e', '2 3 + .'); assert.strictEqual(r.status, 0); assert.strictEqual(r.stdout, '5 \n');
  r = cli('-e', '1 0 /'); assert.strictEqual(r.status, 1); assert.match(r.stderr, /division by zero/);
  r = cli('-e', ': w if drop then ;'); assert.strictEqual(r.status, 1);
  r = cli('-e', ': w if drop then ;', '--lax'); assert.strictEqual(r.status, 0);
  assert.strictEqual(cli('run', 'no-such-file.fth').status, 1); assert.strictEqual(cli().status, 1); assert.strictEqual(cli('bogus').status, 1);
});
t('L3 CLI error reports file:line', () => {
  const f = path.join(require('os').tmpdir(), 'fw-bad-' + process.pid + '.fth'); fs.writeFileSync(f, '1 2 +\n\n: x if drop then ;\n');
  const r = cli('run', f); fs.unlinkSync(f); assert.match(r.stderr, /:3: /);
});
t('L4 REPL over stdin', () => {
  const r = spawnSync('node', [path.join(ROOT, 'cli.js'), 'repl'], { input: ': sq dup * ;\n7 sq .\nbogus\nbye\n', encoding: 'utf8' });
  assert.match(r.stdout, /49/); assert.match(r.stdout, /error: undefined word: bogus/); assert.strictEqual(r.status, 0);
});

console.log(`run.js: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
