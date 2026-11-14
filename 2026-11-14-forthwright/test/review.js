/* Regression tests: one per issue listed in REVIEW.md. */
const assert = require('assert');
const { create } = require('../src');
const Tracer = require('../src/tracer.js');
let n = 0;
const t = (name, fn) => { try { fn(); n++; console.log('  ok  ' + name); } catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); process.exitCode = 1; } };
const mk = o => create(Object.assign({ maxSteps: 3e6, maxOutput: 1e5 }, o));

t('R1 analyzer verdict identical with and without optimizer', () => {
  for (const src of [': w 6 if drop then ;', ': w 0 if 1 else 2 then ;', ': w 1 if 1 2 else 3 then ;']) {
    const a = mk({ optimize: true }).run(src), b = mk({ optimize: false }).run(src);
    assert.strictEqual(a.ok, b.ok, src);
  }
});
t('R2 redefining TYPE/OVER/=/DROP/@/! does not break ." CASE VALUE', () => {
  const vm = mk();
  const r = vm.run(': type 1 ; : over 2 ; : = 3 ; : drop 4 ; : @ 5 ; : ! 6 ; : g ." hi" ; g 7 value q 8 to q q . : c 2 case 2 of ." two" endof endcase ; c');
  assert.ok(r.ok, r.error); assert.strictEqual(r.output, 'hi8 two');
});
t('R3 runaway loops stop with a clear error (stack, output)', () => {
  let r = mk().run(': f no-check begin 1 again ; f'); assert.match(r.error, /stack overflow/);
  r = mk().run(': f begin 65 emit again ; f'); assert.match(r.error, /output limit/);
  r = mk({ maxSteps: 1000 }).run(': f begin again ; f'); assert.match(r.error, /step limit/);
});
t('R4 user-defined IMMEDIATE colon words run at compile time', () => {
  const vm = mk(); const r = vm.run(': kw ." [compiling] " ; immediate : t kw 5 ; t .');
  assert.ok(r.ok, r.error); assert.strictEqual(r.output, '[compiling] 5 ');
});
t('R5 "name" parse-time args and | alternatives in stack comments', () => {
  const vm = mk();
  assert.ok(vm.run(': array ( n "name" -- ) create cells allot does> ( i -- a ) swap cells + ; 3 array foo 7 1 foo ! 1 foo @ .').ok);
  assert.ok(vm.run(': q ( n -- n | 0 ) dup ;').ok);
});
t('R6 EXIT inside DO is rejected; UNLOOP EXIT accepted', () => {
  assert.match(mk().run(': t 3 0 do exit loop ;').error, /UNLOOP EXIT/);
  const vm = mk(); assert.ok(vm.run(': t 3 0 do i 1 = if unloop exit then loop ; t').ok);
});
t('R7 I / J outside loops are compile errors', () => {
  assert.match(mk().run(': t i ;').error, /outside a DO loop/);
  assert.match(mk().run(': t 2 0 do j loop ;').error, /two nested/);
  assert.ok(mk().run(': t 2 0 do 2 0 do j i + drop loop loop ;').ok);
});
t('R8 error message carries exactly one line number and sane wording', () => {
  const r = mk().run('\n\n: bad if drop then ;');
  assert.strictEqual(r.line, 3); assert.ok(!/\(line/.test(r.error), r.error);
  const m = mk().run(': l ( a b -- a ) over + swap ;'); assert.match(m.error, /promises 2 in \/ 1 out, but the body actually takes 2 and leaves 2/);
});
t('R9 truncated trace keeps the real stack at the stop point', () => {
  const vm = mk(); const tr = Tracer.record(vm, '1 2 3 4 5', { maxSteps: 3 });
  assert.ok(tr.truncated); assert.deepStrictEqual(tr.final.ds, [1, 2, 3]);
});
t('R10 words never leak loop parameters via LEAVE inside nested IF', () => {
  const vm = mk(); assert.ok(vm.run(': t 10 0 do i 3 = if leave then loop 99 ; t').ok); assert.deepStrictEqual(vm.ds, [99]); assert.strictEqual(vm.ls.length, 0);
});
console.log(n + ' regression checks passed');
