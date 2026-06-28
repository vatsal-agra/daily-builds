"""
Level visualizer — generates a self-contained HTML page showing the current
LSM-tree state: file distribution across levels, key ranges, sizes, and
Bloom filter parameters. No external dependencies.
"""

from pathlib import Path
from typing import Optional
import json


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.1f} GB"


def generate_html(db) -> str:
    """Generate an HTML visualization of the DB's level structure."""
    info = db.info()

    # Gather detailed file info
    level_details = {}
    for level, lstats in info["levels"].items():
        files = []
        for fname in lstats["filenames"]:
            p = db._dir / fname
            if not p.exists():
                continue
            from .sstable import SSTableReader
            try:
                r = SSTableReader(p)
                files.append({
                    "name": fname,
                    "size": p.stat().st_size,
                    "min_key": r.min_key.decode("utf-8", errors="replace") if r.min_key else "",
                    "max_key": r.max_key.decode("utf-8", errors="replace") if r.max_key else "",
                    "bloom_k": r._bloom.k,
                    "bloom_m": r._bloom.m,
                    "blocks": len(r._index),
                })
                r.close()
            except Exception as e:
                files.append({"name": fname, "size": 0, "min_key": "", "max_key": "",
                              "bloom_k": 0, "bloom_m": 0, "blocks": 0, "error": str(e)})
        level_details[level] = files

    # Compute total read amplification (worst case files checked per get)
    l0_files = len(info["levels"].get(0, {}).get("filenames", []))
    non_l0_levels = sum(1 for l in info["levels"] if l > 0)
    read_amp = l0_files + non_l0_levels

    data = {
        "memtable_size": info["memtable_size"],
        "memtable_entries": info["memtable_entries"],
        "next_seq": info["next_seq"],
        "levels": level_details,
        "read_amp": read_amp,
        "db_dir": info["db_dir"],
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Strata — LSM Level Visualizer</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'SF Mono', 'Consolas', monospace; background: #0d1117; color: #e6edf3;
       padding: 24px; font-size: 13px; line-height: 1.5; }}
h1 {{ font-size: 20px; color: #58a6ff; margin-bottom: 4px; }}
.subtitle {{ color: #8b949e; margin-bottom: 24px; font-size: 12px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
         gap: 12px; margin-bottom: 28px; }}
.card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
         padding: 16px; }}
.card-label {{ color: #8b949e; font-size: 11px; text-transform: uppercase;
               letter-spacing: 0.05em; margin-bottom: 6px; }}
