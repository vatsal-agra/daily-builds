"""Command line interface:  python -m lemma <command> …"""
import argparse
import sys
import threading
import time

from .session import Session
from .syntax import LemmaError


def run_with_big_stack(fn, *args):
    sys.setrecursionlimit(200000)
    threading.stack_size(512 * 1024 * 1024)
    result = []
    t = threading.Thread(target=lambda: result.append(fn(*args)))
    t.start()
    t.join()
    return result[0] if result else 1


def cmd_check(args):
    t0 = time.time()
    sess = Session()
    t_prelude = time.time() - t0
    ok_all = True
    for path in args.files:
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        except OSError as e:
            print(f"error: cannot read {path}: {e}")
            return 2
        n0, e0 = len(sess.results), len(sess.errors)
        sess.out.clear()
        sess.run(src, path)
        for line in sess.out:
            print(line)
        for err in sess.errors[e0:]:
            print(err, file=sys.stderr)
        new = sess.results[n0:]
        proved = sum(1 for r in new if r.get("ok") and r["kind"] == "theorem")
        defs = sum(1 for r in new if r.get("ok") and r["kind"] == "def")
        inds = sum(1 for r in new if r.get("ok") and r["kind"] == "inductive")
        bad = len(sess.errors) - e0
        print(f"\n{path}: {proved} theorem(s) proved, {defs} def(s), {inds} inductive type(s), "
              f"{bad} error(s)  [kernel re-checked every declaration; prelude {t_prelude:.2f}s]")
        ok_all = ok_all and bad == 0
    if getattr(args, "export", None) and ok_all:
        from .audit import export_certificate
        export_certificate(sess, args.export)
        print(f"certificate written to {args.export}")
    if getattr(args, "audit", False) and ok_all:
        from .audit import export_certificate, audit_certificate
        cert = export_certificate(sess, None)
        res = audit_certificate(cert)
        print(res.summary())
        ok_all = ok_all and res.ok
    return 0 if ok_all else 1


def cmd_audit(args):
    from .audit import load_certificate, audit_certificate
    cert = load_certificate(args.cert)
    res = audit_certificate(cert)
    print(res.summary())
    return 0 if res.ok else 1


def cmd_report(args):
    from .report import build_report
    sess = Session()
    with open(args.file, encoding="utf-8") as f:
        src = f.read()
    sess.run(src, args.file)
    html = build_report(sess, args.file, src)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"report written to {args.out} ({len(sess.results)} command(s), {len(sess.errors)} error(s))")
    return 0 if not sess.errors else 1


def cmd_repl(args):
    from .repl import repl
    return repl()


def cmd_eval(args):
    sess = Session()
    sess.run(args.expr if args.expr.lstrip().startswith("#") else "#eval " + args.expr, "<expr>")
    for l in sess.out:
        print(l)
    for e in sess.errors:
        print(e, file=sys.stderr)
    return 0 if not sess.errors else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lemma", description="Lemma — a small dependent-type proof assistant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check one or more .lm files")
    c.add_argument("files", nargs="+")
    c.add_argument("--export", metavar="CERT.json", help="write a proof certificate for the auditor")
    c.add_argument("--audit", action="store_true", help="also re-verify with the independent auditor")
    c.set_defaults(fn=cmd_check)
    a = sub.add_parser("audit", help="verify a certificate with the independent auditor")
    a.add_argument("cert")
    a.set_defaults(fn=cmd_audit)
    r = sub.add_parser("report", help="HTML report with every proof state")
    r.add_argument("file")
    r.add_argument("-o", "--out", default="report.html")
    r.set_defaults(fn=cmd_report)
    e = sub.add_parser("eval", help="evaluate a term")
    e.add_argument("expr")
    e.set_defaults(fn=cmd_eval)
    rp = sub.add_parser("repl", help="interactive prompt")
    rp.set_defaults(fn=cmd_repl)
    args = ap.parse_args(argv)
    return run_with_big_stack(args.fn, args)


if __name__ == "__main__":
    sys.exit(main())
