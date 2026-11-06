#!/usr/bin/env python3
"""Render a PDF page with quire and with poppler's pdftoppm, print difference statistics.
usage: compare.py file.pdf [page] [dpi] [password]   (writes /tmp/quire-cmp-*.png)"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from quire import Document
from quire.render import render_page
from quire.compare import diff_stats, load

f = sys.argv[1]
page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
dpi = float(sys.argv[3]) if len(sys.argv) > 3 else 72
pw = sys.argv[4] if len(sys.argv) > 4 else ""
doc = Document(f, pw.encode())
cv = render_page(doc, doc.pages()[page - 1], dpi)
tmp = tempfile.mkdtemp()
open("/tmp/quire-cmp-ours.png", "wb").write(cv.to_png())
cmd = ["pdftoppm", "-r", str(dpi), "-png", "-f", str(page), "-l", str(page)] + (["-upw", pw] if pw else []) + [f, tmp + "/ref"]
subprocess.check_call(cmd)
ref = [x for x in os.listdir(tmp) if x.endswith(".png")][0]
os.replace(tmp + "/" + ref, "/tmp/quire-cmp-ref.png")
print(diff_stats(load("/tmp/quire-cmp-ours.png"), load("/tmp/quire-cmp-ref.png")))
for w in sorted(set(doc.warnings)): print("warning:", w)
