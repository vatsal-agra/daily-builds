"""quire command line."""
import argparse
import json
import os
import sys

from .document import Document, PdfError
from .crypt import WrongPassword, CryptError
from .objects import Stream, Ref, Name, PdfString


def _open(args):
    try:
        with open(args.file, "rb") as f:
            data = f.read()
    except OSError as e:
        sys.exit(f"quire: cannot read {args.file}: {e.strerror}")
    pw = (args.password or "").encode("utf-8")
    try:
        return Document(data, pw)
    except WrongPassword:
        sys.exit(f"quire: {args.file}: incorrect password (use -p PASSWORD)" if args.password else
                 f"quire: {args.file} is encrypted and needs a password (use -p PASSWORD)")
    except (PdfError, CryptError) as e:
        sys.exit(f"quire: {args.file}: {e}")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"quire: {args.file}: not a readable PDF ({type(e).__name__}: {e})")


def fmt(o, depth=0, maxlen=300):
    if isinstance(o, Stream):
        return f"<<stream {len(o.raw)} bytes>> " + fmt(o.dict, depth)
    if isinstance(o, dict):
        return "<< " + " ".join(f"/{k} {fmt(v, depth + 1)}" for k, v in o.items()) + " >>"
    if isinstance(o, list):
        return "[" + " ".join(fmt(v, depth + 1) for v in o) + "]"
    if isinstance(o, PdfString):
        try:
            s = bytes(o).decode("utf-16-be") if bytes(o)[:2] == b"\xfe\xff" else bytes(o).decode("latin-1")
        except UnicodeDecodeError:
            s = bytes(o).hex()
        s = s if len(s) <= maxlen else s[:maxlen] + "…"
        return "(" + "".join(c if c.isprintable() else "\\x%02x" % ord(c) for c in s) + ")"
    if isinstance(o, Name):
        return "/" + str(o)
    return repr(o) if not isinstance(o, str) else o


def cmd_info(args):
    doc = _open(args)
    pages = doc.pages()
    print(f"File:        {args.file}")
    print(f"PDF version: {doc.version}")
    print(f"Pages:       {len(pages)}")
    for k, v in doc.info.items():
        print(f"{k + ':':<12} {fmt(doc.resolve(v))}")
    if doc.dec:
        print(f"Encryption:  {doc.dec.describe()}")
        perms = doc.dec.permissions()
        print("Permissions: " + ", ".join(f"{n}={'yes' if v else 'no'}" for n, v in perms.items()))
    else:
        print("Encryption:  none")
    nobj = sum(1 for e in doc.xref.values() if e[0] != "f")
    kinds = {"n": 0, "c": 0}
    for e in doc.xref.values():
        if e[0] in kinds:
            kinds[e[0]] += 1
    print(f"Objects:     {nobj} ({kinds['c']} in object streams)")
    print("Repaired:    " + (f"yes — {doc.repair_reason}" if doc.repaired else "no"))
    for i, p in enumerate(pages[:50]):
        b = doc.page_box(p)
        print(f"  page {i + 1}: {b[2] - b[0]:.1f} x {b[3] - b[1]:.1f} pt, rotate {doc.page_rotate(p)}")
    return 0


def cmd_dump(args):
    doc = _open(args)
    if args.object is None:
        print("trailer:", fmt(doc.trailer))
        for n in sorted(doc.xref):
            if doc.xref[n][0] == "f":
                continue
            o = doc.get_object(n)
            s = fmt(o)
            print(f"{n} 0 obj: {s[:160] + ('…' if len(s) > 160 else '')}")
        return 0
    o = doc.get_object(args.object)
    if o is None:
        sys.exit(f"quire: object {args.object} not found")
    print(fmt(o))
    if isinstance(o, Stream) and args.stream:
        try:
            data = doc.decode_stream(o)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"quire: cannot decode stream: {e}")
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.write(b"\n")
    return 0


def _page_set(spec, n):
    if not spec:
        return None
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out |= set(range(int(a or 1) - 1, int(b or n)))
        else:
            out.add(int(part) - 1)
    bad = [p + 1 for p in out if not 0 <= p < n]
    if bad:
        sys.exit(f"quire: page {bad[0]} out of range (document has {n} pages)")
    return out


