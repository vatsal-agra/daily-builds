"""Renders a captured pipeline execution trace (PipelineSimulator.cycle_log,
built from real per-cycle stage occupancy -- not synthetic data) to a
self-contained interactive HTML pipeline diagram: one row per *dynamic*
instruction instance (so a loop body run 10 times gets 10 distinct rows),
one column per cycle, stalls visible as an instruction sitting in the same
stage for two+ columns, and flushed (mis-speculated) instructions visibly
truncated and tinted red.
"""

from __future__ import annotations

import html
import json

STAGE_COLOR = {
    "IF": "#3b82f6",
    "ID": "#a855f7",
    "EX": "#f59e0b",
    "MEM": "#10b981",
    "WB": "#64748b",
}
STAGE_ORDER = ["IF", "ID", "EX", "MEM", "WB"]


def _build_instances(cycle_log):
    instances = {}
    order = []
    for row in cycle_log:
        cyc = row["cycle"]
        for stage in STAGE_ORDER:
            val = row.get(stage)
            if not val:
                continue
            seq = val["seq"]
            if seq not in instances:
                instances[seq] = {"seq": seq, "pc": val["pc"], "text": val["text"], "cells": {}}
                order.append(seq)
            instances[seq]["cells"][cyc] = stage
    return [instances[s] for s in order]


