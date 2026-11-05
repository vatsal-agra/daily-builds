"""Command-line front end:  ferrule as | ld | build | ar | dump | nm | map | report"""
import argparse
import os
import sys
from . import __version__
from .errors import FerruleError
from .elf import ElfObject
from .ar import Archive, Member, read_archive, is_archive
from .asm import assemble
from .link import Linker, Options, link
from . import dump as dumpmod


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as ex:
        raise FerruleError(f"cannot read {path}: {ex.strerror}")


def _write(path, data, exe=False):
    try:
        with open(path, "wb") as f:
            f.write(data)
        if exe:
            os.chmod(path, 0o755)
    except OSError as ex:
        raise FerruleError(f"cannot write {path}: {ex.strerror}")


def asm_file(path):
    try:
        text = _read(path).decode("utf-8")
    except UnicodeDecodeError:
        raise FerruleError(f"{path}: source is not valid UTF-8")
    return assemble(text, path)


def cmd_as(a):
    out = a.output or os.path.splitext(os.path.basename(a.input))[0] + ".o"
    _write(out, asm_file(a.input).to_bytes())
    return 0


def _linker_opts(a):
    try:
        base = int(a.base, 0)
    except ValueError:
        raise FerruleError(f"invalid --base value {a.base!r} (expected a number such as 0x400000)")
    return Options(entry=a.entry, gc_sections=a.gc_sections, base=base, undefined=a.undefined or [],
                   lib_dirs=a.L or [], allow_undefined=a.allow_undefined)


def _gather(a, assemble_sources):
    items = []
    for i in a.inputs:
        if i.startswith("@lib:"):
            items.append(("lib", i[5:]))
        elif i.endswith((".s", ".S", ".asm")) and assemble_sources:
            items.append(asm_file(i))
        else:
            items.append(i)
    return items


def cmd_ld(a, build=False):
    if not a.inputs:
        raise FerruleError("no input files")
    opts = _linker_opts(a)
    opts.whole_archive = a.whole_archive
    res = link(_gather(a, build), opts)
    out = a.output or "a.out"
    _write(out, res.data, exe=True)
    if a.map:
        with open(a.map, "w") as f:
            f.write(dumpmod.link_map(res, out))
    if a.report:
        from .report import render_html
        with open(a.report, "w") as f:
            f.write(render_html(res, out))
    if a.verbose:
        print(f"{out}: {len(res.data)} bytes, entry {res.entry:#x}, {len(res.sections)} sections, "
              f"{len(res.pulled)} archive member(s) pulled, {len(res.discarded)} section(s) discarded")
    return 0


def cmd_ar(a):
    op = a.ops.lstrip("-")
    if "t" in op:
        for m in read_archive(a.archive).members:
            print(m.name)
        return 0
    if "x" in op:
        ar = read_archive(a.archive)
        wanted = set(a.files)
        for m in ar.members:
            if not wanted or m.name in wanted:
                _write(m.name, m.data)
        return 0
    if "c" in op or "r" in op:
        ar = read_archive(a.archive) if os.path.exists(a.archive) else Archive(a.archive)
        if not a.files:
            raise FerruleError("ar: no members given")
        for f in a.files:
            name = os.path.basename(f)
            data = _read(f)
            ElfObject.parse(data, f)           # members must be valid objects
            for m in ar.members:
                if m.name == name:
                    m.data = data
                    break
            else:
                ar.members.append(Member(name, data))
        _write(a.archive, ar.to_bytes())
        return 0
    raise FerruleError(f"ar: unsupported operation '{a.ops}' (use c/r to create, t to list, x to extract)")


def _load_any(path):
    data = _read(path)
    if is_archive(data):
        return "archive", Archive.parse(data, path), data
    if data[16:18] == b"\x02\x00" and data[:4] == b"\x7fELF":
        return "exe", None, data
    return "object", ElfObject.parse(data, path), data


