"""Regenerate tests/fixtures. Needs: node+playwright (Chromium), libreoffice, and (for the
encrypted/object-stream variants) a Python with `pypdf` + `cryptography`. Run:  python3 tools/make_fixtures.py
Fixtures are checked in, so none of this is needed to run the test-suite."""
import os, subprocess, sys, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "..", "tests", "fixtures")
os.makedirs(FX, exist_ok=True)

HTML = r"""<!doctype html><html><head><meta charset=utf-8><style>
@page{size:A4;margin:18mm}
body{font-family:'DejaVu Serif',serif;font-size:11pt;line-height:1.35}
h1{font-family:'DejaVu Sans',sans-serif;font-size:22pt;margin:0 0 6pt;color:#12356b}
.cols{column-count:2;column-gap:14mm;text-align:left}
.box{border:2px solid #b00;background:#fde;padding:6px;margin:8px 0;border-radius:6px}
.bar{height:14px;background:linear-gradient(90deg,#08f,#f80);margin:6px 0}
svg{display:block;margin:8px 0}
pre{font-family:'DejaVu Sans Mono',monospace;font-size:9pt;background:#eee;padding:4px}
.pb{page-break-before:always}
td,th{border:1px solid #444;padding:2px 8px}table{border-collapse:collapse}
</style></head><body>
<h1>Quire Test Document</h1>
<p>The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. ÀÉÎÕÜ àéîõü ß ñ — “quotes” and an ellipsis… fi fl ffi</p>
<div class=bar></div>
<div class=cols><p>Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.</p>
<p>Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.</p>
<p>Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam.</p></div>
<div class=box>Boxed callout with a red border and rounded corners.</div>
<svg width=300 height=90 viewBox="0 0 300 90"><path d="M10 80 C 60 -10, 120 120, 180 20 S 280 90 290 10" stroke="#063" stroke-width="3" fill="none" stroke-dasharray="8 4"/><circle cx=60 cy=45 r=28 fill="#36c" fill-opacity=".6"/><polygon points="200,80 240,20 280,80" fill="#c63" stroke="#000" stroke-width="2" stroke-linejoin="round"/><path d="M120 40 h40 v20 h-40 z M128 46 h24 v8 h-24 z" fill="#222" fill-rule="evenodd"/></svg>
<table><tr><th>Item</th><th>Qty</th><th>Price</th></tr><tr><td>Widget</td><td>12</td><td>$3.50</td></tr><tr><td>Gadget</td><td>7</td><td>$12.00</td></tr></table>
<pre>def hello():
    return "monospace text"</pre>
<p style="transform:rotate(-8deg);transform-origin:left;font-size:16pt;color:#a0a">Rotated purple sentence.</p>
<p class=pb>Page two begins here. <b>Bold text</b>, <i>italic text</i>, and <span style="font-family:'DejaVu Sans'">sans-serif text</span>.</p>
<img width=120 height=60 src="data:image/png;base64,__PNG__">
</body></html>"""

def png_b64():
    import zlib, struct, base64
    w, h = 24, 12
    rows = b"".join(b"\0" + b"".join(bytes([int(255*x/w), int(255*y/h), 128, 255 if (x+y)%7 else 90]) for x in range(w)) for y in range(h))
    def ch(t, d): c = struct.pack(">I", len(d)) + t + d; return c + struct.pack(">I", zlib.crc32(t+d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + ch(b"IDAT", zlib.compress(rows)) + ch(b"IEND", b"")
    return base64.b64encode(png).decode()

def chromium():
    tmp = tempfile.mkdtemp()
    open(tmp + "/t.html", "w").write(HTML.replace("__PNG__", png_b64()))
    js = f"""const {{chromium}}=require('playwright');(async()=>{{const b=await chromium.launch();const p=await b.newPage();
await p.goto('file://{tmp}/t.html');await p.pdf({{path:'{FX}/chrome.pdf',format:'A4',printBackground:true,preferCSSPageSize:true}});await b.close()}})()"""
    open(tmp + "/g.js", "w").write(js)
    subprocess.check_call(["node", tmp + "/g.js"], env={**os.environ, "NODE_PATH": subprocess.check_output(["npm", "root", "-g"]).decode().strip()})

def libreoffice():
    tmp = tempfile.mkdtemp()
    open(tmp + "/lo.html", "w").write(HTML.replace("__PNG__", png_b64()).replace("<svg", "<!--").replace("</svg>", "-->"))
    subprocess.check_call(["libreoffice", "--headless", "--convert-to", "pdf:writer_web_pdf_Export", "--outdir", tmp, tmp + "/lo.html"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.copy(tmp + "/lo.pdf", FX + "/libreoffice.pdf")

def pypdf_variants():
    from pypdf import PdfReader, PdfWriter
    for name, kw in [("rc4_40", dict(algorithm="RC4-40")), ("rc4_128", dict(algorithm="RC4-128")),
                     ("aes128", dict(algorithm="AES-128")), ("aes256", dict(algorithm="AES-256")),
                     ("aes256_r5", dict(algorithm="AES-256-R5"))]:
        w = PdfWriter(clone_from=FX + "/chrome.pdf")
        w.encrypt(user_password="userpw", owner_password="ownerpw", **kw)
        w.write(FX + f"/enc_{name}.pdf")
    w = PdfWriter(clone_from=FX + "/chrome.pdf")
    w.encrypt(user_password="", owner_password="ownerpw", algorithm="AES-128")
    w.write(FX + "/enc_aes128_openuser.pdf")

if __name__ == "__main__":
    which = sys.argv[1:] or ["chromium", "libreoffice", "pypdf"]
    if "chromium" in which: chromium()
    if "libreoffice" in which: libreoffice()
    if "pypdf" in which: pypdf_variants()
