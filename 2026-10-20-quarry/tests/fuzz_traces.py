#!/usr/bin/env python3
"""Feed corrupted traces to qsim: it must never crash, hang, or blow up memory.  usage: fuzz_traces.py BUILD_DIR [CASES]"""
import os, random, struct, subprocess, sys, tempfile, time

build = sys.argv[1]
cases = int(sys.argv[2]) if len(sys.argv) > 2 else 40
random.seed(20261020)
tmp = tempfile.mkdtemp()
base = os.path.join(tmp, "base.qtr")
subprocess.run([os.path.join(build, "qgen"), "web", "-n", "4000", "-s", "9", "-o", base], check=True, capture_output=True)
good = open(base, "rb").read()
bad = 0
t_start = time.time()
for i in range(cases):
    b = bytearray(good[:64 + 40 * 3000])
    mode = i % 4
    if mode == 0:                                   # random byte flips
        for _ in range(200):
            b[random.randrange(len(b))] = random.randrange(256)
    elif mode == 1:                                 # truncation at an arbitrary byte
        b = b[:random.randrange(1, len(b))]
    elif mode == 2:                                 # poisoned fields: huge / zero / all-ones sizes and pointers
        for _ in range(100):
            o = 64 + 40 * random.randrange(3000) + random.choice([0, 16, 24, 32])
            if o + 8 <= len(b):
                b[o:o + 8] = struct.pack("<Q", random.choice([0, 1 << 62, 2**64 - 1, random.getrandbits(40), random.getrandbits(20)]))
    else:                                           # pure noise (sometimes with a valid header)
        b = bytearray(os.urandom(random.randrange(0, 5000)))
        if i % 8 == 3:
            b[:64] = good[:64]
    path = os.path.join(tmp, "fz.qtr")
    open(path, "wb").write(b)
    try:
        r = subprocess.run([os.path.join(build, "qsim"), "compare", path, "--reps", "1"],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("case %d (mode %d): timeout" % (i, mode)); bad += 1; continue
    out = r.stdout + r.stderr
    if r.returncode not in (0, 1, 2) or "FAILED" in out or "BROKEN" in out or "Segmentation" in out:
        print("case %d (mode %d): rc=%d\n%s" % (i, mode, r.returncode, out[-400:])); bad += 1
if bad:
    sys.exit(1)
print("%d corrupted traces replayed without a crash, hang or false integrity failure (%.0fs)" % (cases, time.time() - t_start))
