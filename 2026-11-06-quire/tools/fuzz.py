#!/usr/bin/env python3
"""Mutation fuzzer: corrupt fixture PDFs and make sure quire only ever fails with PdfError/CryptError
(never an unhandled exception) and never hangs. usage: fuzz.py [iterations] [seed]"""
import os, random, signal, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from quire import Document, PdfError
from quire.crypt import CryptError
from quire.text import extract_text
from quire.render import render_page

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
rnd = random.Random(seed)
fx = os.path.join(HERE, "..", "tests", "fixtures")
srcs = [(open(os.path.join(fx, n), "rb").read(), pw) for n, pw in
        (("chrome.pdf", b""), ("libreoffice.pdf", b""), ("enc_aes128_openuser.pdf", b""), ("enc_rc4_128.pdf", b"userpw"))]

def alarm(*_): raise TimeoutError("hang")
signal.signal(signal.SIGALRM, alarm)

def mutate(data):
    d = bytearray(data)
    k = rnd.random()
    if k < 0.3:
        for _ in range(rnd.randint(1, 30)):
            d[rnd.randrange(len(d))] = rnd.randrange(256)
    elif k < 0.5:
        d = d[:rnd.randrange(len(d) // 4, len(d))]
    elif k < 0.7:
        i = rnd.randrange(len(d)); j = min(len(d), i + rnd.randint(1, 2000)); del d[i:j]
    elif k < 0.85:
        i = rnd.randrange(len(d)); d[i:i] = os.urandom(rnd.randint(1, 200))
    else:
        i = rnd.randrange(len(d)); j = rnd.randrange(len(d)); d[i:i + 50] = d[j:j + 50]
    return bytes(d)

bad = 0
t0 = time.time()
for it in range(N):
    src, pw = rnd.choice(srcs)
    data = mutate(src)
    signal.alarm(20)
    try:
        doc = Document(data, pw)
        extract_text(doc)
        pg = doc.pages()
        if pg:
            render_page(doc, pg[0], 40)
    except (PdfError, CryptError):
        pass
    except TimeoutError:
        bad += 1; print(f"[{it}] HANG"); open(f"/tmp/fuzz-hang-{seed}-{it}.pdf", "wb").write(data)
    except Exception:
        bad += 1; print(f"[{it}] CRASH"); traceback.print_exc(limit=4); open(f"/tmp/fuzz-crash-{seed}-{it}.pdf", "wb").write(data)
    finally:
        signal.alarm(0)
print(f"{N} mutants, {bad} problems, {time.time()-t0:.0f}s")
sys.exit(1 if bad else 0)
