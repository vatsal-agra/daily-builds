"""Renders a real recorded resolution `Trace` into a single self-contained
HTML page -- no build step, no CDN, no client-side DNS logic; every line on
the page came from an actual wire exchange (or a real cache hit) that just
happened."""

from __future__ import annotations

import html as _html

from .textfmt import rcode_name

_KIND_LABEL = {
    "query": "query",
    "cache_hit": "cache hit",
    "error": "error",
}


def _esc(s: str) -> str:
    return _html.escape(str(s))


def _step_html(i: int, step) -> str:
    where = f"{_esc(step.server_name)} &middot; <span class=\"addr\">{_esc(step.server_addr)}</span>" \
        if step.server_name else "<span class=\"addr\">local cache</span>"
    rcode_badge = f'<span class="badge rcode-{_esc(step.rcode)}">{_esc(step.rcode)}</span>' if step.rcode else ""

    sections = ""
    for label, lines in (("ANSWER", step.answer_lines), ("AUTHORITY", step.authority_lines),
                         ("ADDITIONAL", step.additional_lines)):
        if lines:
            rows = "\n".join(f"<div class='rr'>{_esc(line)}</div>" for line in lines)
            sections += f"<div class='section'><div class='section-label'>{label}</div>{rows}</div>"

    return f"""
    <div class="step step-{_esc(step.kind)}">
      <div class="step-num">{i}</div>
      <div class="step-body">
        <div class="step-head">
          <span class="kind-badge kind-{_esc(step.kind)}">{_esc(_KIND_LABEL.get(step.kind, step.kind))}</span>
          <span class="where">{where}</span>
          {rcode_badge}
        </div>
        <div class="step-detail">{_esc(step.detail)}</div>
        {sections}
      </div>
    </div>"""


def render_trace_html(qname: str, qtype: str, trace, result) -> str:
    steps_html = "\n".join(_step_html(i, s) for i, s in enumerate(trace.steps, 1))
    answers_html = "\n".join(
        f"<div class='rr'>{_esc(_fmt(rr))}</div>" for rr in result.answers
    ) or "<div class='rr empty'>(no records)</div>"
    status = rcode_name(result.rcode)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cascade &middot; resolution trace for {_esc(qname)}</title>
<style>
  :root {{
    --bg: #f7f7fb; --panel: #ffffff; --text: #1a1c23; --muted: #6b7080;
    --border: #e2e4ea; --accent: #3b5bfd; --mono-bg: #f1f2f7;
    --query: #3b5bfd; --cache: #1a9c6a; --error: #d1373f;
    --rc-ok: #1a9c6a; --rc-bad: #d1373f;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14151c; --panel: #1c1e29; --text: #e7e8ee; --muted: #9297ab;
      --border: #2c2f3d; --accent: #7d93ff; --mono-bg: #12131a;
      --query: #7d93ff; --cache: #4ad999; --error: #ff6b74;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); margin: 0; padding: 2.5rem 1.5rem; }}
  .wrap {{ max-width: 780px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 0.15rem 0; }}
  .subtitle {{ color: var(--muted); font-size: 0.95rem; margin-bottom: 1.75rem; }}
  .subtitle code {{ background: var(--mono-bg); padding: 0.1rem 0.4rem; border-radius: 4px; }}
  .summary {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 1rem 1.25rem; margin-bottom: 1.75rem; display: flex; align-items: center; gap: 0.9rem;
    flex-wrap: wrap;
  }}
  .status-badge {{
    font-weight: 600; padding: 0.25rem 0.6rem; border-radius: 6px; font-size: 0.85rem;
    background: {"var(--rc-ok)" if status in ("NOERROR",) else "var(--rc-bad)"};
    color: white;
  }}
  .summary .meta {{ color: var(--muted); font-size: 0.9rem; }}
  .answers {{ margin-top: 0.6rem; width: 100%; }}
  .timeline {{ position: relative; }}
  .step {{ display: flex; gap: 1rem; margin-bottom: 1.1rem; }}
  .step-num {{
    flex: 0 0 auto; width: 1.9rem; height: 1.9rem; border-radius: 50%;
    background: var(--panel); border: 1px solid var(--border); color: var(--muted);
    display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 600;
  }}
  .step-body {{
    flex: 1; background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 0.9rem 1.1rem;
  }}
  .step-head {{ display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.3rem; }}
  .kind-badge {{
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700;
    padding: 0.15rem 0.45rem; border-radius: 4px; color: white;
  }}
  .kind-query {{ background: var(--query); }}
  .kind-cache_hit {{ background: var(--cache); }}
  .kind-error {{ background: var(--error); }}
  .where {{ font-weight: 600; }}
  .addr {{ color: var(--muted); font-weight: 400; font-family: ui-monospace, monospace; font-size: 0.85rem; }}
  .badge {{
    font-size: 0.72rem; font-family: ui-monospace, monospace; padding: 0.1rem 0.4rem;
    border-radius: 4px; background: var(--mono-bg); color: var(--muted); margin-left: auto;
  }}
  .step-detail {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 0.4rem; }}
  .section {{ margin-top: 0.5rem; }}
  .section-label {{
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted);
    margin-bottom: 0.2rem; font-weight: 700;
  }}
  .rr {{
    font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 0.83rem;
    background: var(--mono-bg); padding: 0.25rem 0.55rem; border-radius: 5px; margin-bottom: 0.2rem;
    overflow-x: auto; white-space: pre;
  }}
  .rr.empty {{ color: var(--muted); font-style: italic; }}
  footer {{ margin-top: 2rem; color: var(--muted); font-size: 0.8rem; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Resolution trace</h1>
  <div class="subtitle">Real recursive resolution for <code>{_esc(qname)} {_esc(qtype)}</code>
    against Cascade's own root &rarr; TLD &rarr; authoritative fake internet.</div>

  <div class="summary">
    <span class="status-badge">{_esc(status)}</span>
    <span class="meta">{len(trace.steps)} step(s) recorded</span>
    <div class="answers">
      {answers_html}
    </div>
  </div>

  <div class="timeline">
    {steps_html}
  </div>

  <footer>Generated by Cascade &middot; every step above is a real UDP/TCP exchange or a real cache lookup, not a diagram.</footer>
</div>
</body>
</html>
"""


def _fmt(rr) -> str:
    from .textfmt import fmt_rr
    return fmt_rr(rr)
