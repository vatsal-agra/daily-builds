// Conflux CDCL solver — JavaScript mirror of conflux/solver.py.
// Faithful port: two-watched literals, VSIDS, 1-UIP analysis with recursive
// minimization, non-chronological backjumping, Luby restarts, phase saving.
// Optionally records a step trace for the visualizer.
//
// Runs both in the browser (attaches to window.Conflux) and under Node
// (module.exports) so the same code is checked for Python<->JS parity.
(function (root) {
  "use strict";

  function luby(i) {
    let k = 1;
    while (true) {
      if (i === (1 << k) - 1) return 1 << (k - 1);
      if ((1 << (k - 1)) <= i && i < (1 << k) - 1) return luby(i - (1 << (k - 1)) + 1);
      k += 1;
    }
  }

  // Minimal binary heap of {act, v} keyed by (-act, v) to mirror Python heapq
  // on tuples (-activity, var): higher activity first, lower var breaks ties.
  class Heap {
    constructor() { this.a = []; }
    get size() { return this.a.length; }
    _less(x, y) { // returns true if x should be above y
      if (x.act !== y.act) return x.act > y.act;
      return x.v < y.v;
    }
    push(item) {
      const a = this.a; a.push(item);
      let i = a.length - 1;
      while (i > 0) {
        const p = (i - 1) >> 1;
        if (this._less(a[i], a[p])) { [a[i], a[p]] = [a[p], a[i]]; i = p; }
        else break;
      }
    }
    pop() {
      const a = this.a; if (a.length === 0) return null;
      const top = a[0], last = a.pop();
      if (a.length) {
        a[0] = last; let i = 0;
        while (true) {
          let l = 2 * i + 1, r = 2 * i + 2, m = i;
          if (l < a.length && this._less(a[l], a[m])) m = l;
          if (r < a.length && this._less(a[r], a[m])) m = r;
          if (m === i) break;
          [a[i], a[m]] = [a[m], a[i]]; i = m;
        }
      }
      return top;
    }
  }

  class Solver {
    constructor(numVars, opts) {
      opts = opts || {};
      this.numVars = numVars;
      this.val = new Array(numVars + 1).fill(null);
      this.level = new Array(numVars + 1).fill(-1);
      this.reason = new Array(numVars + 1).fill(null);
      this.phase = new Array(numVars + 1).fill(false);

      this.clauses = [];
      this.isLearnt = [];
      this.numOriginal = 0;
      this.watches = new Map();

      this.trail = [];
      this.trailLim = [];
      this.qhead = 0;

      this.activity = new Array(numVars + 1).fill(0);
      this.varInc = 1.0;
      this.varDecay = opts.varDecay || 0.95;
      this.heap = new Heap();

      this.ok = true;
      this.restartBase = opts.restartBase || 100;
      this.stats = { decisions: 0, propagations: 0, conflicts: 0, learned: 0,
                     restarts: 0, maxLevel: 0 };

      this.recordTrace = !!opts.recordTrace;
      this.trace = [];
      this.maxTrace = opts.maxTrace || 200000;
    }

    _emit(ev) { if (this.recordTrace && this.trace.length < this.maxTrace) this.trace.push(ev); }

    _w(lit) {
      let l = this.watches.get(lit);
      if (!l) { l = []; this.watches.set(lit, l); }
      return l;
    }
    litVal(lit) {
      const v = this.val[Math.abs(lit)];
      if (v === null) return null;
      return lit > 0 ? v : !v;
    }
    litTrue(lit) { return this.litVal(lit) === true; }
    litFalse(lit) { return this.litVal(lit) === false; }
    decisionLevel() { return this.trailLim.length; }

    addClause(lits) {
      if (!this.ok) return false;
      const seen = new Set(), cl = [];
      for (let l of lits) {
        l = l | 0;
        if (l === 0) throw new Error("0 is not a literal");
        if (seen.has(-l)) return true; // tautology
        if (seen.has(l)) continue;
        seen.add(l); cl.push(l);
      }
      if (cl.length === 0) { this.ok = false; return false; }
      if (cl.length === 1) return this._enqueueInitial(cl[0]);
      const cref = this.clauses.length;
      this.clauses.push(cl); this.isLearnt.push(false); this.numOriginal++;
      this._w(cl[0]).push(cref); this._w(cl[1]).push(cref);
      return true;
    }
    _enqueueInitial(lit) {
      const v = this.litVal(lit);
      if (v === true) return true;
      if (v === false) { this.ok = false; return false; }
      this._enqueue(lit, null); return true;
    }
    _addLearnt(lits) {
      const cref = this.clauses.length;
      this.clauses.push(lits); this.isLearnt.push(true);
      if (lits.length >= 2) { this._w(lits[0]).push(cref); this._w(lits[1]).push(cref); }
      return cref;
    }
    _enqueue(lit, reason) {
      const v = Math.abs(lit);
      this.val[v] = lit > 0;
      this.level[v] = this.decisionLevel();
      this.reason[v] = reason;
      this.trail.push(lit);
    }
    _newDecisionLevel() { this.trailLim.push(this.trail.length); }

    _backtrackTo(level) {
      if (this.decisionLevel() <= level) return;
      const target = this.trailLim[level];
      for (let k = this.trail.length - 1; k >= target; k--) {
        const v = Math.abs(this.trail[k]);
        this.phase[v] = this.val[v];
        this.val[v] = null; this.reason[v] = null; this.level[v] = -1;
        this.heap.push({ act: this.activity[v], v: v });
      }
      this.trail.length = target;
      this.trailLim.length = level;
      if (this.qhead > this.trail.length) this.qhead = this.trail.length;
    }

    _bump(v) {
      this.activity[v] += this.varInc;
      if (this.activity[v] > 1e100) this._rescale();
      this.heap.push({ act: this.activity[v], v: v });
    }
    _rescale() {
      for (let v = 1; v <= this.numVars; v++) this.activity[v] *= 1e-100;
      this.varInc *= 1e-100;
      this.heap = new Heap();
      for (let v = 1; v <= this.numVars; v++)
        if (this.val[v] === null) this.heap.push({ act: this.activity[v], v: v });
    }
    _decay() { this.varInc /= this.varDecay; }

    _pickBranchVar() {
      while (this.heap.size) {
        const it = this.heap.pop();
        if (this.val[it.v] === null) return it.v;
      }
      let best = null, bestAct = -1;
      for (let v = 1; v <= this.numVars; v++)
        if (this.val[v] === null && this.activity[v] >= bestAct) { best = v; bestAct = this.activity[v]; }
      return best;
    }

    propagate() {
      while (this.qhead < this.trail.length) {
        const p = this.trail[this.qhead++];
        this.stats.propagations++;
        const neg = -p;
        const ws = this.watches.get(neg) || [];
        const newWs = [];
        let conflict = null, i = 0; const n = ws.length;
        while (i < n) {
          const cref = ws[i++]; const c = this.clauses[cref];
          if (c[0] === neg) { const t = c[0]; c[0] = c[1]; c[1] = t; }
          const first = c[0];
          if (first !== neg && this.litTrue(first)) { newWs.push(cref); continue; }
          let found = false;
          for (let k = 2; k < c.length; k++) {
            if (!this.litFalse(c[k])) { const t = c[1]; c[1] = c[k]; c[k] = t; this._w(c[1]).push(cref); found = true; break; }
          }
          if (found) continue;
          newWs.push(cref);
          if (this.litFalse(first)) {
            conflict = cref;
            while (i < n) newWs.push(ws[i++]);
            break;
          } else {
            this._enqueue(first, cref);
            this._emit({ t: "imply", lit: first, reason: c.slice(), level: this.decisionLevel() });
          }
        }
        this.watches.set(neg, newWs);
        if (conflict !== null) { this.qhead = this.trail.length; return conflict; }
      }
      return null;
    }

    analyze(confl) {
      const learnt = [0];
      const seen = new Array(this.numVars + 1).fill(false);
      let pathCount = 0, p = 0, index = this.trail.length - 1;
      const curLevel = this.decisionLevel();
      let lits = this.clauses[confl];
      while (true) {
        const start = p === 0 ? 0 : 1;
        for (let j = start; j < lits.length; j++) {
          const q = lits[j], v = Math.abs(q);
          if (!seen[v] && this.level[v] > 0) {
            seen[v] = true; this._bump(v);
            if (this.level[v] >= curLevel) pathCount++;
            else learnt.push(q);
          }
        }
        while (!seen[Math.abs(this.trail[index])]) index--;
        p = this.trail[index];
        seen[Math.abs(p)] = false;
        index--; pathCount--;
        if (pathCount <= 0) break;
        lits = this.clauses[this.reason[Math.abs(p)]];
      }
      learnt[0] = -p;
      const min = this._minimize(learnt);
      let bt;
      if (min.length === 1) bt = 0;
      else {
        let maxI = 1;
        for (let i = 2; i < min.length; i++)
          if (this.level[Math.abs(min[i])] > this.level[Math.abs(min[maxI])]) maxI = i;
        const t = min[1]; min[1] = min[maxI]; min[maxI] = t;
        bt = this.level[Math.abs(min[1])];
      }
      return { learnt: min, bt: bt, uip: -learnt[0] };
    }

    _minimize(learnt) {
      const mark = new Set(learnt.map(l => Math.abs(l)));
      const out = [learnt[0]];
      for (let i = 1; i < learnt.length; i++) {
        const l = learnt[i];
        if (this.reason[Math.abs(l)] === null) out.push(l);
        else if (!this._redundant(l, mark, 0)) out.push(l);
      }
      return out;
    }
    _redundant(lit, mark, depth) {
      const r = this.reason[Math.abs(lit)];
      if (r === null) return false;
      if (depth > 200) return false;
      for (const q of this.clauses[r]) {
        if (Math.abs(q) === Math.abs(lit)) continue;
        const v = Math.abs(q);
        if (this.level[v] === 0) continue;
        if (mark.has(v)) continue;
        if (this.reason[v] === null) return false;
        if (!this._redundant(q, mark, depth + 1)) return false;
      }
      return true;
    }

    solve(maxConflicts) {
      if (!this.ok) return "UNSAT";
      if (this.heap.size === 0) {
        for (let v = 1; v <= this.numVars; v++) this.heap.push({ act: this.activity[v], v: v });
      }
      if (this.propagate() !== null) { this.ok = false; return "UNSAT"; }
      let restartNo = 0;
      let untilRestart = this.restartBase * luby(restartNo + 1);
      let thisRun = 0;
      while (true) {
        const confl = this.propagate();
        if (confl !== null) {
          this.stats.conflicts++; thisRun++;
          if (maxConflicts && this.stats.conflicts > maxConflicts) return "UNKNOWN";
          this._emit({ t: "conflict", clause: this.clauses[confl].slice(),
                       level: this.decisionLevel(), graph: this._conflictGraph(confl) });
          if (this.decisionLevel() === 0) return "UNSAT";
          const { learnt, bt, uip } = this.analyze(confl);
          this.stats.learned++;
          this._emit({ t: "learn", clause: learnt.slice(), bt: bt, uip: uip });
          this._backtrackTo(bt);
          let acref = null;
          if (learnt.length === 1) this._enqueue(learnt[0], null);
          else { acref = this._addLearnt(learnt); this._enqueue(learnt[0], acref); }
          this._emit({ t: "backjump", to: bt, lit: learnt[0] });
          this._decay();
        } else {
          if (this.decisionLevel() > this.stats.maxLevel) this.stats.maxLevel = this.decisionLevel();
          if (thisRun >= untilRestart) {
            this.stats.restarts++; restartNo++; thisRun = 0;
            untilRestart = this.restartBase * luby(restartNo + 1);
            this._backtrackTo(0);
            this._emit({ t: "restart" });
            continue;
          }
          const v = this._pickBranchVar();
          if (v === null) return "SAT";
          this.stats.decisions++;
          this._newDecisionLevel();
          const lit = this.phase[v] ? v : -v;
          this._enqueue(lit, null);
          this._emit({ t: "decide", lit: lit, level: this.decisionLevel() });
        }
      }
    }

    // snapshot the implication-graph cone feeding a conflict (for the viz)
    _conflictGraph(confl) {
      const nodes = {}, edges = [];
      const addNode = (lit) => {
        const v = Math.abs(lit);
        if (!(v in nodes)) nodes[v] = { lit: this.val[v] ? v : -v, level: this.level[v],
                                        decision: this.reason[v] === null };
      };
      const queue = [];
      for (const l of this.clauses[confl]) { addNode(l); queue.push(Math.abs(l)); edges.push({ from: -l, to: "K" }); }
      const visited = new Set();
      while (queue.length) {
        const v = queue.shift();
        if (visited.has(v)) continue; visited.add(v);
        const r = this.reason[v];
        if (r === null) continue;
        const implied = this.clauses[r][0];
        for (const q of this.clauses[r]) {
          if (Math.abs(q) === v) continue;
          addNode(q); edges.push({ from: -q, to: implied }); queue.push(Math.abs(q));
        }
      }
      return { nodes: Object.values(nodes), edges: edges, conflictClause: this.clauses[confl].slice() };
    }

    model() {
      const m = {};
      for (let v = 1; v <= this.numVars; v++) m[v] = this.val[v] === null ? false : this.val[v];
      return m;
    }
  }

  function isSatisfied(numVars, clauses, model) {
    for (const cl of clauses) {
      let ok = false;
      for (const l of cl) { if (model[Math.abs(l)] === (l > 0)) { ok = true; break; } }
      if (!ok) return false;
    }
    return true;
  }

  function solveCNF(numVars, clauses, opts) {
    const s = new Solver(numVars, opts);
    for (const cl of clauses) if (!s.addClause(cl)) break;
    const res = s.solve(opts && opts.maxConflicts);
    return { result: res, model: res === "SAT" ? s.model() : null, solver: s };
  }

  const api = { Solver, solveCNF, isSatisfied, luby };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Conflux = api;
})(typeof window !== "undefined" ? window : globalThis);