.card-value {{ color: #e6edf3; font-size: 22px; font-weight: 600; }}
.card-sub {{ color: #8b949e; font-size: 11px; margin-top: 2px; }}
h2 {{ font-size: 15px; color: #79c0ff; margin: 20px 0 12px; border-bottom: 1px solid #21262d;
      padding-bottom: 8px; }}
.level {{ margin-bottom: 20px; }}
.level-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
.level-tag {{ background: #1f6feb; color: #cae8ff; border-radius: 4px;
              padding: 2px 8px; font-size: 12px; font-weight: 600; }}
.level-tag.l0 {{ background: #da3633; color: #ffd0c6; }}
.level-tag.l1 {{ background: #388bfd; color: #cae8ff; }}
.level-tag.l2 {{ background: #3fb950; color: #c6efce; }}
.level-tag.l3 {{ background: #d29922; color: #fef3c7; }}
.level-stat {{ color: #8b949e; font-size: 12px; }}
.file-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
              gap: 8px; }}
.file-card {{ background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
              padding: 10px 12px; }}
.file-name {{ color: #79c0ff; font-size: 11px; margin-bottom: 6px; }}
.file-range {{ color: #a5d6ff; font-size: 11px; margin-bottom: 4px; }}
.file-meta {{ color: #8b949e; font-size: 10px; }}
.bar-wrap {{ background: #21262d; border-radius: 4px; height: 6px;
             margin: 8px 0 4px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.empty-state {{ color: #484f58; font-style: italic; padding: 8px 0; }}
.memtable-bar {{ height: 8px; background: #21262d; border-radius: 4px;
                 margin-top: 8px; overflow: hidden; }}
.memtable-fill {{ height: 100%; background: linear-gradient(90deg, #388bfd, #79c0ff);
                  border-radius: 4px; transition: width 0.4s; }}
.amp-badge {{ display: inline-flex; align-items: center; gap: 6px; background: #161b22;
              border: 1px solid #30363d; border-radius: 6px; padding: 6px 12px;
              margin-top: 8px; }}
.amp-value {{ color: #f78166; font-weight: 700; font-size: 18px; }}
.amp-label {{ color: #8b949e; font-size: 12px; }}
footer {{ margin-top: 32px; color: #484f58; font-size: 11px; border-top: 1px solid #21262d;
          padding-top: 16px; }}
</style>
</head>
<body>
<h1>&#8963; Strata LSM-tree Visualizer</h1>
<div class="subtitle">Database: {data['db_dir']} &nbsp;|&nbsp; Sequence: {data['next_seq']}</div>

<div class="grid">
  <div class="card">
    <div class="card-label">MemTable</div>
    <div class="card-value">{data['memtable_entries']}</div>
    <div class="card-sub">entries in memory</div>
    <div class="memtable-bar">
      <div class="memtable-fill" style="width:{min(100, data['memtable_size'] * 100 // (4*1024*1024 + 1))}%"></div>
    </div>
    <div class="card-sub">{_format_bytes(data['memtable_size'])} / ~4 MB</div>
  </div>
  <div class="card">
    <div class="card-label">Total Levels</div>
    <div class="card-value">{len(data['levels'])}</div>
    <div class="card-sub">{sum(len(v) for v in data['levels'].values())} SSTable files</div>
  </div>
  <div class="card">
    <div class="card-label">Read Amplification</div>
    <div class="card-value" style="color:#f78166">{data['read_amp']}×</div>
    <div class="card-sub">worst-case files per GET</div>
  </div>
  <div class="card">
    <div class="card-label">Total On-Disk</div>
    <div class="card-value">{_format_bytes(sum(f['size'] for lvl in data['levels'].values() for f in lvl))}</div>
    <div class="card-sub">across all levels</div>
  </div>
</div>

<h2>Level Structure</h2>
"""

    level_colors = {0: "#da3633", 1: "#388bfd", 2: "#3fb950", 3: "#d29922"}
    level_budgets = {1: 10*1024*1024, 2: 100*1024*1024, 3: 1024*1024*1024}

    for level in sorted(data["levels"].keys()):
        files = data["levels"][level]
        total_bytes = sum(f["size"] for f in files)
        budget = level_budgets.get(level, 10**level * 1024 * 1024)
        fill_pct = min(100, total_bytes * 100 // budget) if budget > 0 else 0
        color = level_colors.get(level, "#8b949e")
        tag_class = f"l{level}" if level < 4 else ""

        html += f"""
<div class="level">
  <div class="level-header">
    <span class="level-tag {tag_class}">L{level}</span>
    <span class="level-stat">{len(files)} file{'s' if len(files) != 1 else ''} &nbsp;·&nbsp; {_format_bytes(total_bytes)}</span>
  </div>
"""
        if level > 0:
            html += f"""  <div class="bar-wrap">
    <div class="bar-fill" style="width:{fill_pct}%; background:{color}"></div>
  </div>
  <div class="card-sub" style="margin-bottom:8px">{_format_bytes(total_bytes)} / {_format_bytes(budget)} budget ({fill_pct}%)</div>
"""

        if not files:
            html += '  <div class="empty-state">(empty)</div>\n'
        else:
            html += '  <div class="file-grid">\n'
            for f in files:
                min_k = f.get("min_key", "")[:24]
                max_k = f.get("max_key", "")[:24]
                html += f"""    <div class="file-card">
      <div class="file-name">📦 {f['name']}</div>
      <div class="file-range">Range: <b>{min_k!r}</b> … <b>{max_k!r}</b></div>
      <div class="file-meta">{_format_bytes(f['size'])} &nbsp;|&nbsp; {f['blocks']} blocks &nbsp;|&nbsp; Bloom: k={f['bloom_k']}, m={f['bloom_m']}</div>
    </div>
"""
            html += '  </div>\n'
        html += '</div>\n'

    html += """
<footer>
  Strata LSM-tree Key-Value Store &mdash; built 2026-06-28<br>
  Data model: MemTable (in-memory MVCC) + WAL (CRC-checked) + SSTables (Bloom + Index) + Leveled Compaction
</footer>
</body>
</html>"""

    return html


def serve_visualizer(db, port: int = 8765) -> None:
    """Serve the visualizer HTML on a local HTTP server."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            html = generate_html(db).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, fmt, *args):
            pass  # suppress access log

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"Visualizer running at http://127.0.0.1:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