def render_pipeline_html(sim, title: str = "program") -> str:
    instances = _build_instances(sim.cycle_log)
    max_cycle = sim.stats.cycles
    reg_rows = []
    for i in range(0, 32, 1):
        from . import isa
        reg_rows.append((f"x{i}", isa.reg_name(i), sim.regs.read(i)))

    stalled_cycles = {row["cycle"]: row["stalled"] for row in sim.cycle_log if row.get("stalled")}
    flushed_cycles = {row["cycle"]: row["flush"] for row in sim.cycle_log if row.get("flush")}

    # ---- build the grid as JSON for the client to render (keeps the HTML
    # itself small and lets us add hover/zoom without regenerating markup) ----
    grid_data = {
        "instances": [
            {"seq": inst["seq"], "pc": inst["pc"], "text": inst["text"], "cells": inst["cells"]}
            for inst in instances
        ],
        "maxCycle": max_cycle,
        "stalledCycles": stalled_cycles,
        "flushedCycles": flushed_cycles,
    }

    icache_html = _cache_panel(sim.icache, "L1 Instruction Cache") if sim.icache else ""
    dcache_html = _cache_panel(sim.dcache, "L1 Data Cache") if sim.dcache else ""

    s = sim.stats
    misp_pct = (100.0 * s.mispredictions / s.branches_resolved) if s.branches_resolved else 0.0

    return f"""<title>Silicon pipeline trace: {html.escape(title)}</title>
<style>
  :root {{
    --bg: #0b1020; --panel: #131a2e; --border: #263252; --text: #e2e8f0;
    --muted: #93a3c2; --accent: #38bdf8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: 'SF Mono', 'JetBrains Mono', Consolas, monospace;
    margin: 0; padding: 24px; font-size: 13px;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); margin-bottom: 20px; }}
  .panels {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 18px; min-width: 200px;
  }}
  .panel h2 {{ font-size: 12px; text-transform: uppercase; letter-spacing: .06em;
    color: var(--muted); margin: 0 0 8px; }}
  .stat {{ font-size: 22px; font-weight: 600; }}
  .stat small {{ font-size: 12px; color: var(--muted); font-weight: 400; }}
  .legend {{ display: flex; gap: 14px; margin-bottom: 12px; flex-wrap: wrap; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; color: var(--muted); }}
  .swatch {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
  #gridwrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 10px;
    background: var(--panel); }}
  table.grid {{ border-collapse: collapse; font-size: 11px; }}
  table.grid th, table.grid td {{ padding: 0; text-align: center; }}
  .rowlabel {{
    position: sticky; left: 0; background: var(--panel); z-index: 2;
    padding: 3px 10px !important; text-align: left !important; white-space: nowrap;
    border-right: 1px solid var(--border); color: var(--text);
  }}
  .colhead {{ color: var(--muted); font-weight: 400; padding: 4px 2px !important;
    position: sticky; top: 0; background: var(--panel); z-index: 1; }}
  .cell {{ width: 20px; height: 20px; border: 1px solid #0b1020; }}
  .cell.flushed {{ opacity: 0.55; box-shadow: inset 0 0 0 1px #ef4444; }}
  .cell.stallcol {{ box-shadow: inset 0 0 0 1px #eab308; }}
  #tooltip {{
    position: fixed; display: none; background: #000c; border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 10px; font-size: 12px; pointer-events: none; z-index: 10;
  }}
  table.regs {{ border-collapse: collapse; font-size: 11px; }}
  table.regs td {{ padding: 2px 8px; border-bottom: 1px solid var(--border); }}
  footer {{ margin-top: 24px; color: var(--muted); font-size: 11px; }}
</style>
<h1>Silicon &mdash; pipeline trace: {html.escape(title)}</h1>
<div class="sub">{s.instret} instructions retired in {s.cycles} cycles &middot; CPI {s.cpi:.3f} &middot;
predictor: {sim.predictor.name}</div>

<div class="panels">
  <div class="panel"><h2>Cycles</h2><div class="stat">{s.cycles}</div></div>
  <div class="panel"><h2>Instructions</h2><div class="stat">{s.instret}</div></div>
  <div class="panel"><h2>CPI</h2><div class="stat">{s.cpi:.2f}</div></div>
  <div class="panel"><h2>Load-use stalls</h2><div class="stat">{s.load_use_stall_cycles}<small> cycles</small></div></div>
  <div class="panel"><h2>Mem-stall cycles</h2><div class="stat">{s.mem_stall_cycles}</div></div>
  <div class="panel"><h2>Branch mispredictions</h2>
    <div class="stat">{s.mispredictions}<small> / {s.branches_resolved} ({misp_pct:.1f}%)</small></div></div>
  {icache_html}
  {dcache_html}
</div>

<div class="legend">
  <span><span class="swatch" style="background:{STAGE_COLOR['IF']}"></span>IF</span>
  <span><span class="swatch" style="background:{STAGE_COLOR['ID']}"></span>ID</span>
  <span><span class="swatch" style="background:{STAGE_COLOR['EX']}"></span>EX</span>
  <span><span class="swatch" style="background:{STAGE_COLOR['MEM']}"></span>MEM</span>
  <span><span class="swatch" style="background:{STAGE_COLOR['WB']}"></span>WB</span>
  <span><span class="swatch" style="box-shadow: inset 0 0 0 1px #ef4444; background:#111"></span>flushed (misprediction)</span>
  <span><span class="swatch" style="box-shadow: inset 0 0 0 1px #eab308; background:#111"></span>stall cycle</span>
</div>

<div id="gridwrap"><table class="grid" id="grid"></table></div>
<div id="tooltip"></div>

<h2 style="margin-top:28px;">Final register file</h2>
<table class="regs">{_reg_table_html(reg_rows)}</table>

<footer>Generated by Silicon from a real captured execution trace of {html.escape(title)}.s
({len(instances)} dynamic instruction instances across {max_cycle} cycles).</footer>

<script>
const DATA = {json.dumps(grid_data)};
const STAGE_COLOR = {json.dumps(STAGE_COLOR)};

function build() {{
  const table = document.getElementById('grid');
  const thead = document.createElement('tr');
  thead.innerHTML = '<th class="rowlabel">instruction</th>' +
    Array.from({{length: DATA.maxCycle}}, (_, c) =>
      '<th class="colhead">' + (c % 5 === 0 ? c : '') + '</th>').join('');
  table.appendChild(thead);

  const tooltip = document.getElementById('tooltip');

  for (const inst of DATA.instances) {{
    const tr = document.createElement('tr');
    const label = document.createElement('td');
    label.className = 'rowlabel';
    label.textContent = '0x' + inst.pc.toString(16).padStart(4,'0') + '  ' + inst.text;
    tr.appendChild(label);

    const reachedWB = Object.values(inst.cells).includes('WB');
    for (let c = 0; c < DATA.maxCycle; c++) {{
      const td = document.createElement('td');
      const stage = inst.cells[c];
      let cls = 'cell';
      if (DATA.flushedCycles[c] && !reachedWB) cls += ' flushed';
      if (DATA.stalledCycles[c]) cls += ' stallcol';
      td.className = cls;
      if (stage) {{
        td.style.background = STAGE_COLOR[stage];
        td.addEventListener('mousemove', (e) => {{
          tooltip.style.display = 'block';
          tooltip.style.left = (e.clientX + 12) + 'px';
          tooltip.style.top = (e.clientY + 12) + 'px';
          tooltip.textContent = 'cycle ' + c + ': ' + stage + '  ' + inst.text;
        }});
        td.addEventListener('mouseleave', () => tooltip.style.display = 'none');
      }}
      tr.appendChild(td);
    }}
    table.appendChild(tr);
  }}
}}
build();
</script>
"""


def _cache_panel(cache, label: str) -> str:
    st = cache.stats
    return (
        f'<div class="panel"><h2>{html.escape(label)}</h2>'
        f'<div class="stat">{st.hit_rate:.0%}<small> hit rate</small></div>'
        f'<div style="color:var(--muted); margin-top:4px;">{st.hits} hits / {st.misses} misses</div>'
        f"</div>"
    )


def _reg_table_html(rows) -> str:
    cells = []
    for i in range(0, 32, 4):
        tr = "<tr>"
        for j in range(4):
            xname, abi, val = rows[i + j]
            tr += f"<td>{xname} ({abi})</td><td style='text-align:right'>{val}</td>"
        tr += "</tr>"
        cells.append(tr)
    return "".join(cells)
