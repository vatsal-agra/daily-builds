/* IR optimizer: constant folding, peephole rewrites, dead-branch removal and inlining of
 * small straight-line words. Every rewrite keeps jump targets valid (windows never span a
 * jump target) and preserves early binding. Differentially tested against unoptimized runs. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./forth.js'));
  else root.Forthwright = Object.assign(root.Forthwright || {}, { Optimizer: factory(root.Forthwright.Forth) });
})(typeof self !== 'undefined' ? self : this, function (Forth) {
  'use strict';
  const O = Forth.O;
  const INLINE_MAX = 8;

  const isJump = op => op.op !== O.LIT && op.op !== O.CALL && typeof op.a === 'number';
  const lit = (v, like) => ({ op: O.LIT, a: v | 0, line: like && like.line });
  const isPrim = (op, name) => op.op === O.CALL && op.a.kind === 'prim' && op.a.name === name;
  const clone = (op, line) => Object.assign({}, op, { line: line || op.line });

  function inlinable(w) {
    if (w.inl !== undefined && w.inlCode === w.code) return w.inl;
    let ok = Array.isArray(w.code) && w.code.length <= INLINE_MAX;
    if (ok) for (const op of w.code) {
      if (op.op !== O.LIT && op.op !== O.CALL) { ok = false; break; }
      if (op.op === O.CALL && (op.a === w || op.recurse)) { ok = false; break; }
    }
    w.inl = ok; w.inlCode = w.code;
    return ok;
  }

  function pass(code, vm) {
    const n = code.length;
    const targets = new Set();
    for (const op of code) if (isJump(op)) targets.add(op.a);
    const out = [], map = new Array(n + 1);
    let changed = false;
    const free = (i, len) => { for (let k = 1; k < len; k++) if (targets.has(i + k) || i + k >= n) return false; return i + len <= n; };
    const word = name => vm.find(name);
    let i = 0;
    while (i < n) {
      const op = code[i];
      map[i] = out.length;
      // CALL of constants / variables / small words
      if (op.op === O.CALL) {
        const w = op.a;
        if (w.kind === 'const') { out.push(lit(w.value, op)); changed = true; i++; continue; }
        if (w.kind === 'var') { out.push(lit(w.addr, op)); changed = true; i++; continue; }
        if (w.kind === 'prim' && w.constVal !== undefined) { out.push(lit(w.constVal, op)); changed = true; i++; continue; }
        if (w.kind === 'colon' && inlinable(w)) { for (const x of w.code) out.push(clone(x, op.line)); changed = true; i++; continue; }
      }
      // LIT LIT <pure binary>
      if (op.op === O.LIT && free(i, 3) && code[i + 1].op === O.LIT && code[i + 2].op === O.CALL
          && code[i + 2].a.kind === 'prim' && code[i + 2].a.pure && code[i + 2].a.eff.in === 2) {
        out.push(lit(code[i + 2].a.fold(op.a, code[i + 1].a), op)); changed = true; i += 3; continue;
      }
      if (op.op === O.LIT && free(i, 2)) {
        const nx = code[i + 1];
        if (nx.op === O.CALL && nx.a.kind === 'prim' && nx.a.pure && nx.a.eff.in === 1) {
          out.push(lit(nx.a.fold(op.a), op)); changed = true; i += 2; continue;
        }
        if (isPrim(nx, 'DROP')) { changed = true; i += 2; continue; }
        if (nx.op === O.JZ) {            // constant condition
          if (op.a === 0) out.push({ op: O.JMP, a: nx.a, line: nx.line });
          changed = true; i += 2; continue;
        }
      }
      // x LIT k <op>  ->  cheaper unary word
      if (op.op === O.LIT && free(i, 2) && code[i + 1].op === O.CALL && code[i + 1].a.kind === 'prim') {
        const nm = code[i + 1].a.name, k = op.a;
        const rep = (nm === '+' && k === 1) ? '1+' : (nm === '-' && k === 1) ? '1-' : (nm === '*' && k === 2) ? '2*' : (nm === '=' && k === 0) ? '0=' : null;
        if (rep && word(rep)) { out.push({ op: O.CALL, a: word(rep), line: op.line }); changed = true; i += 2; continue; }
      }
      if (isPrim(op, 'DUP') && free(i, 2) && isPrim(code[i + 1], 'DROP')) { changed = true; i += 2; continue; }
      if (isPrim(op, 'SWAP') && free(i, 2) && isPrim(code[i + 1], 'SWAP')) { changed = true; i += 2; continue; }
      if (isPrim(op, 'NEGATE') && free(i, 2) && isPrim(code[i + 1], 'NEGATE')) { changed = true; i += 2; continue; }
      if (op.op === O.JMP && op.a === i + 1) { changed = true; i++; continue; }
      out.push(op); i++;
    }
    map[n] = out.length;
    if (!changed) return { code, changed: false };
    // clone jump ops (shared with caller's array) and retarget
    const res = out.map(o => isJump(o) ? Object.assign({}, o, { a: map[o.a] }) : o);
    return { code: res, changed: true };
  }

  function optimize(code, vm) {
    let cur = code;
    for (let k = 0; k < 8; k++) {
      const r = pass(cur, vm);
      if (!r.changed) break;
      cur = r.code;
    }
    return cur;
  }

  return { optimize, inlinable };
});
