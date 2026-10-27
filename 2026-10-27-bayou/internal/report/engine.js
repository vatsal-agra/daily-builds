// Bayou in-browser inference engine: factor algebra + variable elimination with
// barren-node pruning + d-separation reachability. Mirrors the Go implementation
// (log-scaled factors so long evidence chains cannot underflow).
(function (root) {
  'use strict';

  function Factor(vars, card, val, logScale) {
    this.vars = vars; this.card = card; this.val = val; this.logScale = logScale || 0;
  }
  Factor.prototype.strides = function () {
    const s = new Array(this.vars.length); let acc = 1;
    for (let i = this.vars.length - 1; i >= 0; i--) { s[i] = acc; acc *= this.card[i]; }
    return s;
  };
  Factor.prototype.has = function (v) { return this.vars.indexOf(v) >= 0; };
  Factor.prototype.impossible = function () { return this.logScale === -Infinity; };

  function rescale(f) {
    let mx = 0;
    for (let i = 0; i < f.val.length; i++) if (f.val[i] > mx) mx = f.val[i];
    if (mx === 0) { f.logScale = -Infinity; return f; }
    if (mx !== 1) { for (let i = 0; i < f.val.length; i++) f.val[i] /= mx; f.logScale += Math.log(mx); }
    return f;
  }

  function product(a, b) {
    if (a.impossible() || b.impossible()) {
      // keep a well-formed (all-zero) table over the union scope
    }
    const vars = [], card = [];
    let i = 0, j = 0;
    while (i < a.vars.length || j < b.vars.length) {
      if (j >= b.vars.length || (i < a.vars.length && a.vars[i] < b.vars[j])) { vars.push(a.vars[i]); card.push(a.card[i]); i++; }
      else if (i >= a.vars.length || b.vars[j] < a.vars[i]) { vars.push(b.vars[j]); card.push(b.card[j]); j++; }
      else { vars.push(a.vars[i]); card.push(a.card[i]); i++; j++; }
    }
    let n = 1; for (const c of card) n *= c;
    const val = new Float64Array(n);
    const ast = a.strides(), bst = b.strides();
    const sa = vars.map(v => { const p = a.vars.indexOf(v); return p < 0 ? 0 : ast[p]; });
    const sb = vars.map(v => { const p = b.vars.indexOf(v); return p < 0 ? 0 : bst[p]; });
    const cnt = new Array(vars.length).fill(0);
    let ia = 0, ib = 0;
    for (let r = 0; r < n; r++) {
      val[r] = a.val[ia] * b.val[ib];
      for (let k = vars.length - 1; k >= 0; k--) {
        cnt[k]++; ia += sa[k]; ib += sb[k];
        if (cnt[k] < card[k]) break;
        ia -= sa[k] * card[k]; ib -= sb[k] * card[k]; cnt[k] = 0;
      }
    }
    const out = new Factor(vars, card, val, a.logScale + b.logScale);
    if (a.impossible() || b.impossible()) { out.logScale = -Infinity; val.fill(0); return out; }
    return rescale(out);
  }

  function sumOut(f, v) {
    const p = f.vars.indexOf(v);
    if (p < 0) return f;
    const vars = f.vars.filter((_, k) => k !== p), card = f.card.filter((_, k) => k !== p);
    let inner = 1; for (let k = p + 1; k < f.card.length; k++) inner *= f.card[k];
    let outer = 1; for (let k = 0; k < p; k++) outer *= f.card[k];
    const cv = f.card[p];
    const val = new Float64Array(outer * inner);
    for (let o = 0; o < outer; o++) for (let s = 0; s < cv; s++) for (let q = 0; q < inner; q++)
      val[o * inner + q] += f.val[(o * cv + s) * inner + q];
    const out = new Factor(vars, card, val, f.logScale);
    return f.impossible() ? out : rescale(out);
  }

  function reduce(f, v, state) {
    const p = f.vars.indexOf(v);
    if (p < 0) return f;
    const vars = f.vars.filter((_, k) => k !== p), card = f.card.filter((_, k) => k !== p);
    let inner = 1; for (let k = p + 1; k < f.card.length; k++) inner *= f.card[k];
    let outer = 1; for (let k = 0; k < p; k++) outer *= f.card[k];
    const cv = f.card[p];
    const val = new Float64Array(outer * inner);
    for (let o = 0; o < outer; o++) for (let q = 0; q < inner; q++) val[o * inner + q] = f.val[(o * cv + state) * inner + q];
    const out = new Factor(vars, card, val, f.logScale);
    return f.impossible() ? out : rescale(out);
  }

  // CPT factor of variable v: scope {v} ∪ parents (sorted); CPT layout: parents slowest, child fastest.
  function cptFactor(net, v) {
    const x = net.vars[v];
    const order = x.parents.concat([v]);
    const sorted = order.slice().sort((a, b) => a - b);
    const card = sorted.map(u => net.vars[u].states.length);
    const sst = new Array(sorted.length); let acc = 1;
    for (let i = sorted.length - 1; i >= 0; i--) { sst[i] = acc; acc *= card[i]; }
    const val = new Float64Array(acc);
    const ocard = order.map(u => net.vars[u].states.length);
    const cnt = new Array(order.length).fill(0);
    for (let idx = 0; idx < x.cpt.length; idx++) {
      let t = 0;
      for (let i = 0; i < order.length; i++) t += cnt[i] * sst[sorted.indexOf(order[i])];
      val[t] = x.cpt[idx];
      for (let k = order.length - 1; k >= 0; k--) { cnt[k]++; if (cnt[k] < ocard[k]) break; cnt[k] = 0; }
    }
    return rescale(new Factor(sorted, card, val, 0));
  }

  function ancestors(net, roots) {
    const seen = new Set(); const stack = roots.slice();
    while (stack.length) {
      const v = stack.pop();
      if (seen.has(v)) continue;
      seen.add(v);
      for (const p of net.vars[v].parents) stack.push(p);
    }
    return seen;
  }

  // Posterior over `query` (array of var ids) given evidence {id: state}.
  // Returns {probs: Float64Array over sorted query vars, vars, logEvidence} or null if impossible.
  function posterior(net, query, evidence) {
    const evIds = Object.keys(evidence).map(Number);
    const rel = ancestors(net, query.concat(evIds));
    let fs = [];
    for (const v of Array.from(rel).sort((a, b) => a - b)) {
      let f = cptFactor(net, v);
      for (const e of evIds) if (f.has(e)) f = reduce(f, e, evidence[e]);
      fs.push(f);
    }
    const qset = new Set(query);
    const todo = new Set(Array.from(rel).filter(v => !(v in evidence) && !qset.has(v)));
    while (todo.size) {
      let best = -1, bf = 0, bw = 0;
      for (const v of Array.from(todo).sort((a, b) => a - b)) {
        const nb = new Set();
        for (const f of fs) if (f.has(v)) for (const u of f.vars) if (u !== v) nb.add(u);
        const list = Array.from(nb);
        let fill = 0;
        for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
          if (!fs.some(f => f.has(list[i]) && f.has(list[j]))) fill++;
        }
        let w = net.vars[v].states.length;
        for (const u of list) w *= net.vars[u].states.length;
        if (best < 0 || fill < bf || (fill === bf && w < bw)) { best = v; bf = fill; bw = w; }
      }
      const inn = fs.filter(f => f.has(best)), out = fs.filter(f => !f.has(best));
      let prod = inn[0];
      for (let i = 1; i < inn.length; i++) prod = product(prod, inn[i]);
      out.push(sumOut(prod, best));
      fs = out; todo.delete(best);
    }
    let joint = fs[0];
    for (let i = 1; i < fs.length; i++) joint = product(joint, fs[i]);
    let total = 0; for (const x of joint.val) total += x;
    if (joint.impossible() || total === 0) return null;
    const probs = new Float64Array(joint.val.length);
    for (let i = 0; i < probs.length; i++) probs[i] = joint.val[i] / total;
    return { probs, vars: joint.vars, logEvidence: Math.log(total) + joint.logScale };
  }

  // All single-variable marginals (observed variables get a point mass) plus log P(e).
  function marginals(net, evidence) {
    const out = new Array(net.vars.length);
    let logPe = null;
    for (let v = 0; v < net.vars.length; v++) {
      if (v in evidence) {
        const p = new Array(net.vars[v].states.length).fill(0); p[evidence[v]] = 1; out[v] = p;
        continue;
      }
      const r = posterior(net, [v], evidence);
      if (!r) return null;
      out[v] = Array.from(r.probs);
      if (logPe === null) logPe = r.logEvidence;
    }
    if (logPe === null) { const r = posterior(net, [], evidence); if (!r) return null; logPe = r.logEvidence; }
    return { marginals: out, logEvidence: logPe };
  }

  // Variables d-connected to `start` given the observed set (Koller & Friedman Alg. 3.1).
  function dConnected(net, start, observed) {
    const obs = new Set(observed);
    const anc = ancestors(net, observed);
    const children = net.vars.map(() => []);
    net.vars.forEach((x, v) => x.parents.forEach(p => children[p].push(v)));
    const visited = new Set(), reach = new Set([start]);
    const queue = [[start, true]];
    while (queue.length) {
      const [v, up] = queue.shift();
      const key = v + (up ? 'u' : 'd');
      if (visited.has(key)) continue;
      visited.add(key);
      if (!obs.has(v)) reach.add(v);
      if (up) {
        if (!obs.has(v)) { for (const p of net.vars[v].parents) queue.push([p, true]); for (const c of children[v]) queue.push([c, false]); }
      } else {
        if (!obs.has(v)) for (const c of children[v]) queue.push([c, false]);
        if (anc.has(v)) for (const p of net.vars[v].parents) queue.push([p, true]);
      }
    }
    return reach;
  }

  const api = { posterior, marginals, dConnected, cptFactor };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.BayouEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
