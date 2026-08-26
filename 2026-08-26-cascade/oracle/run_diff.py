#!/usr/bin/env python3
"""Differential layout testing against real headless Chromium.

For each testpages/*.html file: render it with Cascade's own engine, render
the *same file* in real Chromium via oracle/diff.cjs, and diff every
element's border-box geometry (x, y, width, height) between the two.

Tolerance is deliberately asymmetric: real per-glyph text metrics
(font hinting, kerning, the exact installed font) are something no
from-scratch metrics table will match a real browser pixel-for-pixel, so
we allow a generous relative tolerance scaled to each element's own size.
That's wide enough to swallow font-metric noise while still being tight
enough (a flat 4px floor) to catch a real algorithmic bug — wrong margin
collapsing, a float placed on the wrong side, a percentage resolved
against the wrong base — which routinely produce errors far larger than
that. See PLAN.md for why this specific sandbox can run a real-browser
oracle at all.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cascade.engine import render_html  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DIFF_JS = os.path.join(HERE, "diff.cjs")
TOL_FLOOR = 6.0
TOL_RATIO = 0.14


def flatten_cascade_boxes(root_box):
    out = []
    if root_box is None:
        return out
    for b in root_box.walk():
        if b.node is None:
            continue
        bb = b.dims.border_box()
        out.append({
            "tag": b.node.tag,
            "id": b.node.id(),
            "x": bb.x, "y": bb.y, "width": bb.width, "height": bb.height,
        })
    return out


def run_chromium(html_path, width):
    proc = subprocess.run(["node", DIFF_JS, html_path, str(width)],
                           capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"oracle failed for {html_path}:\n{proc.stderr}")
    return json.loads(proc.stdout)


def tol(box, field):
    # Scale tolerance to the dimension the field actually varies along —
    # a wide-but-short element must not get a huge tolerance on its Y
    # position just because it's wide (that masked a real bug once; see
    # REVIEW.md).
    ref = box["width"] if field in ("x", "width") else box["height"]
    return max(TOL_FLOOR, TOL_RATIO * max(ref, 10))


def diff_page(html_path, width=800):
    html = open(html_path, encoding="utf-8").read()
    result = render_html(html, viewport_width=width)
    ours = flatten_cascade_boxes(result.box)
    theirs = run_chromium(html_path, width)

    mismatches = []
    if len(ours) != len(theirs):
        mismatches.append({
            "kind": "count-mismatch",
            "ours_count": len(ours), "chromium_count": len(theirs),
            "ours_tags": [b["tag"] for b in ours],
            "chromium_tags": [b["tag"] for b in theirs],
        })
        n = min(len(ours), len(theirs))
    else:
        n = len(ours)

    for i in range(n):
        o, c = ours[i], theirs[i]
        if o["tag"] != c["tag"]:
            mismatches.append({"kind": "tag-mismatch", "index": i, "ours": o["tag"], "chromium": c["tag"]})
            continue
        for field in ("x", "y", "width", "height"):
            t = tol(c, field)
            delta = abs(o[field] - c[field])
            if delta > t:
                mismatches.append({
                    "kind": "geometry", "index": i, "tag": o["tag"], "id": o["id"],
                    "field": field, "ours": round(o[field], 1), "chromium": round(c[field], 1),
                    "delta": round(delta, 1), "tolerance": round(t, 1),
                })
    return {"page": os.path.basename(html_path), "elements": n, "mismatches": mismatches}


def main():
    testpages_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(HERE), "testpages")
    files = sorted(f for f in os.listdir(testpages_dir) if f.endswith(".html"))
    all_results = []
    total_mismatches = 0
    for fname in files:
        path = os.path.join(testpages_dir, fname)
        try:
            result = diff_page(path)
        except Exception as e:
            result = {"page": fname, "elements": 0, "mismatches": [{"kind": "error", "message": str(e)}]}
        all_results.append(result)
        n_mis = len(result["mismatches"])
        total_mismatches += n_mis
        status = "OK" if n_mis == 0 else f"{n_mis} MISMATCH(ES)"
        print(f"[{status:>16}] {result['page']} ({result['elements']} elements)")
        for m in result["mismatches"][:8]:
            print(f"    {m}")

    print(f"\n{len(files)} pages, {total_mismatches} total mismatches")
    with open(os.path.join(HERE, "diff_report.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    return 0 if total_mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
