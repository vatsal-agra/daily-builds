/* Forthwright core: tokenizer / outer interpreter, IR compiler, VM, primitives.
 * UMD: works in Node (require) and in browsers (window.Forthwright). */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Forthwright = Object.assign(root.Forthwright || {}, { Forth: factory() });
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---- opcodes -----------------------------------------------------------
  const O = { LIT: 'lit', CALL: 'call', JMP: 'jmp', JZ: 'jz', DO: 'do', QDO: 'qdo',
    LOOP: 'loop', PLOOP: 'ploop', LEAVE: 'leave', EXIT: 'exit', DOES: 'does' };

  class ForthError extends Error {
    constructor(msg, loc) { super(msg); this.name = 'ForthError'; this.loc = loc || null; }
  }

  // ---- effect string "a b -- c" -> {in,out} ---------------------------------
  function parseEffect(text) {
    const orig = text;
    text = text.replace(/"[^"]*"/g, ' ');            // parse-time arguments ("name") are not stack items
    if (text.includes('|') || text.includes('...')) return null;   // alternatives / variadic: not checkable
    const parts = text.split('--');
    if (parts.length !== 2) return null;
    const cnt = s => s.trim() === '' ? 0 : s.trim().split(/\s+/).length;
    return { in: cnt(parts[0]), out: cnt(parts[1]), text: orig.trim() };
  }

  const MEM_SIZE = 1 << 18;
  const PAD = 512, BASE_ADDR = 16, HERE0 = 1024;

  class Forth {
    constructor(opts = {}) {
      this.opts = Object.assign({ optimize: true, maxSteps: 50000000, analyze: true, strict: true, maxOutput: 20000000, maxStack: 200000 }, opts);
      this.mem = new DataView(new ArrayBuffer(MEM_SIZE));
      this.bytes = new Uint8Array(this.mem.buffer);
      this.here = HERE0;
      this.dict = new Map();
      this.xts = [null];            // execution tokens: index -> word
      this.ds = []; this.rs = []; this.ls = []; this.frames = [];
      this.out = ''; this.onOutput = null;
      this.hook = null; this.steps = 0; this.outCount = 0;
      this.cur = null;              // current colon definition
      this.state = 0;               // 0 interpret, 1 compile
      this.lastCreated = null; this.latest = null;
      this.src = ''; this.pos = 0; this.line = 1;
      this.mem.setInt32(BASE_ADDR, 10, true);
      this.optimizer = null; this.analyzer = null;
      this._installPrims();
      this._installCompilers();
      this.coreWords = new Map(this.dict);   // immune to user redefinition
    }
    core(name) { return this.coreWords ? this.coreWords.get(name) : this.dict.get(name); }

    use(parts) { if (parts.analyzer) this.analyzer = parts.analyzer; if (parts.optimizer) this.optimizer = parts.optimizer; return this; }

    // ------------------------------------------------------------ output ---
    emit(s) {
      this.outCount += s.length;
      if (this.outCount > this.opts.maxOutput) throw new ForthError('output limit exceeded (' + this.opts.maxOutput + ' chars) - runaway loop?');
      if (this.onOutput) this.onOutput(s); else this.out += s;
    }
    takeOutput() { const o = this.out; this.out = ''; return o; }

    // ------------------------------------------------------------ memory ---
    chk(a, n) {
      if (a < 0 || a + n > MEM_SIZE || a !== (a | 0)) throw new ForthError('invalid memory address ' + a);
    }
    fetch(a) { this.chk(a, 4); return this.mem.getInt32(a, true); }
    store(a, v) { this.chk(a, 4); this.mem.setInt32(a, v | 0, true); }
    allot(n) {
      if (this.here + n > MEM_SIZE || this.here + n < HERE0) throw new ForthError('dictionary space exhausted');
      const a = this.here; this.here += n; return a;
    }
    getString(addr, len) {
      this.chk(addr, len);
      let s = ''; for (let i = 0; i < len; i++) s += String.fromCharCode(this.bytes[addr + i]);
      return s;
    }
    putString(s) {
      const a = this.allot(s.length);
      for (let i = 0; i < s.length; i++) this.bytes[a + i] = s.charCodeAt(i) & 255;
      return a;
    }
    get base() { return this.mem.getInt32(BASE_ADDR, true); }

    // ---------------------------------------------------------- dictionary --
    addWord(w) {
      w.id = this.xts.length; this.xts.push(w);
      this.dict.set(w.name.toUpperCase(), w);
      this.latest = w;
      return w;
    }
    find(name) { return this.dict.get(name.toUpperCase()); }
    def(name, effect, fn, extra) {
      const eff = effect === '?' ? null : parseEffect(effect);
      const w = { name, kind: 'prim', fn, eff, effText: effect, pops: eff ? eff.in : 0 };
      if (effect === '?') w.pops = 0;
      Object.assign(w, extra || {});
      return this.addWord(w);
    }

    // ------------------------------------------------------------ tokenizer -
    skipWs() {
      const s = this.src;
      while (this.pos < s.length && /\s/.test(s[this.pos])) { if (s[this.pos] === '\n') this.line++; this.pos++; }
    }
    token() {
      this.skipWs();
      const s = this.src; if (this.pos >= s.length) return null;
      const st = this.pos;
      while (this.pos < s.length && !/\s/.test(s[this.pos])) this.pos++;
      this.tokLine = this.line;
      return s.slice(st, this.pos);
    }
    parseUntil(delim) {            // parse until delimiter char, skipping one leading space
      const s = this.src;
      if (this.pos < s.length && s[this.pos] === ' ') this.pos++;
      const st = this.pos;
      while (this.pos < s.length && s[this.pos] !== delim) { if (s[this.pos] === '\n') this.line++; this.pos++; }
      if (this.pos >= s.length) throw new ForthError('missing closing ' + JSON.stringify(delim), this.loc());
      const r = s.slice(st, this.pos); this.pos++;
      return r;
    }
    loc() { return { line: this.tokLine || this.line }; }
    parseNumber(tok) {
      let base = this.base, t = tok, neg = false;
      if (t.length > 2 && t[0] === "'" && t[2] === "'" && t.length === 3) return t.charCodeAt(1);
      const pre = { '$': 16, '#': 10, '%': 2 };
      if (pre[t[0]] && t.length > 1) { base = pre[t[0]]; t = t.slice(1); }
      if (t[0] === '-') { neg = true; t = t.slice(1); }
      if (!t.length) return null;
      let v = 0;
      for (const ch of t.toLowerCase()) {
        const d = ch >= '0' && ch <= '9' ? ch.charCodeAt(0) - 48 : ch >= 'a' && ch <= 'z' ? ch.charCodeAt(0) - 87 : 99;
        if (d >= base) return null;
        v = (Math.imul(v, base) + d) | 0;
      }
      return neg ? (-v) | 0 : v;
    }

    // -------------------------------------------------------- outer interp --
    reset() { this.ds.length = 0; this.rs.length = 0; this.ls.length = 0; this.frames.length = 0; this.cur = null; this.state = 0; }

    evaluate(source) {
      const saveSrc = this.src, savePos = this.pos, saveLine = this.line;
      this.src = source; this.pos = 0; this.line = 1;
      try {
        let tok;
        while ((tok = this.token()) !== null) this.interpretToken(tok);
        if (this.cur && !this.cur.fromBracket) { /* unterminated definition stays open across evaluate calls */ }
      } catch (e) {
        if (e instanceof ForthError || e instanceof RangeError) {
          if (e instanceof RangeError) e = new ForthError('internal limit: ' + e.message);
          if (!e.loc) e.loc = { line: this.tokLine || this.line };
          this.reset();
          throw e;
        }
        throw e;
      } finally { this.src = saveSrc; this.pos = savePos; this.line = saveLine; }
    }

    /** evaluate and return {ok, error, output} without throwing */
    run(source) {
      try { this.evaluate(source); return { ok: true, output: this.takeOutput() }; }
      catch (e) {
        if (!(e instanceof ForthError)) throw e;
        return { ok: false, error: e.message, line: e.loc && e.loc.line, output: this.takeOutput() };
      }
    }

    interpretToken(tok) {
      const w = this.find(tok);
      if (w) {
        if (w.imm || (w.kind === 'prim' && w.compileOnly)) {
          if (w.compileOnly && !this.cur) throw new ForthError(tok.toUpperCase() + ' is compile-only', this.loc());
          if (w.kind === 'colon') return this.execute(w);
          return w.fn(this);
        }
        if (this.state && this.cur) {
          if (w.needLoop && this.cur.cs.filter(e => e.t === 'do').length < w.needLoop)
            throw new ForthError(w.name.toUpperCase() + ' used outside ' + (w.needLoop > 1 ? 'two nested DO loops' : 'a DO loop') + ' in ' + this.cur.name.toUpperCase(), this.loc());
          this.emitOp({ op: O.CALL, a: w }); return;
        }
        return this.execute(w);
      }
      const n = this.parseNumber(tok);
      if (n === null) throw new ForthError('undefined word: ' + tok, this.loc());
      if (this.state && this.cur) this.emitOp({ op: O.LIT, a: n });
      else { if (this.hook) this.hook(this, null, { op: O.LIT, a: n, line: this.tokLine }); this.ds.push(n); }
    }

    emitOp(op) { op.line = this.tokLine; this.cur.code.push(op); return this.cur.code.length - 1; }

    execute(w) {
      const base = this.frames.length;
      this.steps = 0; this.outCount = 0;
      if (this.hook) this.hook(this, null, { op: O.CALL, a: w, line: this.tokLine });
      this.invoke(w);
      this.loop(base);
    }

    invoke(w) {
      switch (w.kind) {
        case 'prim':
          if (this.ds.length < w.pops) throw new ForthError('stack underflow in ' + w.name.toUpperCase(), this.loc());
          w.fn(this); break;
        case 'colon':
          if (this.frames.length > 20000) throw new ForthError('call stack overflow (recursion too deep)');
          this.frames.push({ code: w.code, ip: 0, word: w }); break;
        case 'const': this.ds.push(w.value); break;
        case 'var': this.ds.push(w.addr); break;
        case 'create':
          this.ds.push(w.addr);
          if (w.doesCode) this.frames.push({ code: w.doesCode, ip: w.doesIp, word: w });
          break;
        default: throw new ForthError('cannot execute ' + w.name);
      }
    }

    // ---------------------------------------------------------- VM loop -----
    loop(base) {
      const ds = this.ds, frames = this.frames;
      const max = this.opts.maxSteps, maxStack = this.opts.maxStack;
      while (frames.length > base) {
        const f = frames[frames.length - 1];
        if (f.ip >= f.code.length) { frames.pop(); continue; }
        const op = f.code[f.ip++];
        if (this.hook) this.hook(this, f, op);
        if (++this.steps > max) throw new ForthError('step limit exceeded (' + max + ') - infinite loop?');
        switch (op.op) {
          case O.LIT: ds.push(op.a); break;
          case O.CALL: this.invoke(op.a); break;
          case O.JMP: f.ip = op.a; break;
          case O.JZ:
            if (ds.length < 1) throw new ForthError('stack underflow at IF/WHILE/UNTIL', { line: op.line });
            if (ds.pop() === 0) f.ip = op.a; break;
          case O.DO: {
            if (ds.length < 2) throw new ForthError('stack underflow at DO', { line: op.line });
            const i = ds.pop(), l = ds.pop(); this.ls.push(l, i); break;
          }
          case O.QDO: {
            if (ds.length < 2) throw new ForthError('stack underflow at ?DO', { line: op.line });
            const i = ds.pop(), l = ds.pop();
            if (i === l) f.ip = op.a; else this.ls.push(l, i);
            break;
          }
          case O.LOOP: case O.PLOOP: {
            let n = 1;
            if (op.op === O.PLOOP) {
              if (ds.length < 1) throw new ForthError('stack underflow at +LOOP', { line: op.line });
              n = ds.pop();
            }
            const ls = this.ls, k = ls.length;
            const old = (ls[k - 1] - ls[k - 2]) | 0, nw = (old + n) | 0;
            ls[k - 1] = (ls[k - 1] + n) | 0;
            if ((old >= 0) !== (nw >= 0)) ls.length = k - 2; else f.ip = op.a;
            break;
          }
          case O.LEAVE: this.ls.length -= 2; f.ip = op.a; break;
          case O.EXIT: frames.pop(); break;
          case O.DOES: {
            const c = this.lastCreated;
            if (!c) throw new ForthError('DOES> without CREATE');
            c.doesCode = f.code; c.doesIp = f.ip; frames.pop(); break;
          }
          default: throw new ForthError('bad opcode ' + op.op);
        }
        if (ds.length > maxStack || this.rs.length > maxStack || this.ls.length > maxStack)
          throw new ForthError('stack overflow (more than ' + maxStack + ' items) - runaway loop?');
      }
    }

    // ------------------------------------------------- compile-time helpers -
    cs() { return this.cur.cs; }
    needCs(type, what) {
      const cs = this.cs();
      const top = cs[cs.length - 1];
      if (!top || (Array.isArray(type) ? !type.includes(top.t) : top.t !== type))
        throw new ForthError(what + ' without matching ' + (Array.isArray(type) ? type.join('/') : type).toUpperCase(), this.loc());
      return cs.pop();
    }

    beginDef(name) {
      this.cur = { name, code: [], cs: [], declared: null, nocheck: false, w: null };
      this.state = 1;
    }

    finishDef() {
      const cur = this.cur;
      if (cur.cs.length) {
        const t = cur.cs[cur.cs.length - 1].t.toUpperCase();
        throw new ForthError('unterminated ' + t + ' in definition of ' + cur.name.toUpperCase(), this.loc());
      }
      const w = cur.w;
      w.code = cur.code;
      w.declared = cur.declared;
      w.eff = null; w.effNote = null;
      if (this.opts.analyze && this.analyzer && !cur.nocheck) {
        const r = this.analyzer.analyzeWord(w, this);
        if (r.error && this.opts.strict) {
          this.cur = null; this.state = 0;
          throw new ForthError(r.error, { line: r.line || this.tokLine });
        }
        w.eff = r.eff; w.effNote = r.note || r.error || null;
        if (r.error) w.warning = r.error;
      } else if (cur.nocheck) w.effNote = 'unchecked (NO-CHECK)';
      // analysis runs on the source IR so accept/reject never depends on the optimizer
      if (this.opts.optimize && this.optimizer) w.code = this.optimizer.optimize(w.code, this);
      this.cur = null; this.state = 0;
      this.addWord(w);
    }

    // ================================================== compiling words =====
    _installCompilers() {
      const imm = (name, fn, extra) => this.addWord(Object.assign({ name, kind: 'prim', imm: true, fn, eff: null, pops: 0 }, extra || {}));
      const co = (name, fn) => imm(name, fn, { compileOnly: true });
      const vm = this;

      imm(':', () => {
        if (vm.cur) throw new ForthError('nested definition (missing ;?)', vm.loc());
        const name = vm.token(); if (!name) throw new ForthError(': needs a name', vm.loc());
        vm.beginDef(name);
        vm.cur.w = { name, kind: 'colon', code: null, eff: null, line: vm.tokLine };
        vm.cur.declStart = vm.pos;
        vm.cur.expectDecl = true;
      });
      imm(';', () => {
        if (!vm.cur) throw new ForthError('; outside a definition', vm.loc());
        vm.finishDef();
      });
      imm('(', () => {
        const text = vm.parseUntil(')');
        if (vm.cur && vm.cur.expectDecl && vm.cur.code.length === 0 && /--/.test(text)) {
          const e = parseEffect(text);
          if (e) vm.cur.declared = e;
        }
        if (vm.cur) vm.cur.expectDecl = false;
      });
      imm('\\', () => {
        const s = vm.src; while (vm.pos < s.length && s[vm.pos] !== '\n') vm.pos++;
      });
      imm('NO-CHECK', () => { if (vm.cur) vm.cur.nocheck = true; });
      imm('IMMEDIATE', () => { if (vm.latest) vm.latest.imm = true; });

      // --- control flow ---
      co('IF', () => { const at = vm.emitOp({ op: O.JZ, a: -1 }); vm.cs().push({ t: 'if', at }); });
      co('ELSE', () => {
        const f = vm.needCs('if', 'ELSE');
        const at = vm.emitOp({ op: O.JMP, a: -1 });
        vm.cur.code[f.at].a = vm.cur.code.length;
        vm.cs().push({ t: 'else', at });
      });
      co('THEN', () => {
        const f = vm.needCs(['if', 'else'], 'THEN');
        vm.cur.code[f.at].a = vm.cur.code.length;
      });
      co('BEGIN', () => vm.cs().push({ t: 'begin', at: vm.cur.code.length }));
      co('UNTIL', () => { const f = vm.needCs('begin', 'UNTIL'); vm.emitOp({ op: O.JZ, a: f.at }); });
      co('AGAIN', () => { const f = vm.needCs('begin', 'AGAIN'); vm.emitOp({ op: O.JMP, a: f.at }); });
      co('WHILE', () => {
        const b = vm.needCs('begin', 'WHILE');
        const at = vm.emitOp({ op: O.JZ, a: -1 });
        vm.cs().push(b, { t: 'while', at });
      });
      co('REPEAT', () => {
        const w = vm.needCs('while', 'REPEAT');
        const b = vm.needCs('begin', 'REPEAT');
        vm.emitOp({ op: O.JMP, a: b.at });
        vm.cur.code[w.at].a = vm.cur.code.length;
      });
      const doLike = (opcode) => () => {
        const at = vm.emitOp({ op: opcode, a: -1 });
        vm.cs().push({ t: 'do', at, start: vm.cur.code.length, leaves: [] });
      };
      co('DO', doLike(O.DO)); co('?DO', doLike(O.QDO));
      const endLoop = (name, opcode) => () => {
        const d = vm.needCs('do', name);
        vm.emitOp({ op: opcode, a: d.start });
        const end = vm.cur.code.length;
        if (vm.cur.code[d.at].op === O.QDO) vm.cur.code[d.at].a = end;
        for (const l of d.leaves) vm.cur.code[l].a = end;
      };
      co('LOOP', endLoop('LOOP', O.LOOP)); co('+LOOP', endLoop('+LOOP', O.PLOOP));
      co('LEAVE', () => {
        const cs = vm.cs();
        for (let i = cs.length - 1; i >= 0; i--) if (cs[i].t === 'do') {
          cs[i].leaves.push(vm.emitOp({ op: O.LEAVE, a: -1 })); return;
        }
        throw new ForthError('LEAVE outside DO loop', vm.loc());
      });
      co('EXIT', () => {
        const inDo = vm.cs().some(e => e.t === 'do');
        const last = vm.cur.code[vm.cur.code.length - 1];
        if (inDo && !(last && last.op === O.CALL && last.a.name === 'UNLOOP'))
          throw new ForthError('EXIT inside a DO loop leaves loop parameters behind - write UNLOOP EXIT', vm.loc());
        vm.emitOp({ op: O.EXIT });
      });
      co('RECURSE', () => { vm.emitOp({ op: O.CALL, a: vm.cur.w, recurse: true }); });
      co('DOES>', () => { vm.emitOp({ op: O.DOES }); });
      // CASE .. OF .. ENDOF .. ENDCASE
      co('CASE', () => vm.cs().push({ t: 'case', ends: [] }));
      co('OF', () => {
        const c = vm.cs()[vm.cs().length - 1];
        if (!c || c.t !== 'case') throw new ForthError('OF without CASE', vm.loc());
        vm.emitOp({ op: O.CALL, a: vm.core('OVER') }); vm.emitOp({ op: O.CALL, a: vm.core('=') });
        const at = vm.emitOp({ op: O.JZ, a: -1 });
        vm.emitOp({ op: O.CALL, a: vm.core('DROP') });
        vm.cs().push({ t: 'of', at });
      });
      co('ENDOF', () => {
        const o = vm.needCs('of', 'ENDOF');
        const c = vm.cs()[vm.cs().length - 1];
        c.ends.push(vm.emitOp({ op: O.JMP, a: -1 }));
        vm.cur.code[o.at].a = vm.cur.code.length;
      });
      co('ENDCASE', () => {
        const c = vm.needCs('case', 'ENDCASE');
        vm.emitOp({ op: O.CALL, a: vm.core('DROP') });
        for (const e of c.ends) vm.cur.code[e].a = vm.cur.code.length;
      });

      // --- literals / state ---
      imm('[', () => { vm.state = 0; });
      imm(']', () => { if (!vm.cur) throw new ForthError('] outside definition', vm.loc()); vm.state = 1; });
      co('LITERAL', () => { vm.emitOp({ op: O.LIT, a: vm.pop1('LITERAL') }); });
      imm('[CHAR]', () => {
        const t = vm.token(); if (!t) throw new ForthError('[CHAR] needs a character', vm.loc());
        if (vm.cur && vm.state) vm.emitOp({ op: O.LIT, a: t.charCodeAt(0) }); else vm.ds.push(t.charCodeAt(0));
      });
      imm('CHAR', () => {
        const t = vm.token(); if (!t) throw new ForthError('CHAR needs a character', vm.loc());
        if (vm.cur && vm.state) vm.emitOp({ op: O.LIT, a: t.charCodeAt(0) }); else vm.ds.push(t.charCodeAt(0));
      });
      const xtOf = (name) => {
        const n = vm.token(); if (!n) throw new ForthError(name + ' needs a word name', vm.loc());
        const w = vm.find(n); if (!w) throw new ForthError('undefined word: ' + n, vm.loc());
        return w;
      };
      imm("'", () => { const w = xtOf("'"); if (vm.cur && vm.state) vm.emitOp({ op: O.LIT, a: w.id }); else vm.ds.push(w.id); });
      imm('[\']', () => { const w = xtOf("[']"); if (vm.cur && vm.state) vm.emitOp({ op: O.LIT, a: w.id }); else vm.ds.push(w.id); });

      // --- strings ---
      imm('."', () => {
        const s = vm.parseUntil('"');
        if (vm.cur && vm.state) {
          const a = vm.putString(s);
          vm.emitOp({ op: O.LIT, a }); vm.emitOp({ op: O.LIT, a: s.length }); vm.emitOp({ op: O.CALL, a: vm.core('TYPE') });
        } else vm.emit(s);
      });
      imm('.(', () => { vm.emit(vm.parseUntil(')')); });
      imm('S"', () => {
        const s = vm.parseUntil('"');
        if (vm.cur && vm.state) {
          const a = vm.putString(s);
          vm.emitOp({ op: O.LIT, a }); vm.emitOp({ op: O.LIT, a: s.length });
        } else {
          if (s.length > 255) throw new ForthError('S" string too long (255 max in interpret mode)');
          for (let i = 0; i < s.length; i++) vm.bytes[PAD + i] = s.charCodeAt(i) & 255;
          vm.ds.push(PAD, s.length);
        }
      });

      // --- defining words ---
      vm.def('VARIABLE', '--', () => {
        const name = vm.token(); if (!name) throw new ForthError('VARIABLE needs a name', vm.loc());
        const addr = vm.allot(4); vm.store(addr, 0);
        vm.addWord({ name, kind: 'var', addr, eff: { in: 0, out: 1 } });
      });
      vm.def('CONSTANT', 'a --', () => {
        const name = vm.token(); if (!name) throw new ForthError('CONSTANT needs a name', vm.loc());
        const value = vm.ds.pop();
        vm.addWord({ name, kind: 'const', value, eff: { in: 0, out: 1 } });
      });
      vm.def('VALUE', 'a --', () => {
        const name = vm.token(); if (!name) throw new ForthError('VALUE needs a name', vm.loc());
        const value = vm.ds.pop();
        const addr = vm.allot(4); vm.store(addr, value);
        vm.addWord({ name, kind: 'var', addr, isValue: true, eff: null, fetchOnCall: true });
        const w = vm.latest;
        // a VALUE pushes its contents: model as a colon word  addr @
        w.kind = 'colon'; w.code = [{ op: O.LIT, a: addr }, { op: O.CALL, a: vm.core('@') }];
        w.eff = { in: 0, out: 1 }; w.valueAddr = addr;
      });
      imm('TO', () => {
        const n = vm.token(); const w = n && vm.find(n);
        if (!w || w.valueAddr === undefined) throw new ForthError('TO needs a VALUE name' + (n ? ': ' + n : ''), vm.loc());
        if (vm.cur && vm.state) { vm.emitOp({ op: O.LIT, a: w.valueAddr }); vm.emitOp({ op: O.CALL, a: vm.core('!') }); }
        else vm.store(w.valueAddr, vm.pop1('TO'));
      });
      vm.def('CREATE', '--', () => {
        const name = vm.token(); if (!name) throw new ForthError('CREATE needs a name', vm.loc());
        const w = vm.addWord({ name, kind: 'create', addr: vm.here, eff: { in: 0, out: 1 } });
        vm.lastCreated = w;
      });
      imm('SEE', () => {
        const n = vm.token(); const w = n && vm.find(n);
        if (!w) throw new ForthError('SEE: undefined word ' + n, vm.loc());
        vm.emit(vm.disassemble(w));
      });
    }

    pop1(who) {
      if (!this.ds.length) throw new ForthError('stack underflow in ' + who, this.loc());
      return this.ds.pop();
    }

    // ---------------------------------------------------------- disassembler
    opText(op) {
      switch (op.op) {
        case O.LIT: return 'lit ' + op.a;
        case O.CALL: return 'call ' + op.a.name.toLowerCase();
        case O.JMP: case O.JZ: case O.DO: case O.QDO: case O.LOOP: case O.PLOOP: case O.LEAVE:
          return op.op + ' ->' + op.a;
        default: return op.op;
      }
    }
    disassemble(w) {
      if (w.kind !== 'colon') {
        const e = w.eff ? ' ( ' + (w.effText || w.eff.text || '') + ' )' : '';
        return ': ' + w.name + ' [' + w.kind + ']' + e + '\n';
      }
      const targets = new Set(w.code.filter(o => typeof o.a === 'number' && o.op !== O.LIT).map(o => o.a));
      let s = ': ' + w.name + '  ' + effectString(w) + '\n';
      w.code.forEach((op, i) => { s += (targets.has(i) ? ' >' : '  ') + String(i).padStart(3) + '  ' + this.opText(op) + '\n'; });
      if (targets.has(w.code.length)) s += ' >' + String(w.code.length).padStart(3) + '  (end)\n';
      return s + ';\n';
    }
  }

  function effectString(w) {
    if (w.eff) return '( ' + (w.eff.text || effNames(w.eff)) + ' )';
    return '( ? )' + (w.effNote ? '  \\ ' + w.effNote : '');
  }
  function effNames(e) {
    const n = (k, p) => Array.from({ length: k }, (_, i) => p + (k > 1 ? i + 1 : ''));
    return [...n(e.in, 'x'), '--', ...n(e.out, 'y')].join(' ');
  }

  // ==================================================================== PRIMS
  Forth.prototype._installPrims = function () {
    const vm = this;
    const d = (name, eff, fn, x) => vm.def(name, eff, fn, x);
    const u32 = x => x >>> 0;
    const bin = (name, f, x) => d(name, 'a b -- c', v => { const ds = v.ds, b = ds.pop(), a = ds.pop(); ds.push(f(a, b) | 0); }, Object.assign({ pure: true, fold: f }, x));
    const un = (name, f) => d(name, 'a -- b', v => { const ds = v.ds; ds.push(f(ds.pop()) | 0); }, { pure: true, fold: f });
    const B = x => x ? -1 : 0;
    const divz = b => { if (b === 0) throw new ForthError('division by zero'); };

    // stack
    d('DUP', 'a -- a a', v => { v.ds.push(v.ds[v.ds.length - 1]); });
    d('DROP', 'a --', v => { v.ds.pop(); });
    d('SWAP', 'a b -- b a', v => { const s = v.ds, n = s.length; const t = s[n - 1]; s[n - 1] = s[n - 2]; s[n - 2] = t; });
    d('OVER', 'a b -- a b a', v => { v.ds.push(v.ds[v.ds.length - 2]); });
    d('ROT', 'a b c -- b c a', v => { const s = v.ds, n = s.length; const a = s[n - 3]; s[n - 3] = s[n - 2]; s[n - 2] = s[n - 1]; s[n - 1] = a; });
    d('-ROT', 'a b c -- c a b', v => { const s = v.ds, n = s.length; const c = s[n - 1]; s[n - 1] = s[n - 2]; s[n - 2] = s[n - 3]; s[n - 3] = c; });
    d('NIP', 'a b -- b', v => { const s = v.ds; const b = s.pop(); s[s.length - 1] = b; });
    d('TUCK', 'a b -- b a b', v => { const s = v.ds; const b = s.pop(), a = s.pop(); s.push(b, a, b); });
    d('2DUP', 'a b -- a b a b', v => { const s = v.ds, n = s.length; s.push(s[n - 2], s[n - 1]); });
    d('2DROP', 'a b --', v => { v.ds.length -= 2; });
    d('2SWAP', 'a b c d -- c d a b', v => { const s = v.ds; const d_ = s.pop(), c = s.pop(), b = s.pop(), a = s.pop(); s.push(c, d_, a, b); });
    d('2OVER', 'a b c d -- a b c d a b', v => { const s = v.ds, n = s.length; s.push(s[n - 4], s[n - 3]); });
    d('?DUP', '?', v => { const s = v.ds; if (!s.length) throw new ForthError('stack underflow in ?DUP'); if (s[s.length - 1] !== 0) s.push(s[s.length - 1]); });
    d('DEPTH', '-- n', v => { v.ds.push(v.ds.length); });
    d('PICK', '?', v => {
      const s = v.ds; if (!s.length) throw new ForthError('stack underflow in PICK');
      const n = s.pop(); if (n < 0 || n >= s.length) throw new ForthError('PICK out of range');
      s.push(s[s.length - 1 - n]);
    }, { pickLike: 'pick' });
    d('ROLL', '?', v => {
      const s = v.ds; if (!s.length) throw new ForthError('stack underflow in ROLL');
      const n = s.pop(); if (n < 0 || n >= s.length) throw new ForthError('ROLL out of range');
      const x = s.splice(s.length - 1 - n, 1)[0]; s.push(x);
    }, { pickLike: 'roll' });
    d('>R', 'a --', v => { v.rs.push(v.ds.pop()); }, { rd: 1 });
    d('R>', '-- a', v => { if (!v.rs.length) throw new ForthError('return stack underflow in R>'); v.ds.push(v.rs.pop()); }, { rd: -1 });
    d('R@', '-- a', v => { if (!v.rs.length) throw new ForthError('return stack underflow in R@'); v.ds.push(v.rs[v.rs.length - 1]); }, { rd: 0, rneed: 1 });
    d('2>R', 'a b --', v => { const b = v.ds.pop(), a = v.ds.pop(); v.rs.push(a, b); }, { rd: 2 });
    d('2R>', '-- a b', v => { if (v.rs.length < 2) throw new ForthError('return stack underflow in 2R>'); const b = v.rs.pop(), a = v.rs.pop(); v.ds.push(a, b); }, { rd: -2 });
    d('2R@', '-- a b', v => { const r = v.rs; if (r.length < 2) throw new ForthError('return stack underflow in 2R@'); v.ds.push(r[r.length - 2], r[r.length - 1]); }, { rd: 0, rneed: 2 });
    d('I', '-- n', v => { if (v.ls.length < 2) throw new ForthError('I used outside a DO loop'); v.ds.push(v.ls[v.ls.length - 1]); }, { needLoop: 1 });
    d('J', '-- n', v => { if (v.ls.length < 4) throw new ForthError('J needs two nested DO loops'); v.ds.push(v.ls[v.ls.length - 3]); }, { needLoop: 2 });
    d('UNLOOP', '--', v => { if (v.ls.length < 2) throw new ForthError('UNLOOP outside a DO loop'); v.ls.length -= 2; });

    // arithmetic
    bin('+', (a, b) => a + b); bin('-', (a, b) => a - b); bin('*', (a, b) => Math.imul(a, b));
    d('/', 'a b -- c', v => { const b = v.ds.pop(), a = v.ds.pop(); divz(b); v.ds.push(Math.floor(a / b) | 0); });
    d('MOD', 'a b -- c', v => { const b = v.ds.pop(), a = v.ds.pop(); divz(b); v.ds.push((a - Math.floor(a / b) * b) | 0); });
    d('/MOD', 'a b -- c d', v => { const b = v.ds.pop(), a = v.ds.pop(); divz(b); const q = Math.floor(a / b); v.ds.push((a - q * b) | 0, q | 0); });
    const bigdiv = (a, b, c) => { divz(c); const p = BigInt(a) * BigInt(b), C = BigInt(c); let q = p / C, r = p % C; if (r !== 0n && ((r < 0n) !== (C < 0n))) { q -= 1n; r += C; } return [Number(BigInt.asIntN(32, r)), Number(BigInt.asIntN(32, q))]; };
    d('*/', 'a b c -- d', v => { const c = v.ds.pop(), b = v.ds.pop(), a = v.ds.pop(); v.ds.push(bigdiv(a, b, c)[1]); });
    d('*/MOD', 'a b c -- d e', v => { const c = v.ds.pop(), b = v.ds.pop(), a = v.ds.pop(); const [r, q] = bigdiv(a, b, c); v.ds.push(r, q); });
    un('NEGATE', a => -a); un('ABS', a => Math.abs(a)); un('1+', a => a + 1); un('1-', a => a - 1);
    un('2*', a => a << 1); un('2/', a => a >> 1); un('INVERT', a => ~a);
    un('0=', a => B(a === 0)); un('0<', a => B(a < 0)); un('0>', a => B(a > 0)); un('0<>', a => B(a !== 0));
    bin('MIN', Math.min); bin('MAX', Math.max);
    bin('AND', (a, b) => a & b); bin('OR', (a, b) => a | b); bin('XOR', (a, b) => a ^ b);
    bin('LSHIFT', (a, b) => b > 31 || b < 0 ? 0 : a << b); bin('RSHIFT', (a, b) => b > 31 || b < 0 ? 0 : a >>> b);
    bin('=', (a, b) => B(a === b)); bin('<>', (a, b) => B(a !== b));
    bin('<', (a, b) => B(a < b)); bin('>', (a, b) => B(a > b)); bin('<=', (a, b) => B(a <= b)); bin('>=', (a, b) => B(a >= b));
    bin('U<', (a, b) => B(u32(a) < u32(b))); bin('U>', (a, b) => B(u32(a) > u32(b)));
    d('WITHIN', 'a b c -- d', v => { const c = v.ds.pop(), b = v.ds.pop(), a = v.ds.pop(); v.ds.push(B(u32(a - b) < u32(c - b))); });
    d('S>D', 'a -- b c', v => { const a = v.ds.pop(); v.ds.push(a, a < 0 ? -1 : 0); });
    d('UM*', 'a b -- c d', v => { const b = v.ds.pop(), a = v.ds.pop(); const p = BigInt(u32(a)) * BigInt(u32(b)); v.ds.push(Number(BigInt.asIntN(32, p)), Number(BigInt.asIntN(32, p >> 32n))); });
    d('M*', 'a b -- c d', v => { const b = v.ds.pop(), a = v.ds.pop(); const p = BigInt(a) * BigInt(b); v.ds.push(Number(BigInt.asIntN(32, p)), Number(BigInt.asIntN(32, p >> 32n))); });
    const dbl = (lo, hi) => (BigInt(hi) << 32n) | BigInt(u32(lo));
    d('UM/MOD', 'a b c -- d e', v => { const c = v.ds.pop(), hi = v.ds.pop(), lo = v.ds.pop(); divz(c); const n = (BigInt(u32(hi)) << 32n) | BigInt(u32(lo)); const C = BigInt(u32(c)); const q = n / C; if (q > 0xffffffffn) throw new ForthError('UM/MOD quotient overflow'); v.ds.push(Number(BigInt.asIntN(32, n % C)), Number(BigInt.asIntN(32, q))); });
    d('FM/MOD', 'a b c -- d e', v => { const c = v.ds.pop(), hi = v.ds.pop(), lo = v.ds.pop(); divz(c); const n = dbl(lo, hi), C = BigInt(c); let q = n / C, r = n % C; if (r !== 0n && ((r < 0n) !== (C < 0n))) { q -= 1n; r += C; } v.ds.push(Number(BigInt.asIntN(32, r)), Number(BigInt.asIntN(32, q))); });
    d('SM/REM', 'a b c -- d e', v => { const c = v.ds.pop(), hi = v.ds.pop(), lo = v.ds.pop(); divz(c); const n = dbl(lo, hi), C = BigInt(c); v.ds.push(Number(BigInt.asIntN(32, n % C)), Number(BigInt.asIntN(32, n / C))); });

    // constants
    d('TRUE', '-- a', v => { v.ds.push(-1); }); d('FALSE', '-- a', v => { v.ds.push(0); });
    d('BL', '-- a', v => { v.ds.push(32); });
    vm.find('TRUE').constVal = -1; vm.find('FALSE').constVal = 0; vm.find('BL').constVal = 32;

    // memory
    d('@', 'a -- b', v => { v.ds.push(v.fetch(v.ds.pop())); });
    d('!', 'a b --', v => { const a = v.ds.pop(), x = v.ds.pop(); v.store(a, x); });
    d('C@', 'a -- b', v => { const a = v.ds.pop(); v.chk(a, 1); v.ds.push(v.bytes[a]); });
    d('C!', 'a b --', v => { const a = v.ds.pop(), x = v.ds.pop(); v.chk(a, 1); v.bytes[a] = x & 255; });
    d('+!', 'a b --', v => { const a = v.ds.pop(), x = v.ds.pop(); v.store(a, v.fetch(a) + x); });
    d('2@', 'a -- b c', v => { const a = v.ds.pop(); v.ds.push(v.fetch(a + 4), v.fetch(a)); });
    d('2!', 'a b c --', v => { const a = v.ds.pop(), x2 = v.ds.pop(), x1 = v.ds.pop(); v.store(a, x2); v.store(a + 4, x1); });
    d('HERE', '-- a', v => { v.ds.push(v.here); });
    d('ALLOT', 'a --', v => { v.allot(v.ds.pop()); });
    d(',', 'a --', v => { v.store(v.allot(4), v.ds.pop()); });
    d('C,', 'a --', v => { const a = v.allot(1); v.bytes[a] = v.ds.pop() & 255; });
    d('CELLS', 'a -- b', v => { v.ds.push(v.ds.pop() * 4); }, { pure: true, fold: a => a * 4 });
    d('CELL+', 'a -- b', v => { v.ds.push(v.ds.pop() + 4); }, { pure: true, fold: a => a + 4 });
    d('CHARS', 'a -- b', v => { }, { pure: true, fold: a => a });
    d('CHAR+', 'a -- b', v => { v.ds.push(v.ds.pop() + 1); }, { pure: true, fold: a => a + 1 });
    d('BASE', '-- a', v => { v.ds.push(BASE_ADDR); });
    d('PAD', '-- a', v => { v.ds.push(PAD); });
    d('FILL', 'a b c --', v => { const c = v.ds.pop(), n = v.ds.pop(), a = v.ds.pop(); if (n > 0) { v.chk(a, n); v.bytes.fill(c & 255, a, a + n); } });
    d('ERASE', 'a b --', v => { const n = v.ds.pop(), a = v.ds.pop(); if (n > 0) { v.chk(a, n); v.bytes.fill(0, a, a + n); } });
    d('MOVE', 'a b c --', v => { const n = v.ds.pop(), dst = v.ds.pop(), src = v.ds.pop(); if (n > 0) { v.chk(src, n); v.chk(dst, n); v.bytes.copyWithin(dst, src, src + n); } });
    d('COUNT', 'a -- b c', v => { const a = v.ds.pop(); v.chk(a, 1); v.ds.push(a + 1, v.bytes[a]); });
    d('COMPARE', 'a b c d -- e', v => { const n2 = v.ds.pop(), a2 = v.ds.pop(), n1 = v.ds.pop(), a1 = v.ds.pop(); const s1 = v.getString(a1, n1), s2 = v.getString(a2, n2); v.ds.push(s1 === s2 ? 0 : s1 < s2 ? -1 : 1); });

    // I/O
    const fmt = (n, base, signed) => {
      const neg = signed && n < 0; const m = neg ? -n : (signed ? n : u32(n));
      let s = (neg ? (n === -2147483648 ? 2147483648 : m) : m).toString(base).toUpperCase();
      return (neg ? '-' : '') + s;
    };
    vm.fmt = fmt;
    d('.', 'a --', v => { v.emit(fmt(v.ds.pop(), v.base, true) + ' '); });
    d('U.', 'a --', v => { v.emit(fmt(v.ds.pop(), v.base, false) + ' '); });
    d('.R', 'a b --', v => { const w = v.ds.pop(), n = v.ds.pop(); v.emit(fmt(n, v.base, true).padStart(Math.max(0, w))); });
    d('CR', '--', v => { v.emit('\n'); });
    d('EMIT', 'a --', v => { v.emit(String.fromCharCode(v.ds.pop() & 255)); });
    d('SPACE', '--', v => { v.emit(' '); });
    d('SPACES', 'a --', v => { const n = v.ds.pop(); if (n > 0) v.emit(' '.repeat(Math.min(n, 10000))); });
    d('TYPE', 'a b --', v => { const n = v.ds.pop(), a = v.ds.pop(); if (n > 0) v.emit(v.getString(a, n)); });
    d('.S', '--', v => { v.emit('<' + v.ds.length + '> ' + v.ds.map(x => fmt(x, v.base, true)).join(' ') + (v.ds.length ? ' ' : '')); });
    d('HEX', '--', v => { v.store(BASE_ADDR, 16); });
    d('DECIMAL', '--', v => { v.store(BASE_ADDR, 10); });
    d('WORDS', '--', v => { v.emit([...v.dict.values()].map(w => w.name.toLowerCase()).join(' ') + '\n'); });
    d('EXECUTE', '?', v => {
      if (!v.ds.length) throw new ForthError('stack underflow in EXECUTE');
      const id = v.ds.pop(); const w = v.xts[id];
      if (!w || id <= 0) throw new ForthError('EXECUTE: invalid execution token ' + id);
      v.invoke(w);
    });
    d('ABORT', '--', v => { throw new ForthError('ABORT'); });
    d('BYE', '--', v => { throw new ForthError('BYE'); });
  };

  Forth.O = O; Forth.ForthError = ForthError; Forth.parseEffect = parseEffect;
  Forth.effectString = effectString; Forth.effNames = effNames;
  return Forth;
});