def cmd_crosscheck(a):
    """Link with Ferrule and with GNU ld, run both, compare stdout + exit status."""
    import shutil
    import subprocess
    import tempfile
    ld = shutil.which("ld")
    if ld is None:
        raise FerruleError("crosscheck needs GNU ld on PATH")
    with tempfile.TemporaryDirectory() as d:
        fo, go = os.path.join(d, "ferrule.out"), os.path.join(d, "gnu.out")
        res = link(_gather(a, True), _linker_opts(a))
        _write(fo, res.data, exe=True)
        objs = []
        for i in a.inputs:
            if i.endswith((".s", ".S", ".asm")):
                o = os.path.join(d, os.path.basename(i) + ".o")
                _write(o, asm_file(i).to_bytes())
                objs.append(o)
            else:
                objs.append(i)
        extra = ["--gc-sections"] if a.gc_sections else []
        r = subprocess.run([ld, "-e", a.entry, *extra, "-o", go, *objs], capture_output=True, text=True)
        if r.returncode:
            raise FerruleError("GNU ld rejected the link:\n" + r.stderr.strip())
        outs = []
        for exe in (fo, go):
            try:
                p = subprocess.run([exe], capture_output=True, timeout=a.timeout)
                outs.append((p.returncode, p.stdout))
            except subprocess.TimeoutExpired:
                outs.append(("timeout", b""))
        same = outs[0] == outs[1]
        print(f"ferrule: exit={outs[0][0]} stdout={len(outs[0][1])}B | gnu ld: exit={outs[1][0]} stdout={len(outs[1][1])}B"
              f" -> {'IDENTICAL' if same else 'DIFFERENT'}")
        print(f"sizes: ferrule {os.path.getsize(fo)} B, gnu ld {os.path.getsize(go)} B")
        return 0 if same else 1


def cmd_dump(a):
    kind, obj, data = _load_any(a.file)
    if kind == "archive":
        print(dumpmod.dump_archive(obj))
    elif kind == "exe":
        print(dumpmod.dump_exe(data, a.file))
    else:
        print(dumpmod.dump_object(obj))
    return 0


def cmd_nm(a):
    kind, obj, data = _load_any(a.file)
    if kind == "archive":
        for m in obj.members:
            print(f"\n{m.name}:")
            print("\n".join(dumpmod.nm(ElfObject.parse(m.data, m.name))))
    else:
        print("\n".join(dumpmod.nm(obj if kind == "object" else data)))
    return 0


def _protect_libs(argv):
    """argparse would swallow `-lNAME` as an unknown option and lose its position; keep it positional."""
    out, skip = [], False
    for tok in argv:
        if skip:
            out.append(tok)
            skip = False
        elif tok in ("-o", "-e", "--entry", "--base", "-L", "-u", "--undefined", "-Map", "--map", "--report"):
            out.append(tok)
            skip = True
        elif tok.startswith("-l") and len(tok) > 2 and not tok.startswith("--"):
            out.append("@lib:" + tok[2:])
        else:
            out.append(tok)
    return out


LD_HELP = """usage: ferrule ld|build [options] INPUT...
  INPUT            object (.o), archive (.a), -lNAME (with -L DIR); `build` also takes .s sources
  -o FILE          output (default a.out)        -e SYM / --entry SYM   entry point (default _start)
  --gc-sections    drop unreachable sections     -u SYM                 force SYM to be linked in
  -L DIR           library search directory      --base ADDR            load address (default 0x400000)
  -Map FILE        write a link map              --report FILE.html     write an HTML layout report
  --whole-archive  pull in every archive member  --allow-undefined      resolve missing symbols to 0
  -v               print a summary
Archives are searched where they appear on the command line, like GNU ld."""


