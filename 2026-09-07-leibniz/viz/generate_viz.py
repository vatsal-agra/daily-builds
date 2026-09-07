"""Build a self-contained, dependency-free HTML visualizer for a captured
Leibniz derivation (a list of Steps entries, each with a rendered string and
a JSON expression tree). No server, no external assets, no build step."""

from __future__ import annotations

import json

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Leibniz -- {op_title}</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --panel2: #1e222b; --text: #e8eaf0;
    --muted: #8b93a7; --accent: #7dd3fc; --accent2: #a78bfa; --edge: #3a4152;
    --good: #4ade80;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: 'Cambria Math', Georgia, 'Times New Roman', serif;
    display: flex; flex-direction: column; height: 100vh;
  }}
  header {{
    padding: 14px 22px; background: var(--panel); border-bottom: 1px solid var(--edge);
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  }}
  header h1 {{ font-size: 18px; margin: 0; font-weight: 600; letter-spacing: .02em; }}
  header .badge {{
    font-family: -apple-system, sans-serif; font-size: 11px; text-transform: uppercase;
    letter-spacing: .08em; background: var(--accent2); color: #14101f; padding: 3px 9px;
    border-radius: 999px; font-weight: 700;
  }}
  header .orig {{ color: var(--muted); font-size: 15px; }}
  .layout {{ flex: 1; display: flex; min-height: 0; }}
  nav {{
    width: 280px; background: var(--panel); border-right: 1px solid var(--edge);
    overflow-y: auto; padding: 10px;
  }}
  .step {{
    padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px;
    border: 1px solid transparent; transition: background .12s;
    font-family: -apple-system, sans-serif;
  }}
  .step:hover {{ background: var(--panel2); }}
  .step.active {{ background: var(--panel2); border-color: var(--accent); }}
  .step .idx {{
    display: inline-block; width: 20px; height: 20px; border-radius: 50%;
    background: var(--edge); color: var(--text); font-size: 11px; text-align: center;
    line-height: 20px; margin-right: 8px;
  }}
  .step.active .idx {{ background: var(--accent); color: #06202b; }}
  .step .label {{ font-size: 13px; font-weight: 600; }}
  .step .note {{ font-size: 11px; color: var(--muted); margin-left: 28px; }}
  main {{ flex: 1; display: flex; flex-direction: column; min-width: 0; }}
  .expr-panel {{
    padding: 26px 30px; border-bottom: 1px solid var(--edge); background: var(--panel);
  }}
  .expr-panel .tag {{ font-family: -apple-system, sans-serif; font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: 6px; }}
  .expr-panel .expr {{ font-size: 30px; color: var(--good); word-break: break-word; }}
  .tree-panel {{ flex: 1; overflow: auto; padding: 20px; }}
  svg text {{ fill: var(--text); font-family: 'Cambria Math', Georgia, serif; }}
  svg .Num text, svg .Symbol text {{ fill: var(--accent); }}
  svg .Func text, svg .Constant text, svg .Imaginary text {{ fill: var(--accent2); }}
  svg circle {{ fill: var(--panel2); stroke: var(--edge); stroke-width: 1.5; }}
  svg .node.active circle {{ stroke: var(--accent); stroke-width: 2.5; }}
  svg line {{ stroke: var(--edge); stroke-width: 1.5; }}
  .controls {{
    font-family: -apple-system, sans-serif; padding: 10px 22px; background: var(--panel);
    border-top: 1px solid var(--edge); display: flex; gap: 10px; align-items: center;
  }}
  button {{
    background: var(--panel2); color: var(--text); border: 1px solid var(--edge);
    padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
  }}
  button:hover {{ background: var(--edge); }}
  .controls .pos {{ color: var(--muted); font-size: 12px; font-family: monospace; }}
  footer {{ padding: 6px 22px; font-family: -apple-system, sans-serif; font-size: 11px;
    color: var(--muted); background: var(--panel); }}
</style>
</head>
<body>
<header>
  <h1>Leibniz</h1>
  <span class="badge">{op_title}</span>
  <span class="orig">{expr_text_esc}{var_note}</span>
</header>
<div class="layout">
  <nav id="steplist"></nav>
  <main>
    <div class="expr-panel">
      <div class="tag">result</div>
      <div class="expr" id="exprline"></div>
    </div>
    <div class="tree-panel"><svg id="tree" width="100%" height="600"></svg></div>
  </main>
</div>
<div class="controls">
  <button id="prev">&larr; prev</button>
  <button id="play">&#9654; play</button>
  <button id="next">next &rarr;</button>
  <span class="pos" id="pos"></span>
</div>
<footer>Self-contained -- no server, no external assets. Use &larr;/&rarr; or click a step.</footer>
<script>
const STEPS = {steps_json};

let current = 0;
let playing = null;

function renderStepList() {{
  const nav = document.getElementById('steplist');
  nav.innerHTML = '';
  STEPS.forEach((s, i) => {{
    const div = document.createElement('div');
    div.className = 'step' + (i === current ? ' active' : '');
    div.innerHTML = `<span class="idx">${{i+1}}</span><span class="label">${{escapeHtml(s.label)}}</span>` +
                     (s.note ? `<div class="note">${{escapeHtml(s.note)}}</div>` : '');
    div.onclick = () => {{ current = i; render(); }};
    nav.appendChild(div);
  }});
}}

function escapeHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function layoutTree(node) {{
  let leafCounter = 0;
  function assign(n, depth) {{
    n.depth = depth;
    if (!n.children || n.children.length === 0) {{
      n.x = leafCounter; leafCounter += 1;
    }} else {{
      n.children.forEach(c => assign(c, depth + 1));
      n.x = (n.children[0].x + n.children[n.children.length - 1].x) / 2;
    }}
  }}
  assign(node, 0);
  return {{tree: node, leafCount: Math.max(leafCounter, 1)}};
}}

function drawTree(node) {{
  const svg = document.getElementById('tree');
  svg.innerHTML = '';
  const {{tree, leafCount}} = layoutTree(node);
  const spacingX = 78, spacingY = 76, marginX = 60, marginY = 40;
  const width = Math.max(leafCount * spacingX + marginX * 2, 400);
  const depthMax = maxDepth(tree);
  const height = (depthMax + 1) * spacingY + marginY * 2;
  svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
  svg.setAttribute('height', height);

  const ns = 'http://www.w3.org/2000/svg';
  function pos(n) {{ return [marginX + n.x * spacingX, marginY + n.depth * spacingY]; }}

  function drawEdges(n) {{
    if (!n.children) return;
    const [x1, y1] = pos(n);
    n.children.forEach(c => {{
      const [x2, y2] = pos(c);
      const line = document.createElementNS(ns, 'line');
      line.setAttribute('x1', x1); line.setAttribute('y1', y1 + 16);
      line.setAttribute('x2', x2); line.setAttribute('y2', y2 - 16);
      svg.appendChild(line);
      drawEdges(c);
    }});
  }}
  drawEdges(tree);

  function drawNodes(n) {{
    const [x, y] = pos(n);
    const g = document.createElementNS(ns, 'g');
    g.setAttribute('class', 'node ' + n.type);
    g.setAttribute('transform', `translate(${{x}},${{y}})`);
    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('r', 16);
    g.appendChild(circle);
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dy', '5');
    text.setAttribute('font-size', '13');
    text.textContent = n.label;
    g.appendChild(text);
    svg.appendChild(g);
    (n.children || []).forEach(drawNodes);
  }}
  drawNodes(tree);
}}

function maxDepth(n) {{
  if (!n.children || n.children.length === 0) return n.depth;
  return Math.max(...n.children.map(maxDepth));
}}

function render() {{
  renderStepList();
  const s = STEPS[current];
  document.getElementById('exprline').textContent = s.expr;
  document.getElementById('pos').textContent = `step ${{current+1}} / ${{STEPS.length}}`;
  drawTree(JSON.parse(JSON.stringify(s.tree)));
}}

document.getElementById('prev').onclick = () => {{ current = Math.max(0, current - 1); render(); }};
document.getElementById('next').onclick = () => {{ current = Math.min(STEPS.length - 1, current + 1); render(); }};
document.getElementById('play').onclick = (e) => {{
  if (playing) {{
    clearInterval(playing); playing = null; e.target.textContent = '▶ play';
  }} else {{
    e.target.textContent = '⏸ pause';
    playing = setInterval(() => {{
      if (current >= STEPS.length - 1) {{ current = 0; }} else {{ current += 1; }}
      render();
    }}, 1400);
  }}
}};
document.addEventListener('keydown', (e) => {{
  if (e.key === 'ArrowRight') {{ current = Math.min(STEPS.length - 1, current + 1); render(); }}
  if (e.key === 'ArrowLeft') {{ current = Math.max(0, current - 1); render(); }}
}});

render();
</script>
</body>
</html>
"""


def build_html(op: str, expr_text: str, var: str, steps: list[dict]) -> str:
    if not steps:
        raise ValueError("no steps to visualize")
    esc = (
        expr_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return _TEMPLATE.format(
        op_title=op,
        expr_text_esc=esc,
        var_note=f"  (variable: {var})" if var else "",
        steps_json=json.dumps(steps),
    )
