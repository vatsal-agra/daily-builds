"""faraday: a from-scratch SPICE-like circuit simulator CLI.

    faraday dc <preset|netlist.cir>
    faraday tran <preset|netlist.cir> --tstop 5m --dt 1u [--uic]
    faraday ac <preset|netlist.cir> --fstart 1 --fstop 1meg [--points 50]
    faraday netlist <netlist.cir>        # parse + pretty-print + re-serialize
    faraday list-presets
    faraday serve [--port 8000]
    faraday demo
"""

import argparse
import csv
import sys

from . import ac as ac_mod
from . import circuits, dc, netlist, transient
from .linalg import SingularMatrixError
from .mna import Circuit
from .netlist import parse_value


def _load_circuit(spec):
    if spec in circuits.PRESETS:
        return circuits.PRESETS[spec]()
    try:
        with open(spec) as f:
            text = f.read()
    except OSError as exc:
        raise SystemExit(
            f"faraday: {spec!r} is not a known preset "
            f"({', '.join(sorted(circuits.PRESETS))}) and could not be "
            f"opened as a netlist file: {exc}"
        )
    elements, directives = netlist.parse_netlist(text)
    if not elements:
        raise SystemExit(f"faraday: {spec}: netlist has no elements")
    return Circuit(elements, name=spec)


def cmd_dc(args):
    circuit = _load_circuit(args.circuit)
    voltages, currents = dc.operating_point(circuit)
    print(f"DC operating point: {circuit.name}")
    for node in sorted(voltages, key=lambda n: (n != "0", n)):
        print(f"  V({node:>6}) = {voltages[node]: .6f} V")
    for name, i in sorted(currents.items()):
        print(f"  I({name:>6}) = {i: .6e} A")


def cmd_tran(args):
    circuit = _load_circuit(args.circuit)
    t_stop = parse_value(args.tstop)
    dt = parse_value(args.dt)
    result = transient.simulate(circuit, t_stop, dt, use_ic=args.uic)
    nodes = sorted(result.voltages, key=lambda n: (n != "0", n))
    branches = sorted(result.currents)
    out = open(args.out, "w", newline="") if args.out else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow(["time"] + [f"V({n})" for n in nodes] + [f"I({b})" for b in branches])
        for i, t in enumerate(result.times):
            writer.writerow([f"{t:.9g}"]
                             + [f"{result.voltages[n][i]:.9g}" for n in nodes]
                             + [f"{result.currents[b][i]:.9g}" for b in branches])
    finally:
        if out is not sys.stdout:
            out.close()
            print(f"wrote {len(result.times)} samples to {args.out}", file=sys.stderr)


def cmd_ac(args):
    circuit = _load_circuit(args.circuit)
    f_start = parse_value(args.fstart)
    f_stop = parse_value(args.fstop)
    result = ac_mod.sweep(circuit, f_start, f_stop, args.points, args.scale)
    nodes = sorted(result.voltages, key=lambda n: (n != "0", n))
    out = open(args.out, "w", newline="") if args.out else sys.stdout
    try:
        writer = csv.writer(out)
        header = ["freq"]
        for n in nodes:
            header += [f"|V({n})|{'_dB' if args.db else ''}", f"phase({n})_deg"]
        writer.writerow(header)
        for i, f in enumerate(result.freqs):
            row = [f"{f:.9g}"]
            for n in nodes:
                mag = result.magnitude_db(n)[i] if args.db else result.magnitude(n)[i]
                row += [f"{mag:.6g}", f"{result.phase_deg(n)[i]:.6g}"]
            writer.writerow(row)
    finally:
        if out is not sys.stdout:
            out.close()
            print(f"wrote {len(result.freqs)} points to {args.out}", file=sys.stderr)


def cmd_netlist(args):
    with open(args.file) as f:
        text = f.read()
    elements, directives = netlist.parse_netlist(text)
    print(f"# parsed {len(elements)} elements, {len(directives)} directives from {args.file}")
    print(netlist.to_netlist(elements, directives, title=args.file))


def cmd_list_presets(args):
    for name, factory in sorted(circuits.PRESETS.items()):
        c = factory()
        print(f"{name:24} {len(c.elements)} elements, nodes: {', '.join(c.node_names)}")


def cmd_serve(args):
    from . import server
    server.serve(args.port)


def cmd_demo(args):
    from . import demo
    demo.run()


def build_parser():
    p = argparse.ArgumentParser(prog="faraday", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    p_dc = sub.add_parser("dc", help="DC operating point analysis")
    p_dc.add_argument("circuit", help="preset name or netlist file")
    p_dc.set_defaults(func=cmd_dc)

    p_tran = sub.add_parser("tran", help="transient (time-domain) analysis")
    p_tran.add_argument("circuit")
    p_tran.add_argument("--tstop", required=True, help="e.g. 5m, 10u")
    p_tran.add_argument("--dt", required=True, help="e.g. 1u, 100n")
    p_tran.add_argument("--uic", action="store_true",
                         help="use each element's initial condition instead "
                              "of a DC operating point at t=0")
    p_tran.add_argument("--out", help="write CSV here instead of stdout")
    p_tran.set_defaults(func=cmd_tran)

    p_ac = sub.add_parser("ac", help="AC small-signal frequency sweep")
    p_ac.add_argument("circuit")
    p_ac.add_argument("--fstart", required=True)
    p_ac.add_argument("--fstop", required=True)
    p_ac.add_argument("--points", type=int, default=50)
    p_ac.add_argument("--scale", choices=["log", "linear"], default="log")
    p_ac.add_argument("--db", action="store_true", help="magnitude in dB instead of linear")
    p_ac.add_argument("--out", help="write CSV here instead of stdout")
    p_ac.set_defaults(func=cmd_ac)

    p_net = sub.add_parser("netlist", help="parse a netlist and re-print it")
    p_net.add_argument("file")
    p_net.set_defaults(func=cmd_netlist)

    p_list = sub.add_parser("list-presets", help="list built-in preset circuits")
    p_list.set_defaults(func=cmd_list_presets)

    p_serve = sub.add_parser("serve", help="run the interactive browser UI")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    p_demo = sub.add_parser("demo", help="run a self-checking end-to-end walkthrough")
    p_demo.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError, SingularMatrixError, dc.ConvergenceError) as exc:
        print(f"faraday: error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
