"""Render the implication graph at the first conflict to a standalone HTML/SVG
file — no JS frameworks, no external assets. Nodes are assigned literals laid
out in columns by decision level; edges are reason (antecedent) relationships.
Decision literals are diamonds, the 1-UIP literal is highlighted, and the
conflict node κ is shown in red along with the learned clause.
"""
from __future__ import annotations

from typing import Dict, List, Tuple
from .cnf import CNF
from .solver import Solver


def _lit_label(lit: int) -> str:
    v = abs(lit)
    return f"x{v}" if lit > 0 else f"¬x{v}"


def _collect_graph(s: Solver, conflict):
    """Return (nodes, edges, uip_var, learned). nodes: var -> dict(level, lit,
    decision, order). edges: list of (src_var_or_None, dst_key)."""
    nodes: Dict[int, dict] = {}
    edges: List[Tuple] = []
    pos = {abs(s.trail[i]): i for i in range(len(s.trail))}

    def add_var(v: int):
        if v not in nodes:
            nodes[v] = {
                "level": s.level[v],
                "lit": s.assigned_literal(v),
                "decision": s.reason[v] is None,
                "order": pos.get(v, 0),
            }

    frontier = []
    # Conflict clause: every literal is false; the assignment that falsified
    # each one (the negation) points at the conflict node κ.
    for lit in conflict.lits:
        v = abs(lit)
        if s.level[v] == 0:
            continue
        add_var(v)
        edges.append((v, "K"))
        frontier.append(v)

    seen = set(frontier)
    while frontier:
        v = frontier.pop()
        reason = s.reason[v]
        if reason is None:
            continue  # decision node, a source
        for lit in reason.lits:
            u = abs(lit)
            if u == v or s.level[u] == 0:
                continue
            add_var(u)
            edges.append((u, v))
            if u not in seen:
                seen.add(u)
                frontier.append(u)

    # Compute the 1-UIP learned clause (reads state, does not mutate assignment).
    learned, _bt = s._analyze(conflict)
    uip_var = abs(learned[0])
    add_var(uip_var)
    return nodes, edges, uip_var, learned


