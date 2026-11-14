/* Recording tracer (time-travel debugging) and profiler built on the VM's per-op hook. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./forth.js'));
  else root.Forthwright = Object.assign(root.Forthwright || {}, { Tracer: factory(root.Forthwright.Forth) });
})(typeof self !== 'undefined' ? self : this, function (Forth) {
  'use strict';
  const { ForthError } = Forth;

  class TraceLimit extends Error {}

  function wordOf(f) { return f ? f.word.name : '(top)'; }

  /** Run `source` on `vm` recording the machine state before every executed op.
   *  Returns {steps:[{word,op,line,ds,rs,depth,out}], output, error, truncated, final}. */
  function record(vm, source, opts = {}) {
    const max = opts.maxSteps || 20000;
    const steps = [];
    const saveHook = vm.hook, saveOut = vm.onOutput;
    vm.onOutput = null; vm.takeOutput();
    let truncated = false, error = null, errLine = null, atStop = null;
    vm.hook = (v, f, op) => {
      if (steps.length >= max) { truncated = true; atStop = { ds: v.ds.slice(), rs: v.rs.slice(), out: v.out.length }; throw new TraceLimit(); }
      steps.push({ word: wordOf(f), op: v.opText(op), line: op.line || null, ds: v.ds.slice(), rs: v.rs.slice(),
        depth: v.frames.length, out: v.out.length });
    };
    try { vm.evaluate(source); }
    catch (e) {
      if (e instanceof TraceLimit) { vm.reset(); }
      else if (e instanceof ForthError) { error = e.message; errLine = e.loc && e.loc.line; }
      else throw e;
    } finally { vm.hook = saveHook; vm.onOutput = saveOut; }
    const output = vm.takeOutput();
    const final = atStop ? { ds: atStop.ds, rs: atStop.rs, out: Math.min(atStop.out, output.length) } : { ds: vm.ds.slice(), rs: vm.rs.slice(), out: output.length };
    // clamp output offsets (output was drained)
    for (const s of steps) if (s.out > output.length) s.out = output.length;
    return { steps, output, error, errLine, truncated, final };
  }

  /** Execute `source` counting ops per word and calls per word. */
  function profile(vm, source) {
    const ops = new Map(), calls = new Map();
    const saveHook = vm.hook, saveOut = vm.onOutput;
    vm.onOutput = null; vm.takeOutput();
    let total = 0, error = null;
    vm.hook = (v, f, op) => {
      total++;
      const n = wordOf(f); ops.set(n, (ops.get(n) || 0) + 1);
      if (op.op === 'call' && op.a.kind === 'colon') calls.set(op.a.name, (calls.get(op.a.name) || 0) + 1);
    };
    try { vm.evaluate(source); }
    catch (e) { if (e instanceof ForthError) error = e.message; else throw e; }
    finally { vm.hook = saveHook; vm.onOutput = saveOut; }
    const output = vm.takeOutput();
    const rows = [...ops.entries()].map(([name, n]) => ({ name, ops: n, calls: calls.get(name) || 0, pct: total ? n / total : 0 }))
      .sort((a, b) => b.ops - a.ops);
    return { total, rows, output, error };
  }

  return { record, profile };
});
