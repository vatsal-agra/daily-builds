#!/usr/bin/env python3
"""Mutation check: apply one small bug at a time to a scratch copy of the module and
require the Go test suite to notice. Prints KILLED/SURVIVED per mutant; exit 1 if any survive."""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# (file, old, new, package, description) — `old` must occur exactly once
MUTANTS = [
    ("raster/fill.go", "wind += int(c.dir)", "wind = 1 - wind", "./raster", "even-odd instead of non-zero winding"),
    ("raster/fill.go", "acc[ia] += (float64(ia+1) - xa) * wt\n", "acc[ia] += (float64(ia+1) - xa) * wt * 0.9\n", "./raster", "left-edge pixel coverage under-counted"),
    ("raster/path.go", "(4 * tol)", "(400 * tol)", "./raster", "curves flattened 10x too coarsely"),
    ("raster/lcd.go", "{8.0 / 256, 77.0 / 256, 86.0 / 256, 77.0 / 256, 8.0 / 256}", "{8.0 / 256, 77.0 / 256, 86.0 / 256, 8.0 / 256, 77.0 / 256}", "./raster", "LCD filter taps asymmetric"),
    ("ttf/glyf.go", "d = -d", "d = d", "./ttf", "short x/y deltas lose their sign"),
    ("ttf/glyf.go", "if _, lsb := f.hmtx(int(gid)); lsb != i16(g, 2) {", "if false {", "./ttf", "left-side-bearing shift removed"),
    ("ttf/glyf.go", "a, b, c, d = f2(p), f2(p+2), f2(p+4), f2(p+6)", "a, c, b, d = f2(p), f2(p+2), f2(p+4), f2(p+6)", "./ttf", "2x2 composite matrix transposed"),
    ("ttf/glyf.go", "dx, dy = pp.X-cp.X, pp.Y-cp.Y", "dx, dy = cp.X-pp.X, cp.Y-pp.Y", "./ttf", "point-matching offset reversed"),
    ("ttf/cmap.go", "return (int(r) + delta) & 0xFFFF", "return (int(r) - delta) & 0xFFFF", "./ttf", "cmap4 idDelta sign"),
    ("ttf/cmap.go", "return startG + int(r) - start", "return startG + int(r) - start + 1", "./ttf", "cmap12 glyph off by one"),
    ("ttf/kern.go", "n += 2", "n += 4", "./ttf", "GPOS value-record size wrong"),
    ("ttf/kern.go", "format == 0 && horizontal && !minimum && !cross &&", "format == 0 && horizontal && !minimum &&", "./ttf", "cross-stream kerning applied"),
    ("ttf/kern.go", "return xAdvanceOf(d, ps.recBase+rec*(c1*ps.c2n+c2), ps.valFmt1), true", "return xAdvanceOf(d, ps.recBase+rec*(c2*ps.c1n+c1), ps.valFmt1), true", "./ttf", "PairPos2 class matrix transposed"),
    ("ttf/build.go", "b.Write(be16(p.v & 0xFFFF))", "b.Write(be16(-p.v & 0xFFFF))", "./ttf", "kern value sign flipped on write"),
    ("ttf/build.go", "adj := 0xB1B0AFBA - Checksum(b)", "adj := 0xB1B0AFBA - Checksum(b) + 1", "./ttf", "head.checksumAdjustment wrong"),
    ("layout/layout.go", "x += float64(f.Kerning(it.gid, seg[i+1].gid)) * scale", "x -= float64(f.Kerning(it.gid, seg[i+1].gid)) * scale", "./layout", "kerning applied backwards"),
    ("layout/layout.go", "extra = (o.Width - width) / float64(gaps)", "extra = (o.Width - width) / float64(gaps+1)", "./layout", "justification under-fills the line"),
    ("layout/layout.go", "x0 = o.Width - width", "x0 = o.Width - width - 1", "./layout", "right alignment off by a pixel"),
    ("img/png.go", "dst[i] = cur[i] - b\n", "dst[i] = cur[i] - a\n", "./img", "PNG Up filter wrong"),
    ("img/png.go", "binary.BigEndian.PutUint32(tail[:], crc.Sum32())", "binary.BigEndian.PutUint32(tail[:], crc.Sum32()+1)", "./img", "PNG chunk CRC corrupted"),
    ("img/canvas.go", "l := toLinear[c.Pix[i+k]]*(1-a) + toLinear[fg]*a", "l := toLinear[c.Pix[i+k]]*a + toLinear[fg]*(1-a)", "./img", "gamma blend weights swapped"),
    ("render/sdf.go", "v := math.Round(255 * (0.5 + d/(2*float64(spread))))", "v := math.Round(255 * (0.4 + d/(2*float64(spread))))", "./render", "SDF zero level shifted"),
    ("render/render.go", "cv.Blend(p.bm, pad-minX+p.px, pad-minY+p.py, st.FG, st.Gamma)", "cv.Blend(p.bm, pad-minX+p.px+1, pad-minY+p.py, st.FG, st.Gamma)", "./render", "glyph bitmaps drawn one pixel off"),
]

def main():
    survivors = 0
    work = tempfile.mkdtemp()
    try:
        for file, old, new, pkg, desc in MUTANTS:
            src = os.path.join(HERE, file)
            text = open(src).read()
            if text.count(old) != 1:
                print(f"BROKEN    {desc}: pattern occurs {text.count(old)}x in {file}")
                survivors += 1
                continue
            dst = os.path.join(work, "src")
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("*.png", "*.html"))
            open(os.path.join(dst, file), "w").write(text.replace(old, new))
            r = subprocess.run(["go", "test", "-count=1", pkg], cwd=dst, capture_output=True, text=True)
            if r.returncode == 0:
                print(f"SURVIVED  {desc}  [{file}]")
                survivors += 1
            else:
                print(f"KILLED    {desc}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"survivors: {survivors} / {len(MUTANTS)}")
    return 1 if survivors else 0

if __name__ == "__main__":
    sys.exit(main())