def _parse_ld(args, build):
    import types
    ns = types.SimpleNamespace(inputs=[], output=None, entry="_start", gc_sections=False, base="0x400000",
                               L=[], undefined=[], whole_archive=False, allow_undefined=False, map=None,
                               report=None, verbose=False)
    valued = {"-o": "output", "--output": "output", "-e": "entry", "--entry": "entry", "--base": "base",
              "-L": "L", "-u": "undefined", "--undefined": "undefined", "-Map": "map", "--map": "map",
              "--report": "report"}
    flags = {"--gc-sections": "gc_sections", "--whole-archive": "whole_archive",
             "--allow-undefined": "allow_undefined", "-v": "verbose", "--verbose": "verbose"}
    i = 0
    while i < len(args):
        t = args[i]
        i += 1
        if t in ("-h", "--help"):
            print(LD_HELP)
            return None
        if t in flags:
            setattr(ns, flags[t], True)
        elif t.split("=", 1)[0] in valued:
            key, eq, val = t.partition("=")
            if not eq:
                if i >= len(args):
                    raise FerruleError(f"option {key} needs a value")
                val, i = args[i], i + 1
            dest = valued[key]
            if isinstance(getattr(ns, dest), list):
                getattr(ns, dest).append(val)
            else:
                setattr(ns, dest, val)
        elif t.startswith(("-L", "-u", "-e", "-o")) and len(t) > 2 and not t.startswith("--"):
            dest = valued[t[:2]]
            if isinstance(getattr(ns, dest), list):
                getattr(ns, dest).append(t[2:])
            else:
                setattr(ns, dest, t[2:])
        elif t.startswith("-l") and len(t) > 2:
            ns.inputs.append("@lib:" + t[2:])
        elif t.startswith("-") and t != "-":
            raise FerruleError(f"unknown option {t!r} (see: ferrule ld --help)")
        else:
            ns.inputs.append(t)
    ns.fn = (lambda a: cmd_ld(a, True)) if build else cmd_ld
    return ns


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="ferrule", description="x86-64 assembler + static linker + archiver")
    p.add_argument("--version", action="version", version=f"ferrule {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("as", help="assemble a .s file into an ELF object")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_as)
    for name, build in (("ld", False), ("build", True)):
        s = sub.add_parser(name, help="link objects/archives" + (" (assembling .s inputs first)" if build else ""))
        s.add_argument("inputs", nargs="*")
        s.add_argument("-o", "--output")
        s.add_argument("-e", "--entry", default="_start")
        s.add_argument("--gc-sections", action="store_true")
        s.add_argument("--base", default="0x400000")
        s.add_argument("-L", action="append")
        s.add_argument("-u", "--undefined", action="append")
        s.add_argument("--whole-archive", action="store_true")
        s.add_argument("--allow-undefined", action="store_true")
        s.add_argument("-Map", "--map")
        s.add_argument("--report", help="write a self-contained HTML layout report")
        s.add_argument("-v", "--verbose", action="store_true")
        s.set_defaults(fn=(lambda a: cmd_ld(a, True)) if build else cmd_ld)
    s = sub.add_parser("crosscheck", help="link with ferrule AND GNU ld, run both, compare behaviour")
    s.add_argument("inputs", nargs="+")
    s.add_argument("-e", "--entry", default="_start")
    s.add_argument("--gc-sections", action="store_true")
    s.add_argument("--timeout", type=float, default=10)
    s.set_defaults(fn=cmd_crosscheck, base="0x400000", L=[], undefined=[], allow_undefined=False)
    s = sub.add_parser("ar", help="create/list/extract archives (ar crs lib.a a.o b.o | ar t lib.a)")
    s.add_argument("ops")
    s.add_argument("archive")
    s.add_argument("files", nargs="*")
    s.set_defaults(fn=cmd_ar)
    s = sub.add_parser("dump", help="readelf-style dump of an object, archive or executable")
    s.add_argument("file")
    s.set_defaults(fn=cmd_dump)
    s = sub.add_parser("nm", help="list symbols")
    s.add_argument("file")
    s.set_defaults(fn=cmd_nm)
    if argv and argv[0] in ("ld", "build"):
        try:
            a = _parse_ld(argv[1:], argv[0] == "build")
        except FerruleError as ex:
            print(f"ferrule: error: {ex}", file=sys.stderr)
            return 2
        if a is None:
            return 0
    else:
        a = p.parse_args(argv)
    try:
        return a.fn(a)
    except FerruleError as ex:
        print(f"ferrule: error: {ex}", file=sys.stderr)
        return 1
    except OSError as ex:
        print(f"ferrule: error: {ex.filename or ''}: {ex.strerror}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0
