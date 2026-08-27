"""Captures a real WAM execution trace for one query and renders it as
a self-contained, interactive HTML step-through visualizer -- no server,
no client-side Prolog logic, just a JSON trace of a real run replayed by
a small amount of vanilla JS."""
import json
import os

from .parser import Parser
from .pretty import term_to_str
from .heap import reify

MAX_STEPS = 4000


def _cell_repr(cell):
    if cell.tag == "CON":
        return {"tag": "CON", "text": term_to_str(cell.a, quoted=True)}
    if cell.tag == "REF":
        return {"tag": "REF", "a": cell.a}
    if cell.tag == "STR":
        return {"tag": "STR", "a": cell.a}
    if cell.tag == "FUN":
        return {"tag": "FUN", "name": cell.a, "arity": cell.b}
    return {"tag": cell.tag}


def _instr_repr(instr):
    op = instr[0]
    rest = instr[1:]

    def fmt(v):
        if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
            return f"{v[0]}/{v[1]}"
        try:
            return term_to_str(v)
        except Exception:
            return str(v)
    return op + (" " + ", ".join(fmt(v) for v in rest) if rest else "")


def capture_trace(machine, goal_term, max_steps=MAX_STEPS):
    """Runs goal_term to its first solution (or failure/step cap),
    recording one frame per executed instruction. Returns
    (steps: list[dict], solved: bool)."""
    steps = []
    orig_exec = machine._exec

    def hooked(instr):
        p_before = machine.P
        (pred_name, pred_arity), clause_idx, offset = p_before
        result = orig_exec(instr)
        steps.append({
            "p": [pred_name, pred_arity, clause_idx, offset],
            "instr": _instr_repr(instr),
            "heap_len": len(machine.heap),
            "trail_len": len(machine.trail),
            "choice_len": len(machine.choice_stack),
            "choice_kinds": [cp.kind for cp in machine.choice_stack],
            "result": {"True": "ok", "False": "fail", "None": "jump"}[str(result)],
        })
        return result

    machine._exec = hooked
    solved = False
    try:
        for _ in machine.meta_call(goal_term):
            solved = True
            break
    finally:
        machine._exec = orig_exec

    heap_snapshot = [_cell_repr(c) for c in machine.heap[:20000]]
    trail_snapshot = list(machine.trail[:20000])
    return steps[:max_steps], solved, heap_snapshot, trail_snapshot


def run_and_export_trace(engine, goal_text, out_path):
    machine = engine.impl
    p = Parser(goal_text if goal_text.rstrip().endswith(".") else goal_text + ".")
    goal = p.read_clause()

    from .terms import term_vars, deref
    goal_str = term_to_str(goal, quoted=True)
    qvars = [v for v in term_vars(goal) if not v.name.startswith("_")]

    steps, solved, heap_snapshot, trail_snapshot = capture_trace(machine, goal)

    solution_str = "(query failed -- no solution)"
    if solved:
        parts = [f"{v.name} = {term_to_str(deref(v), quoted=True)}" for v in qvars]
        solution_str = ", ".join(parts) if parts else "true"

    payload = {
        "goal": goal_str,
        "solved": solved,
        "solution": solution_str,
        "steps": steps,
        "final_heap_len": len(machine.heap),
    }
    html = _TEMPLATE.replace("__WARREN_TRACE_JSON__", json.dumps(payload))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return os.path.abspath(out_path)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Warren -- WAM Execution Trace</title>
<style>
:root {
  --bg: #0b0e14; --panel: #121722; --panel2: #171d2b; --border: #232b3d;
  --text: #e6e9f0; --muted: #8b93a7; --accent: #7dd3fc; --accent2: #c084fc;
  --ok: #4ade80; --fail: #f87171; --jump: #fbbf24;
  --mono: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}
