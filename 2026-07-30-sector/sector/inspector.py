"""Builds a self-contained interactive HTML report for a FAT16 image: the
annotated boot-sector byte layout, the directory tree, and a cluster
allocation map (which clusters belong to which file, which are free).
No server, no network calls, no external JS/CSS — every byte comes from a
real image via FatImage.
"""
import html
import json

# Categorical palette (validated: skills/dataviz reference palette, slots 1-8,
# fixed order, never cycled — the first N owners get distinct hues, the rest
# fold into "Other").
_CATEGORICAL = [
    ("#2a78d6", "#3987e5"),  # 1 blue
    ("#eb6834", "#d95926"),  # 2 orange
    ("#1baf7a", "#199e70"),  # 3 aqua
    ("#eda100", "#c98500"),  # 4 yellow
    ("#e87ba4", "#d55181"),  # 5 magenta
    ("#008300", "#008300"),  # 6 green
    ("#4a3aa7", "#9085e9"),  # 7 violet
    ("#e34948", "#e66767"),  # 8 red
]
_OTHER = ("#898781", "#898781")   # muted ink — "Other" bucket
_FREE = ("#e1e0d9", "#2c2c2a")    # gridline hairline — free cluster


def _bpb_field_rows(bpb):
    bps = bpb.bytes_per_sector
    rows = [
        (0, 3, "jmp_boot", "EB 3C 90 (jump to boot code)"),
        (3, 8, "oem_name", bpb.oem_name),
        (11, 2, "bytes_per_sector", str(bps)),
        (13, 1, "sectors_per_cluster", str(bpb.sectors_per_cluster)),
        (14, 2, "reserved_sector_count", str(bpb.reserved_sector_count)),
        (16, 1, "num_fats", str(bpb.num_fats)),
        (17, 2, "root_entry_count", str(bpb.root_entry_count)),
        (19, 2, "total_sectors_16", str(bpb.total_sectors if bpb.total_sectors < 0x10000 else 0)),
        (21, 1, "media", f"0x{bpb.media:02X}"),
        (22, 2, "fat_size_16", str(bpb.fat_size)),
        (24, 2, "sectors_per_track", str(bpb.sectors_per_track)),
        (26, 2, "num_heads", str(bpb.num_heads)),
        (28, 4, "hidden_sectors", str(bpb.hidden_sectors)),
        (32, 4, "total_sectors_32", str(bpb.total_sectors if bpb.total_sectors >= 0x10000 else 0)),
        (36, 1, "drive_number", f"0x{bpb.drive_number:02X}"),
        (38, 1, "boot_signature", "0x29"),
        (39, 4, "volume_id", f"0x{bpb.volume_id:08X}"),
        (43, 11, "volume_label", bpb.volume_label),
        (54, 8, "fs_type", bpb.fs_type),
        (510, 2, "boot_sector_signature", "0x55AA"),
    ]
    return rows


def _tree_html(nodes, depth=0):
    if not nodes:
        return "<div class='tnode empty'>(empty)</div>"
    out = []
    for n in sorted(nodes, key=lambda n: (not n["is_dir"], n["name"].lower())):
        icon = "📁" if n["is_dir"] else "📄"
        size = "" if n["is_dir"] else f"<span class='tsize'>{n['size']:,}B</span>"
        out.append(
            f"<div class='tnode' style='--depth:{depth}'>"
            f"<span class='ticon'>{icon}</span>"
            f"<span class='tname'>{html.escape(n['name'])}</span>{size}</div>"
        )
        if n["is_dir"]:
            out.append(_tree_html(n["children"], depth + 1))
    return "\n".join(out)


