#!/usr/bin/env python3
"""Render every gallery case with quire and poppler; print stats (+ write PNGs to /tmp/quire-gallery)."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); sys.path.insert(0, os.path.join(HERE, "..", "tests"))
from quire import Document
from quire.render import render_page
from quire.compare import diff_stats, load
from quire.raster import read_png_rgb
import gallery
out = "/tmp/quire-gallery"; os.makedirs(out, exist_ok=True)
only = sys.argv[1:] 
for name in gallery.CASES:
    if only and name not in only: continue
    data = gallery.build(name)
    pdf = f"{out}/{name}.pdf"; open(pdf, "wb").write(data)
    d = Document(data)
    cv = render_page(d, d.pages()[0], 72 * 2)
    open(f"{out}/{name}-ours.png", "wb").write(cv.to_png())
    subprocess.check_call(["pdftoppm", "-cropbox", "-r", "144", "-png", "-singlefile", pdf, f"{out}/{name}-ref"])
    s = diff_stats(read_png_rgb(cv.to_png()), load(f"{out}/{name}-ref.png"))
    print(f"{name:22} mad={s['mad']:6.2f} bad={s['bad_frac']*100:6.2f}%  {sorted(set(d.warnings))[:2]}")