def _svg(nodes, edges, uip_var, learned) -> str:
    # Layout: x by decision level, y by assignment order within level.
    levels = sorted(set(n["level"] for n in nodes.values()))
    col_x = {lv: 110 + i * 200 for i, lv in enumerate(levels)}
    by_level: Dict[int, list] = {lv: [] for lv in levels}
    for v, n in nodes.items():
        by_level[n["level"]].append(v)
    coords: Dict[object, Tuple[float, float]] = {}
    for lv in levels:
        vs = sorted(by_level[lv], key=lambda v: nodes[v]["order"])
        for j, v in enumerate(vs):
            coords[v] = (col_x[lv], 90 + j * 90)
    # Conflict node κ to the far right.
    kx = (max(col_x.values()) + 200) if col_x else 200
    ky = 90
    coords["K"] = (kx, ky)

    width = kx + 140
    height = max((90 + 90 * max((len(by_level[lv]) for lv in levels), default=1)),
                 260)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" '
             f'height="{height}" xmlns="http://www.w3.org/2000/svg" '
             'font-family="ui-monospace, Menlo, monospace">']
    parts.append('<defs><marker id="arrow" markerWidth="10" markerHeight="10" '
                 'refX="9" refY="3" orient="auto" markerUnits="strokeWidth">'
                 '<path d="M0,0 L9,3 L0,6 Z" fill="#7c8aa5"/></marker></defs>')

    # Level guide bands.
    for lv in levels:
        x = col_x[lv]
        parts.append(f'<text x="{x}" y="42" fill="#6b7a99" font-size="13" '
                     f'text-anchor="middle">level {lv}</text>')

    # Edges first (so nodes draw on top).
    for src, dst in edges:
        x1, y1 = coords[src]
        x2, y2 = coords[dst]
        parts.append(f'<line x1="{x1+34}" y1="{y1}" x2="{x2-34}" y2="{y2}" '
                     'stroke="#7c8aa5" stroke-width="1.6" marker-end="url(#arrow)" '
                     'opacity="0.8"/>')

    learned_vars = set(abs(l) for l in learned)
    # Nodes.
    for v, n in nodes.items():
        x, y = coords[v]
        is_uip = (v == uip_var)
        in_learned = v in learned_vars
        if is_uip:
            fill, stroke = "#fde68a", "#d97706"
        elif in_learned:
            fill, stroke = "#dbeafe", "#2563eb"
        elif n["decision"]:
            fill, stroke = "#e9d5ff", "#7c3aed"
        else:
            fill, stroke = "#e2e8f0", "#64748b"
        if n["decision"]:
            # diamond
            parts.append(f'<polygon points="{x},{y-30} {x+44},{y} {x},{y+30} '
                         f'{x-44},{y}" fill="{fill}" stroke="{stroke}" '
                         'stroke-width="2"/>')
        else:
            parts.append(f'<rect x="{x-40}" y="{y-24}" width="80" height="48" '
                         f'rx="10" fill="{fill}" stroke="{stroke}" '
                         'stroke-width="2"/>')
        parts.append(f'<text x="{x}" y="{y+5}" text-anchor="middle" '
                     f'font-size="16" fill="#0f172a">{_lit_label(n["lit"])}</text>')
        if is_uip:
            parts.append(f'<text x="{x}" y="{y-36}" text-anchor="middle" '
                         'font-size="11" fill="#b45309">1-UIP</text>')

    # Conflict node.
    kx, kyc = coords["K"]
    parts.append(f'<circle cx="{kx}" cy="{kyc}" r="30" fill="#fecaca" '
                 'stroke="#dc2626" stroke-width="2.5"/>')
    parts.append(f'<text x="{kx}" y="{kyc+7}" text-anchor="middle" '
                 'font-size="22" fill="#991b1b">κ</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def render_conflict_html(formula: CNF, out_path: str) -> str:
    s = Solver(formula)
    conflict = s.run_to_first_conflict()
    if conflict is None:
        if not s.ok:
            body = ("<p>This formula is unsatisfiable at the root level "
                    "(a conflict before any decision) — there is no branching "
                    "implication graph to draw.</p>")
        else:
            model_ok = formula.is_satisfied_by(s.model())
            body = ("<p>The solver satisfied this formula without ever hitting a "
                    f"conflict, so there is no implication graph. "
                    f"(model verified: {model_ok})</p>")
        svg = ""
        learned_txt = ""
    else:
        nodes, edges, uip_var, learned = _collect_graph(s, conflict)
        svg = _svg(nodes, edges, uip_var, learned)
        clause_txt = " ∨ ".join(_lit_label(l) for l in conflict.lits)
        learned_clause = " ∨ ".join(_lit_label(l) for l in learned)
        body = (f"<p>First conflict reached at decision level "
                f"<b>{s.decision_level}</b> after {s.stats.decisions} decisions. "
                f"The conflicting clause (all literals false) is "
                f"<code>{clause_txt}</code>.</p>"
                f"<p>Conflict analysis resolves backward to the first unique "
                f"implication point and learns the clause "
                f"<code>{learned_clause}</code>, which the solver adds before "
                f"backjumping.</p>")
        learned_txt = learned_clause

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Resolvent — conflict implication graph</title>
<style>
  body {{ margin:0; background:#0f172a; color:#e2e8f0;
         font-family: ui-monospace, Menlo, monospace; }}
  header {{ padding:28px 36px 8px; }}
  h1 {{ margin:0 0 6px; font-size:22px; color:#f8fafc; }}
  .sub {{ color:#94a3b8; font-size:14px; }}
  .panel {{ margin:18px 36px; background:#f8fafc; color:#0f172a;
            border-radius:14px; padding:18px; overflow:auto; }}
  .legend {{ display:flex; gap:18px; flex-wrap:wrap; margin:8px 36px 0;
             font-size:13px; color:#cbd5e1; }}
  .legend span {{ display:inline-flex; align-items:center; gap:7px; }}
  .sw {{ width:16px; height:16px; border-radius:4px; display:inline-block; }}
  p {{ line-height:1.5; }}
  code {{ background:#e2e8f0; padding:2px 6px; border-radius:5px; }}
  footer {{ color:#64748b; font-size:12px; padding:8px 36px 30px; }}
</style></head>
<body>
<header>
  <h1>Resolvent · conflict implication graph</h1>
  <div class="sub">{formula.nvars} variables · {formula.nclauses} clauses</div>
</header>
<div class="legend">
  <span><span class="sw" style="background:#e9d5ff;border:2px solid #7c3aed"></span>decision</span>
  <span><span class="sw" style="background:#e2e8f0;border:2px solid #64748b"></span>implied</span>
  <span><span class="sw" style="background:#dbeafe;border:2px solid #2563eb"></span>in learned clause</span>
  <span><span class="sw" style="background:#fde68a;border:2px solid #d97706"></span>1-UIP</span>
  <span><span class="sw" style="background:#fecaca;border:2px solid #dc2626;border-radius:50%"></span>conflict κ</span>
</div>
<div class="panel">
  {body}
  {svg}
</div>
<footer>Generated by Resolvent — a from-scratch CDCL SAT solver.</footer>
</body></html>
"""
    with open(out_path, "w") as fh:
        fh.write(html)
    note = f"c wrote implication-graph visualization to {out_path}"
    if learned_txt:
        note += f"\nc learned clause: {learned_txt}"
    return note