* { box-sizing: border-box; }
html, body {
  height: 100%; margin: 0; overflow: hidden; /* only the panels below scroll */
  background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
body { display: flex; flex-direction: column; }
main { flex: 1; min-height: 0; }
header {
  padding: 18px 28px; border-bottom: 1px solid var(--border);
  display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
}
header h1 { font-size: 18px; margin: 0; letter-spacing: 0.02em; }
header .goal { font-family: var(--mono); color: var(--accent); font-size: 14px; }
header .solution { font-family: var(--mono); color: var(--ok); font-size: 13px; margin-left: auto; }
main {
  display: grid; grid-template-columns: 340px 1fr 300px; gap: 1px;
  background: var(--border);
}
.panel { background: var(--panel); overflow: auto; padding: 14px 16px; }
.panel h2 {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin: 0 0 10px;
}
#controls {
  display: flex; gap: 8px; align-items: center; padding: 10px 16px;
  background: var(--panel2); border-bottom: 1px solid var(--border);
}
button {
  background: #1c2436; color: var(--text); border: 1px solid var(--border);
  padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
button:hover { background: #253049; }
button:disabled { opacity: 0.4; cursor: default; }
#step-label { font-family: var(--mono); color: var(--muted); font-size: 13px; margin: 0 8px; }
#scrubber { flex: 1; accent-color: var(--accent); }
.instr-list { font-family: var(--mono); font-size: 13px; }
.instr-row {
  padding: 3px 8px; border-radius: 4px; white-space: pre; cursor: pointer;
  border-left: 3px solid transparent;
}
.instr-row:hover { background: #1a2133; }
.instr-row.current { background: #1e2a44; border-left-color: var(--accent); }
.instr-row .tag { color: var(--muted); margin-right: 8px; }
.instr-row.ok .tag { color: var(--ok); }
.instr-row.fail .tag { color: var(--fail); }
.instr-row.jump .tag { color: var(--jump); }
.stat-row { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 13px; padding: 3px 0; }
.stat-row .k { color: var(--muted); }
.cs-item { font-family: var(--mono); font-size: 12px; padding: 2px 6px; background: #1a2133; border-radius: 4px; margin: 2px 0; display: inline-block; margin-right: 4px;}
.legend { margin-top: 18px; font-size: 12px; color: var(--muted); line-height: 1.7; }
.legend b { color: var(--text); }
footer { padding: 10px 16px; font-size: 12px; color: var(--muted); border-top: 1px solid var(--border); }
</style>
</head>
<body>
<header>
  <h1>Warren &mdash; WAM Execution Trace</h1>
  <span class="goal" id="goal-text"></span>
  <span class="solution" id="solution-text"></span>
</header>
<div id="controls">
  <button id="btn-first" title="First">|&laquo;</button>
  <button id="btn-back" title="Back">&larr;</button>
  <button id="btn-fwd" title="Forward">&rarr;</button>
  <button id="btn-last" title="Last">&raquo;|</button>
  <span id="step-label"></span>
  <input type="range" id="scrubber" min="0" max="0" value="0">
</div>
<main>
  <div class="panel">
    <h2>Instruction stream</h2>
    <div class="instr-list" id="instr-list"></div>
  </div>
  <div class="panel">
    <h2>Machine state at this step</h2>
    <div id="state"></div>
    <div class="legend">
      <div><b>P</b> &mdash; the instruction pointer: (predicate/arity, clause index, offset).</div>
      <div><b>heap</b> &mdash; tagged cells: REF (variable/binding), STR (structure pointer), FUN (functor), CON (constant). Grows monotonically forward; truncated on backtrack.</div>
      <div><b>trail</b> &mdash; addresses of variable bindings made since the last choice point, unwound on backtrack.</div>
      <div><b>choice points</b> &mdash; pending alternatives: <span style="color:var(--accent)">clause</span> (another matching clause), <span style="color:var(--accent2)">disj</span> ((A;B) right branch), <span style="color:var(--jump)">pygen</span> (a builtin's next solution).</div>
    </div>
  </div>
  <div class="panel">
    <h2>Choice-point stack</h2>
    <div id="cs-list"></div>
  </div>
</main>
<footer>Replaying a real captured execution &mdash; every instruction below actually ran on Warren's WAM for this query. No server, no live Prolog: this page is a static JSON trace + JS scrubber.</footer>
<script>
const TRACE = __WARREN_TRACE_JSON__;
const steps = TRACE.steps;
let cur = steps.length ? steps.length - 1 : 0;

document.getElementById('goal-text').textContent = TRACE.goal;
document.getElementById('solution-text').textContent =
  (TRACE.solved ? 'solved: ' : 'failed') + (TRACE.solved ? TRACE.solution : '');

const scrubber = document.getElementById('scrubber');
scrubber.max = Math.max(0, steps.length - 1);

const instrList = document.getElementById('instr-list');
steps.forEach((s, i) => {
  const row = document.createElement('div');
  row.className = 'instr-row ' + s.result;
  row.dataset.idx = i;
  row.innerHTML = `<span class="tag">${String(i).padStart(4,'0')}</span>${escapeHtml(s.instr)}`;
  row.addEventListener('click', () => { cur = i; render(); });
  instrList.appendChild(row);
});

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function render() {
  if (!steps.length) {
    document.getElementById('state').textContent = '(no instructions executed)';
    return;
  }
  const s = steps[cur];
  scrubber.value = cur;
  document.getElementById('step-label').textContent = `step ${cur + 1} / ${steps.length}`;

  [...instrList.children].forEach((el, i) => el.classList.toggle('current', i === cur));
  const currentEl = instrList.children[cur];
  if (currentEl) currentEl.scrollIntoView({block: 'center'});

  const stateEl = document.getElementById('state');
  const p = s.p;
  stateEl.innerHTML = `
    <div class="stat-row"><span class="k">P</span><span>${p[0]}/${p[1]}, clause ${p[2]}, offset ${p[3]}</span></div>
    <div class="stat-row"><span class="k">heap size</span><span>${s.heap_len} cells</span></div>
    <div class="stat-row"><span class="k">trail size</span><span>${s.trail_len} entries</span></div>
    <div class="stat-row"><span class="k">choice-stack depth</span><span>${s.choice_len}</span></div>
    <div class="stat-row"><span class="k">this step</span><span>${s.result}</span></div>
  `;

  const csEl = document.getElementById('cs-list');
  csEl.innerHTML = s.choice_kinds.length
    ? s.choice_kinds.map(k => `<div class="cs-item">${k}</div>`).join('')
    : '<span style="color:var(--muted)">(empty)</span>';
}

document.getElementById('btn-first').addEventListener('click', () => { cur = 0; render(); });
document.getElementById('btn-last').addEventListener('click', () => { cur = steps.length - 1; render(); });
document.getElementById('btn-back').addEventListener('click', () => { cur = Math.max(0, cur - 1); render(); });
document.getElementById('btn-fwd').addEventListener('click', () => { cur = Math.min(steps.length - 1, cur + 1); render(); });
scrubber.addEventListener('input', () => { cur = parseInt(scrubber.value, 10); render(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') { cur = Math.max(0, cur - 1); render(); }
  if (e.key === 'ArrowRight') { cur = Math.min(steps.length - 1, cur + 1); render(); }
});

render();
</script>
</body>
</html>
"""
