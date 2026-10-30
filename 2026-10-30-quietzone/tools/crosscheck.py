"""Independent cross-check of Quietzone against two third-party implementations.

  A) qz encode  ->  OpenCV QRCodeDetector decodes    (is our encoder spec-correct?)
  B) segno render -> qz scan decodes                  (is our scanner/decoder real?)
  C) segno render + distortion -> qz scan             (robustness on foreign symbols)

Usage: python3.13 crosscheck.py /path/to/qz [n]
Exit status 1 on any mismatch.
"""
import os, random, subprocess, sys, tempfile
import cv2, numpy as np, segno

qz = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
rng = random.Random(2026)
tmp = tempfile.mkdtemp()
ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 $%*+-./:"
WORDS = "abcdefghijklmnopqrstuvwxyz0123456789 .,:/?=&_-é✓"

def payload():
    kind = rng.randrange(4)
    k = rng.randrange(1, 220)
    if kind == 0: return "".join(rng.choice("0123456789") for _ in range(k * 2))
    if kind == 1: return "".join(rng.choice(ALNUM) for _ in range(k))
    if kind == 2: return "".join(rng.choice(WORDS[:-2]) for _ in range(k))
    return "".join(rng.choice(WORDS) for _ in range(max(1, k // 3)))

def run(*a, **kw):
    kw.setdefault('stdin', subprocess.DEVNULL)
    return subprocess.run([qz, *a], capture_output=True, text=True, **kw)

fails = 0
det = cv2.QRCodeDetector()

# A) ours -> OpenCV
a_ok = 0
for i in range(n):
    text, ecc = payload(), rng.choice("LMQH")
    png = os.path.join(tmp, f"a{i}.png")
    r = subprocess.run([qz, "encode", "-ecc", ecc, "-o", png, "-scale", "6", "-"], input=text, capture_output=True, text=True)
    if r.returncode:
        print("A: encode failed", ecc, len(text), r.stderr.strip()); fails += 1; continue
    img = cv2.imread(png)
    got, _, _ = det.detectAndDecode(img)
    if got == text: a_ok += 1
    else:
        fails += 1; print(f"A: OpenCV mismatch ecc={ecc} len={len(text)}: {got[:30]!r} vs {text[:30]!r}")
print(f"A) OpenCV decodes our symbols: {a_ok}/{n}")

# B) segno -> ours
b_ok = 0
for i in range(n):
    text = payload()
    ecc = rng.choice("lmqh")
    png = os.path.join(tmp, f"b{i}.png")
    try:
        segno.make(text, error=ecc, micro=False, encoding="utf-8").save(png, scale=rng.choice([4, 6, 9]), border=4)
    except Exception as e:
        continue
    r = run("decode", png)
    if r.returncode == 0 and r.stdout.rstrip("\n") == text: b_ok += 1
    else:
        fails += 1; print(f"B: qz mismatch ecc={ecc} len={len(text)}: rc={r.returncode} {r.stdout[:30]!r} {r.stderr.strip()[:60]}")
print(f"B) qz reads segno's symbols: {b_ok}/{n}")

# C) segno + distortion -> ours
c_ok = c_total = 0
for i in range(n):
    text = payload()[:120]
    png, dst = os.path.join(tmp, f"c{i}.png"), os.path.join(tmp, f"cd{i}.png")
    try:
        segno.make(text, error="q", micro=False, encoding="utf-8").save(png, scale=8, border=4)
    except Exception:
        continue
    args = ["distort", "-roll", str(rng.uniform(-180, 180)), "-tiltx", str(rng.uniform(-25, 25)), "-tilty", str(rng.uniform(-25, 25)),
            "-blur", "1.2", "-noise", "10", "-seed", str(i), png, dst]
    run(*args)
    c_total += 1
    r = run("decode", dst)
    if r.returncode == 0 and r.stdout.rstrip("\n") == text: c_ok += 1
    else: print(f"C: distorted segno symbol not read (len {len(text)}): {r.stderr.strip()[:60]}")
print(f"C) qz reads distorted segno symbols: {c_ok}/{c_total}")
if c_total and c_ok / c_total < 0.95: fails += 1
sys.exit(1 if fails else 0)
