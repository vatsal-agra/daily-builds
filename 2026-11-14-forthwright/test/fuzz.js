/* Soundness fuzz for the stack-effect analyzer + differential test for the optimizer.
 * 1) random words are generated; whenever the analyzer ACCEPTS one, executing it on a stack of
 *    sentinels must consume exactly `in` items, leave exactly `out`, and not touch anything below.
 * 2) every accepted word is run with optimizer ON and OFF: outputs and stacks must be identical. */
const { create } = require('../src');

let seed = +process.env.SEED || 12345;
const rnd = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
const pick = a => a[Math.floor(rnd() * a.length)];
const int = (a, b) => a + Math.floor(rnd() * (b - a + 1));

const ATOMS = ['dup', 'drop', 'swap', 'over', 'rot', 'nip', 'tuck', '2dup', '2drop', '+', '-', '*', '1+', '1-', 'negate', 'abs',
  'min', 'max', '0=', '<', '=', 'and', 'or', 'xor', '2*', 'invert', '2swap', '2over', '-rot', 'depth', 'pick0', 'cells', '0<', 'u<', 'within', 'lshift'];
function gen(depth) {
  const parts = [], n = int(1, 6);
  for (let i = 0; i < n; i++) {
    const r = rnd();
    if (r < 0.50) parts.push(pick(ATOMS));
    else if (r < 0.65) parts.push(String(int(-3, 9)));
    else if (r < 0.75 && depth < 3) parts.push('if ' + gen(depth + 1) + ' else ' + gen(depth + 1) + ' then');
    else if (r < 0.80 && depth < 3) parts.push('if ' + gen(depth + 1) + ' then');
    else if (r < 0.88 && depth < 3) parts.push(int(1, 3) + ' 0 do ' + gen(depth + 1) + ' loop');
    else if (r < 0.92 && depth < 3) parts.push('>r ' + gen(depth + 1) + ' r>');
    else if (r < 0.95 && depth < 3) parts.push(int(1, 3) + ' 0 do ' + gen(depth + 1) + ' i + loop');
    else parts.push(pick(['dup', '1']));
  }
  return parts.join(' ').replace(/pick0/g, '0 pick');
}

const N = +process.env.N || 3000;
let accepted = 0, rejected = 0, unknown = 0, executed = 0, diffRuns = 0, loops = 0;
const bad = [];
for (let k = 0; k < N; k++) {
  const body = gen(0);
  const src = ': w ' + body + ' ;';
  const vm = create({ maxSteps: 100000 });
  const r = vm.run(src);
  if (!r.ok) { rejected++; continue; }
  const w = vm.find('w');
  if (!w.eff) { unknown++; continue; }
  accepted++;
  if (/\bdo\b/.test(body)) loops++;
  const { in: nin, out } = w.eff;
  for (let t = 0; t < 4; t++) {
    const margin = 3;
    const input = []; for (let i = 0; i < margin + nin; i++) input.push(int(-4, 4) + (i + 1) * 100 * 0);
    const vm2 = create({ maxSteps: 100000 });
    vm2.run(src);
    vm2.ds.push(...input);
    const before = input.slice();
    const res = vm2.run('w');
    executed++;
    if (!res.ok) {
      // only acceptable runtime failures: none (no division, effect proven)
      bad.push({ src, input, why: 'runtime error: ' + res.error }); break;
    }
    const expectDepth = margin + out;
    if (vm2.ds.length !== expectDepth) { bad.push({ src, input, why: 'depth ' + vm2.ds.length + ' expected ' + expectDepth + ' eff ' + nin + '->' + out }); break; }
    for (let i = 0; i < margin; i++) if (vm2.ds[i] !== before[i]) { bad.push({ src, input, why: 'margin item ' + i + ' clobbered' }); break; }
    // differential: optimizer off
    const vm3 = create({ maxSteps: 100000, optimize: false });
    vm3.run(src); vm3.ds.push(...input);
    const res3 = vm3.run('w'); diffRuns++;
    if (!res3.ok || res3.output !== res.output || vm3.ds.join() !== vm2.ds.join()) { bad.push({ src, input, why: 'optimizer differs: ' + vm2.ds + ' vs ' + vm3.ds }); break; }
  }
}
console.log(`fuzz: ${N} words -> accepted ${accepted} (${loops} with loops), rejected ${rejected}, dynamic ${unknown}; ${executed} runs, ${diffRuns} differential`);
if (bad.length) { console.log('FAILURES: ' + bad.length); bad.slice(0, 8).forEach(b => console.log(JSON.stringify(b))); process.exit(1); }
console.log('fuzz: ok');
