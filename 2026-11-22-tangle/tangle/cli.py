"""Command line interface:  python -m tangle <command> ..."""
import argparse
import json
import sys

from . import catalog, poly as P
from .alexander import alexander, colorings, determinant
from .draw import render_svg
from .identify import identify
from .jones import fmt_jones, jones
from .link import Link, LinkError, parse_braid, parse_pd
from .simplify import fmt_word, scramble, simplify


def add_source(ap):
    g = ap.add_argument_group("diagram source (choose one)")
    g.add_argument("--braid", help='braid word, e.g. "1 -2 1 -2" or "s1 s2^-1 s1 s2^-1"')
    g.add_argument("--strands", type=int, help="number of braid strands (default: inferred)")
    g.add_argument("--pd", help='PD code, e.g. "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]"')
    g.add_argument("--loops", type=int, default=0, help="extra free circles for --pd")
    g.add_argument("--name", help="catalog name, e.g. 4_1, 'Hopf link' (see `tangle catalog`)")
    g.add_argument("--torus", help="torus knot P,Q  (e.g. 3,5)")


def load(args):
    given = [x for x in (args.braid, args.pd, args.name, args.torus) if x is not None]
    if len(given) != 1:
        raise LinkError("give exactly one of --braid, --pd, --name, --torus")
    if args.braid is not None:
        return Link.from_braid(args.braid, args.strands)
    if args.pd is not None:
        return Link.from_pd(parse_pd(args.pd), args.loops)
    if args.name is not None:
        return catalog.get(args.name)
    try:
        p, q = (int(x) for x in args.torus.split(","))
    except ValueError:
        raise LinkError("--torus expects two integers like 3,5")
    return catalog.get(f"T({p},{q})")


def report(link):
    inv = identify(link)
    i = inv["invariants"]
    J, A = i["jones"], i["alexander"]
    lines = []
    if link.name:
        lines.append(f"diagram      : {link.name}")
    if link.braid:
        lines.append(f"braid        : {fmt_word(link.braid[1])}  on {link.braid[0]} strands")
    lines += [f"PD code      : {link.pd_string()}",
              f"structure    : {link.summary()}"]
    lk = link.linking_numbers()
    if lk:
        lines.append("linking nos. : " + ", ".join(f"lk({a+1},{b+1}) = {v:+d}" for (a, b), v in lk.items()))
    lines += [f"Jones  V(t)  : {fmt_jones(J)}",
              f"Alexander    : {P.fmt(A) if A else '0'}",
              f"determinant  : {i['determinant']}"]
    if link.is_knot() and A:
        lines.append(f"genus bound  : g >= {(max(A) - min(A)) / 2:g}   (from the degree of the Alexander polynomial)")
    cols = []
    for p in (3, 5, 7):
        c = colorings(link, p)
        cols.append(f"p={p}: {c['nontrivial']} non-trivial" if c["colorable"] else f"p={p}: no")
    lines.append("Fox colorings: " + "; ".join(cols))
    lines.append("chirality    : " + ("chiral (Jones differs from its mirror image)" if i["chiral"]
                                       else "Jones is mirror-symmetric (amphichiral or achiral-looking)"))
    lines.append(f"VERDICT      : {inv['verdict']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tangle", description="Knot theory laboratory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="invariants + identification of a diagram")
    add_source(a)
    a.add_argument("--json", action="store_true", help="machine readable output")

    s = sub.add_parser("simplify", help="try to simplify a braid (unknot prover)")
    add_source(s)
    s.add_argument("--budget", type=int, default=40000, help="search node budget")

    d = sub.add_parser("draw", help="write an SVG of a braid-closure diagram")
    add_source(d)
    d.add_argument("-o", "--output", required=True)
    d.add_argument("--theme", choices=["light", "dark"], default="light")

    sub.add_parser("catalog", help="list the built-in knots and links with their invariants")

    r = sub.add_parser("scramble", help="scramble a braid with random sound moves and prove nothing changed")
    add_source(r)
    r.add_argument("--steps", type=int, default=30)
    r.add_argument("--seed", type=int, default=0)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "analyze":
            L = load(args)
            if args.json:
                inv = identify(L)
                print(json.dumps({"components": L.num_components, "crossings": L.n, "writhe": L.writhe,
                                  "pd": L.pd_code(), "jones": {str(k): v for k, v in jones(L).items()},
                                  "jones_unit": "exponent q means t^(q/4)",
                                  "alexander": {str(k): v for k, v in alexander(L).items()},
                                  "determinant": determinant(L), "verdict": inv["verdict"],
                                  "matches": inv["matches"]}, indent=1))
            else:
                print(report(L))
        elif args.cmd == "simplify":
            L = load(args)
            if not L.braid:
                raise LinkError("simplify needs a braid word (--braid / --name / --torus)")
            n, w = L.braid
            res = simplify(n, w, args.budget)
            print(f"start : {fmt_word(w)}  on {n} strands  ({len(w)} crossings)")
            for st in res["steps"][1:] if res["steps"] and res["steps"][0].startswith("start") else res["steps"]:
                print("  " + st)
            print(f"end   : {fmt_word(res['word'])}  on {res['strands']} strands  ({len(res['word'])} crossings, "
                  f"{res['nodes']} states explored)")
            if res["proved_unknot"]:
                print("PROVED: the closure is the unknot (explicit sequence of Reidemeister/Markov moves above).")
            else:
                J = jones(L)
                if J == {0: 1} and L.is_knot():
                    print("NOT proved: invariants are trivial but the search could not reduce the diagram.")
                else:
                    print("Reduced as far as the search could; this is NOT a proof of knottedness "
                          "(see `analyze` for the invariants that do prove it)." if J != {0: 1} else "")
        elif args.cmd == "draw":
            L = load(args)
            inv = identify(L)
            cap = [f"Jones  {fmt_jones(jones(L))}", f"Alexander  {P.fmt(alexander(L)) or '0'}"]
            title = L.name or (inv["matches"][0][0] if inv["matches"] else None)
            with open(args.output, "w") as fh:
                fh.write(render_svg(L, title=title, caption=cap, theme=args.theme))
            print(f"wrote {args.output}")
        elif args.cmd == "catalog":
            print(f"{'name':<22}{'xings':>5}  {'det':>4}  Jones")
            for name, n, inv in __import__("tangle.identify", fromlist=["table"]).table():
                print(f"{name:<22}{n:>5}  {inv['determinant']:>4}  {fmt_jones(inv['jones'])}")
        elif args.cmd == "scramble":
            L = load(args)
            if not L.braid:
                raise LinkError("scramble needs a braid word")
            n, w = L.braid
            n2, w2 = scramble(n, w, args.steps, args.seed)
            L2 = Link.from_braid(w2, n2)
            print(f"original : {fmt_word(w)} ({n} strands)")
            print(f"scrambled: {fmt_word(w2)} ({n2} strands, {len(w2)} crossings)")
            same = jones(L) == jones(L2) and alexander(L) == alexander(L2)
            print(f"Jones    : {fmt_jones(jones(L))}   |   {fmt_jones(jones(L2))}")
            print("invariants identical: " + ("YES" if same else "NO  <-- BUG"))
            print("identification of scrambled diagram: " + identify(L2)["verdict"])
            return 0 if same else 2
    except LinkError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except MemoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
