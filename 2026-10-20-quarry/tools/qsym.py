#!/usr/bin/env python3
"""qsym — add function names and file:line to the frames in a Quarry report.

libquarry.so prints frames it cannot name as ``  0x55d0c3a2b4d5  module+0xOFFSET``.  This filter
resolves those with addr2line:

    QUARRY_DEBUG=1 LD_PRELOAD=build/libquarry.so ./prog 2>&1 | tools/qsym.py
    tools/qsym.py report.txt --exe ./prog

Modules are looked up by the name in the report (a path, or a bare name searched for in the
current directory and $PATH); --exe overrides the lookup for the main program.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

FRAME = re.compile(r"^(\s+0x[0-9a-fA-F]+\s+)(\S+)\+0x([0-9a-fA-F]+)\s*$")


def find_module(name, exe):
    if exe and os.path.basename(name) == os.path.basename(exe):
        return exe
    if os.path.isfile(name):
        return name
    base = os.path.basename(name)
    if os.path.isfile(base):
        return os.path.join(".", base)
    return shutil.which(base)


def resolve(path, offsets):
    """Return {offset: 'func at file:line'} for the offsets, or {} if addr2line is unavailable."""
    if not shutil.which("addr2line") or not path:
        return {}
    try:
        out = subprocess.run(
            ["addr2line", "-f", "-C", "-p", "-i", "-e", path] + ["0x%x" % o for o in offsets],
            capture_output=True, text=True, timeout=60,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return {}
    res = {}
    if len(out) < len(offsets):
        return res
    # -p -i prints one line per frame plus extra lines for inlined callers; without -i alignment is 1:1
    # so ask for the simple form again when the counts differ.
    if len(out) != len(offsets):
        out = subprocess.run(
            ["addr2line", "-f", "-C", "-p", "-e", path] + ["0x%x" % o for o in offsets],
            capture_output=True, text=True, timeout=60,
        ).stdout.splitlines()
    for off, line in zip(offsets, out):
        line = line.strip()
        if line and not line.startswith("??"):
            res[off] = line
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", nargs="?", help="report file (default: stdin)")
    ap.add_argument("--exe", help="path of the main program, if it cannot be found by name")
    args = ap.parse_args()
    try:
        text = open(args.report).read() if args.report else sys.stdin.read()
    except OSError as e:
        sys.exit("qsym: %s" % e)

    lines = text.splitlines()
    wanted = {}
    for ln in lines:
        m = FRAME.match(ln)
        if m:
            wanted.setdefault(m.group(2), set()).add(int(m.group(3), 16))
    table = {}
    for mod, offs in wanted.items():
        table[mod] = resolve(find_module(mod, args.exe), sorted(offs))
    for ln in lines:
        m = FRAME.match(ln)
        if m:
            hit = table.get(m.group(2), {}).get(int(m.group(3), 16))
            if hit:
                ln = "%s%s  [%s+0x%s]" % (m.group(1), hit, os.path.basename(m.group(2)), m.group(3))
        print(ln)


if __name__ == "__main__":
    main()
