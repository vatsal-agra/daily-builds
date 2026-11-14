/* Static stack-effect inference by abstract interpretation over a word's IR.
 * State at each op = (data depth relative to word entry, return-stack depth).
 * A worklist walks every path; paths that meet at one op must agree, otherwise
 * the word is rejected (IF/ELSE mismatch, loop body that grows/shrinks the stack, ...).
 * Result: {in, out} = items consumed from / left on the caller's stack. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./forth.js'));
  else root.Forthwright = Object.assign(root.Forthwright || {}, { Analyzer: factory(root.Forthwright.Forth) });
})(typeof self !== 'undefined' ? self : this, function (Forth) {
  'use strict';
  const O = Forth.O;

  function show(e) { return '( ' + (e.text || Forth.effNames(e)) + ' )'; }
  const plural = (n, s) => n + ' ' + s + (n === 1 ? '' : 's');

  /** effect of calling word w from inside `self`; returns {in,out,rd,rneed} or null if unknown */
  function calleeEffect(w, self) {
    if (w === self) return self.declared || null;
    if (w.kind === 'create' && w.doesCode) return null;
    if (w.kind === 'prim' && w.pickLike) return null;
    return w.eff || null;
  }

  function analyzeWord(w, vm) {
    const code = w.code, n = code.length;
    const targets = new Set();
    for (const op of code) if (op.op !== O.LIT && op.op !== O.CALL && typeof op.a === 'number') targets.add(op.a);
    const depth = new Array(n + 1), rdepth = new Array(n + 1);
    const preds = new Array(n + 1);
    const stack = [[0, 0, 0, -1]];
    let min = 0, unknown = null;
    const exits = [];
    let error = null, errLine = null;
    const fail = (msg, op) => { if (!error) { error = msg; errLine = op && op.line || null; } };

    while (stack.length && !error && !unknown) {
      const [pc, d, r, from] = stack.pop();
      if (pc >= n) { exits.push([d, r, from]); continue; }
      if (depth[pc] !== undefined) {
        if (depth[pc] !== d || rdepth[pc] !== r) {
          const src = from >= 0 ? code[from] : null;
          const diff = d - depth[pc];
          const loopish = src && from >= pc && src.op !== O.LEAVE;
          if (rdepth[pc] !== r && depth[pc] === d) fail('return stack differs between paths (' + rdepth[pc] + ' vs ' + r + ' items on the R stack): unbalanced >R / R>', src || code[pc]);
          else if (loopish) fail('loop body is not stack-neutral: each iteration leaves ' + plural(Math.abs(diff), 'item') + (diff > 0 ? ' more' : ' fewer') + ' on the stack than it started with', src);
          else fail('branches disagree about the stack: the paths meeting here differ by ' + plural(Math.abs(diff), 'item') + ' (an IF/ELSE/CASE branch is not balanced)', src || code[pc]);
        }
        continue;
      }
      depth[pc] = d; rdepth[pc] = r;
      const op = code[pc];
      const next = (pc2, d2, r2) => stack.push([pc2, d2, r2 === undefined ? r : r2, pc]);
      const need = (k) => { if (d - k < min) min = d - k; };
      switch (op.op) {
        case O.LIT: next(pc + 1, d + 1); break;
        case O.JMP: next(op.a, d); break;
        case O.LEAVE: next(op.a, d); break;
        case O.EXIT: case O.DOES: exits.push([d, r, pc]); break;
        case O.JZ: need(1); next(pc + 1, d - 1); next(op.a, d - 1); break;
        case O.DO: need(2); next(pc + 1, d - 2); break;
        case O.QDO: need(2); next(pc + 1, d - 2); next(op.a, d - 2); break;
        case O.LOOP: next(pc + 1, d); next(op.a, d); break;
        case O.PLOOP: need(1); next(pc + 1, d - 1); next(op.a, d - 1); break;
        case O.CALL: {
          const cw = op.a;
          const prev = code[pc - 1];
          if (cw.kind === 'prim' && cw.pickLike && prev && prev.op === O.LIT && !targets.has(pc)) {
            const k = prev.a;
            if (k < 0) { fail(cw.name.toUpperCase() + ' with negative index ' + k, op); break; }
            need(k + 2); // k+1 items must sit below the literal that was just pushed
            next(pc + 1, cw.pickLike === 'pick' ? d : d - 1);
            break;
          }
          const e = calleeEffect(cw, w);
          if (!e) { unknown = cw === w ? 'recursive call without a declared ( -- ) effect' : cw.name.toUpperCase() + ' has no static effect'; break; }
          const rd = cw.rd || 0;
          if (cw.rneed && r < cw.rneed) { fail(cw.name.toUpperCase() + ' needs ' + cw.rneed + ' item(s) on the return stack but there are only ' + r + ' (missing >R?)', op); break; }
          if (cw.rd < 0 && r + rd < 0) { fail(cw.name.toUpperCase() + ' without a matching >R', op); break; }
          need(e.in);
          next(pc + 1, d - e.in + e.out, r + rd);
          break;
        }
        default: unknown = 'unknown op ' + op.op;
      }
    }
    if (error) return { error, line: errLine };
    if (unknown) {
      if (w.declared) return { eff: w.declared, note: 'declared ' + show(w.declared) + ' (not verifiable: ' + unknown + ')' };
      return { eff: null, note: unknown };
    }
    const dEnds = [...new Set(exits.map(x => x[0]))];
    if (dEnds.length > 1) return { error: 'paths out of the word disagree about the stack (' + dEnds.map(x => x - min).join(' vs ') + ' items left): an IF/ELSE branch or EXIT is unbalanced' };
    for (const x of exits) if (x[1] !== 0) return { error: 'return stack is not balanced at exit: ' + x[1] + ' item(s) still on it (>R without R>?)' };
    let eff;
    if (!exits.length) eff = { in: -min, out: 0, noReturn: true };
    else eff = { in: -min, out: dEnds[0] - min };
    if (w.declared) {
      const dc = w.declared;
      if (dc.in !== eff.in || dc.out !== eff.out)
        return { error: 'stack effect mismatch in ' + w.name.toUpperCase() + ': the comment ' + show(dc) + ' promises ' + dc.in + ' in / ' + dc.out + ' out, but the body actually takes ' + eff.in + ' and leaves ' + eff.out, line: w.line };
      eff.text = dc.text;
    }
    return { eff };
  }

  function analyzeAll(vm) {
    const rows = [];
    for (const w of vm.dict.values()) if (w.kind === 'colon') rows.push({ name: w.name, eff: w.eff, note: w.effNote, declared: w.declared });
    return rows;
  }

  return { analyzeWord, analyzeAll, show };
});