def build_report(img, image_label):
    bpb = img.bpb
    info = img.info()
    tree = img.tree("/")
    owners = img.cluster_owners()

    # Rank owners by cluster count, assign the fixed categorical order to the
    # top slots, fold the rest into "Other" — never a generated/cycled hue.
    counts = {}
    for path in owners.values():
        counts[path] = counts.get(path, 0) + 1
    ranked = sorted(counts, key=lambda p: (-counts[p], p))
    top = ranked[: len(_CATEGORICAL)]
    color_index = {path: i for i, path in enumerate(top)}

    n_clusters = bpb.count_of_clusters
    cells = []
    for c in range(2, n_clusters + 2):
        owner = owners.get(c)
        if owner is None:
            slot = -1
        elif owner in color_index:
            slot = color_index[owner]
        else:
            slot = len(_CATEGORICAL)  # "Other"
        cells.append({"c": c, "owner": owner or "(free)", "slot": slot})

    legend = [{"label": p, "count": counts[p], "slot": i} for i, p in enumerate(top)]
    other_count = sum(1 for c in cells if c["slot"] == len(_CATEGORICAL))
    if other_count:
        legend.append({"label": f"Other ({len(ranked) - len(top)} more)", "count": other_count, "slot": len(_CATEGORICAL)})

    data = {
        "cells": cells,
        "legend": legend,
        "free": info["free_clusters"],
        "total": n_clusters,
    }

    bpb_rows = "".join(
        f"<tr><td class='mono'>{off}</td><td class='mono'>{ln}</td>"
        f"<td class='mono'>{html.escape(name)}</td><td>{html.escape(val)}</td></tr>"
        for off, ln, name, val in _bpb_field_rows(bpb)
    )

    stat_tiles = "".join(
        f"<div class='stat'><div class='stat-label'>{label}</div><div class='stat-value'>{value}</div></div>"
        for label, value in [
            ("Volume label", info["volume_label"] or "(none)"),
            ("Total size", f"{info['total_bytes']:,} B"),
            ("Cluster size", f"{info['cluster_size']} B"),
            ("Clusters", f"{info['count_of_clusters']:,}"),
            ("Free space", f"{info['free_bytes']:,} B"),
            ("FAT copies", str(info["num_fats"])),
        ]
    )

    return _TEMPLATE.format(
        title=html.escape(image_label),
        stat_tiles=stat_tiles,
        bpb_rows=bpb_rows,
        tree_html=_tree_html(tree),
        data_json=json.dumps(data),
        categorical_json=json.dumps([{"light": l, "dark": d} for l, d in _CATEGORICAL]),
        other_light=_OTHER[0], other_dark=_OTHER[1],
        free_light=_FREE[0], free_dark=_FREE[1],
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sector — {title}</title>
<style>
  :root {{
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7; --text-primary: #0b0b0b;
    --text-secondary: #52514e; --muted: #898781; --grid: #e1e0d9;
    --border: rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff;
      --text-secondary: #c3c2b7; --muted: #898781; --grid: #2c2c2a;
      --border: rgba(255,255,255,0.10);
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d; --text-primary: #ffffff;
    --text-secondary: #c3c2b7; --muted: #898781; --grid: #2c2c2a;
    --border: rgba(255,255,255,0.10);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px; background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; margin: 0 0 12px; color: var(--text-secondary); font-weight: 600; }}
  .sub {{ color: var(--text-secondary); font-size: 13px; margin-bottom: 24px; }}
  .card {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 20px; margin-bottom: 20px; overflow-x: auto;
  }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .stat {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; min-width: 140px;
  }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }}
  .stat-value {{ font-size: 18px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ text-align: left; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase;
        padding: 6px 10px; border-bottom: 1px solid var(--grid); }}
  td {{ padding: 5px 10px; border-bottom: 1px solid var(--grid); }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--text-secondary); }}
  .tnode {{ padding: 3px 0; padding-left: calc(var(--depth) * 20px); font-size: 13px; }}
  .ticon {{ margin-right: 6px; }}
  .tsize {{ color: var(--muted); margin-left: 8px; font-size: 12px; font-variant-numeric: tabular-nums; }}
  .empty {{ color: var(--muted); font-style: italic; }}
  #grid-wrap {{ max-height: 340px; overflow-y: auto; border: 1px solid var(--grid); border-radius: 6px; padding: 8px; }}
  #grid {{ display: grid; grid-template-columns: repeat(auto-fill, 7px); gap: 1px; }}
  .cell {{ width: 7px; height: 7px; border-radius: 1px; cursor: default; }}
  #tooltip {{
    position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1);
    font-size: 12px; padding: 4px 8px; border-radius: 6px; display: none; z-index: 10;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 14px; font-size: 12px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 3px; flex: none; }}
  .legend-label {{ color: var(--text-secondary); }}
  .legend-count {{ color: var(--muted); font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>Sector — disk inspector</h1>
<div class="sub">{title}</div>

<div class="card">
  <h2>Volume summary</h2>
  <div class="stats">{stat_tiles}</div>
</div>

<div class="card">
  <h2>Boot sector / BIOS Parameter Block</h2>
  <table>
    <tr><th>Offset</th><th>Bytes</th><th>Field</th><th>Value</th></tr>
    {bpb_rows}
  </table>
</div>

<div class="card">
  <h2>Directory tree</h2>
  {tree_html}
</div>

<div class="card">
  <h2>Cluster allocation map</h2>
  <div class="sub" style="margin-bottom:12px">Each square is one cluster, in on-disk order; hover for its owner. Scroll for the rest — most of a freshly-written volume is free space.</div>
  <div id="grid-wrap"><div id="grid"></div></div>
  <div class="legend" id="legend"></div>
</div>

<div id="tooltip"></div>

<script>
const DATA = {data_json};
const CATEGORICAL = {categorical_json};
const OTHER = {{light: "{other_light}", dark: "{other_dark}"}};
const FREE = {{light: "{free_light}", dark: "{free_dark}"}};

function isDark() {{
  const t = document.documentElement.getAttribute("data-theme");
  if (t === "dark") return true;
  if (t === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}}

function colorFor(slot) {{
  const dark = isDark();
  if (slot === -1) return dark ? FREE.dark : FREE.light;
  if (slot < CATEGORICAL.length) return dark ? CATEGORICAL[slot].dark : CATEGORICAL[slot].light;
  return dark ? OTHER.dark : OTHER.light;
}}

const grid = document.getElementById("grid");
const tooltip = document.getElementById("tooltip");
DATA.cells.forEach(cell => {{
  const div = document.createElement("div");
  div.className = "cell";
  div.style.background = colorFor(cell.slot);
  div.addEventListener("mousemove", e => {{
    tooltip.style.display = "block";
    tooltip.style.left = (e.clientX + 12) + "px";
    tooltip.style.top = (e.clientY + 12) + "px";
    tooltip.textContent = `cluster ${{cell.c}} — ${{cell.owner}}`;
  }});
  div.addEventListener("mouseleave", () => {{ tooltip.style.display = "none"; }});
  grid.appendChild(div);
}});

const legend = document.getElementById("legend");
DATA.legend.forEach(item => {{
  const el = document.createElement("div");
  el.className = "legend-item";
  const sw = document.createElement("div");
  sw.className = "swatch";
  sw.style.background = colorFor(item.slot);
  el.appendChild(sw);
  const label = document.createElement("span");
  label.className = "legend-label";
  label.textContent = item.label;
  el.appendChild(label);
  const count = document.createElement("span");
  count.className = "legend-count";
  count.textContent = `(${{item.count}} cluster${{item.count === 1 ? "" : "s"}})`;
  el.appendChild(count);
  legend.appendChild(el);
}});
const freeSw = document.createElement("div");
freeSw.className = "legend-item";
freeSw.innerHTML = `<div class="swatch" style="background:${{colorFor(-1)}}"></div>` +
  `<span class="legend-label">Free</span><span class="legend-count">(${{DATA.free}} clusters)</span>`;
legend.appendChild(freeSw);
</script>
</body>
</html>
"""