def cmd_text(args):
    from .text import extract_text
    doc = _open(args)
    try:
        pages = _page_set(args.pages, len(doc.pages()))
    except ValueError:
        sys.exit(f"quire: bad page list {args.pages!r}")
    txt = extract_text(doc, pages, expand_ligatures=not args.keep_ligatures)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(txt)
    else:
        sys.stdout.write(txt)
        if not txt.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def cmd_render(args):
    from .render import render_page
    doc = _open(args)
    pl = doc.pages()
    try:
        pages = sorted(_page_set(args.pages or "1", len(pl)))
    except ValueError:
        sys.exit(f"quire: bad page list {args.pages!r}")
    if args.dpi <= 0 or args.dpi > 600:
        sys.exit("quire: --dpi must be in (0, 600]")
    out = args.output or os.path.splitext(os.path.basename(args.file))[0]
    hl = {}
    if args.highlight:
        from .text import search_page
        for i in pages:
            hl[i] = [b for m in search_page(doc, i, pl[i], args.highlight) for b in m.boxes]
    for i in pages:
        cv = render_page(doc, pl[i], args.dpi, hl.get(i))
        name = out if (len(pages) == 1 and out.endswith(".png")) else f"{out}-{i + 1}.png"
        with open(name, "wb") as f:
            f.write(cv.to_png())
        print(f"wrote {name} ({cv.w}x{cv.h})")
    for w in sorted(set(doc.warnings)):
        print(f"warning: {w}", file=sys.stderr)
    return 0


def cmd_search(args):
    from .text import search_page
    doc = _open(args)
    total = 0
    for i, p in enumerate(doc.pages()):
        for m in search_page(doc, i, p, args.query, not args.case):
            total += 1
            bb = m.boxes[0]
            print(f"page {i + 1}: {m.text!r} at ({bb[0]:.1f}, {bb[1]:.1f})-({bb[2]:.1f}, {bb[3]:.1f})")
    if not total:
        print("no matches")
        return 1
    return 0


def cmd_decrypt(args):
    from .writer import write_document
    doc = _open(args)
    data = write_document(doc, compress=args.compress)
    with open(args.output, "wb") as f:
        f.write(data)
    print(f"wrote {args.output} ({len(data)} bytes){' [decrypted]' if doc.dec else ''}")
    return 0


def cmd_report(args):
    from .report import build_report
    doc = _open(args)
    html = build_report(doc, args.file, dpi=args.dpi)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.output} ({len(html) // 1024} KiB)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quire", description="From-scratch PDF reader, text extractor and renderer.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("file")
        p.add_argument("-p", "--password", help="user or owner password")
        p.set_defaults(fn=fn)
        return p
    add("info", cmd_info, "document summary")
    p = add("dump", cmd_dump, "print the object table, or one object")
    p.add_argument("object", nargs="?", type=int)
    p.add_argument("--stream", action="store_true", help="also write the decoded stream bytes")
    p = add("text", cmd_text, "extract text in reading order")
    p.add_argument("--pages", help="e.g. 1,3-5")
    p.add_argument("-o", "--output")
    p.add_argument("--keep-ligatures", action="store_true")
    p = add("render", cmd_render, "rasterise pages to PNG")
    p.add_argument("--pages", help="e.g. 1,3-5 (default: 1)")
    p.add_argument("--dpi", type=float, default=72.0)
    p.add_argument("-o", "--output", help="output file/prefix")
    p.add_argument("--highlight", help="highlight occurrences of this text")
    p = add("search", cmd_search, "find text with bounding boxes")
    p.add_argument("query")
    p.add_argument("--case", action="store_true", help="case-sensitive")
    p = add("decrypt", cmd_decrypt, "write a decrypted, cleaned copy")
    p.add_argument("output")
    p.add_argument("--compress", action="store_true", help="write object streams + xref stream")
    p = add("report", cmd_report, "write a self-contained HTML inspector")
    p.add_argument("-o", "--output", default="report.html")
    p.add_argument("--dpi", type=float, default=60.0)
    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
