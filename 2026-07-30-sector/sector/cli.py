"""`sector` command-line tool."""
import argparse
import sys

from .image import FatImage
from .bpb import BPBError
from .fat import FatFullError
from .direntry import DirEntryError


class CliError(Exception):
    pass


def _load(image_path):
    try:
        return FatImage.open(image_path)
    except FileNotFoundError:
        raise CliError(f"no such image: {image_path}")
    except BPBError as e:
        raise CliError(f"{image_path}: not a valid FAT16 image ({e})")


def _fmt_size(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def cmd_mkfs(args):
    label = args.label.upper()[:11]
    img = FatImage.mkfs(args.size, volume_label=label)
    img.save(args.image)
    i = img.info()
    print(f"formatted {args.image}: {_fmt_size(i['total_bytes'])}, "
          f"{i['count_of_clusters']} clusters x {i['cluster_size']}B, "
          f"label={i['volume_label']!r}")


def cmd_info(args):
    img = _load(args.image)
    for k, v in img.info().items():
        print(f"{k:24s} {v}")


def cmd_ls(args):
    img = _load(args.image)
    entries = img.list_dir(args.path)
    if not entries:
        print("(empty)")
        return
    for e in sorted(entries, key=lambda e: e["display_name"].lower()):
        s = e["short"]
        kind = "d" if s["is_dir"] else "-"
        size = "" if s["is_dir"] else str(s["size"])
        lfn_flag = "L" if e["long_name"] else " "
        print(f"{kind}{lfn_flag} {size:>10} {s['wtime']:%Y-%m-%d %H:%M} {e['display_name']}")


def cmd_tree(args):
    img = _load(args.image)

    def walk(nodes, prefix=""):
        for i, n in enumerate(nodes):
            last = i == len(nodes) - 1
            branch = "└── " if last else "├── "
            print(prefix + branch + n["name"] + ("/" if n["is_dir"] else f" ({n['size']}B)"))
            if n["is_dir"]:
                walk(n["children"], prefix + ("    " if last else "│   "))

    print(args.path)
    walk(img.tree(args.path))


def cmd_mkdir(args):
    img = _load(args.image)
    img.mkdir(args.path)
    img.save(args.image)
    print(f"created directory {args.path}")


def cmd_cp_in(args):
    img = _load(args.image)
    with open(args.host_path, "rb") as f:
        data = f.read()
    img.write_file(args.image_path, data)
    img.save(args.image)
    print(f"wrote {len(data)} bytes -> {args.image_path}")


def cmd_cp_out(args):
    img = _load(args.image)
    data = img.read_file(args.image_path)
    if args.host_path == "-":
        sys.stdout.buffer.write(data)
    else:
        with open(args.host_path, "wb") as f:
            f.write(data)
        print(f"read {len(data)} bytes <- {args.image_path}", file=sys.stderr)


def cmd_cat(args):
    img = _load(args.image)
    sys.stdout.buffer.write(img.read_file(args.path))


def cmd_stat(args):
    img = _load(args.image)
    for k, v in img.stat(args.path).items():
        print(f"{k:14s} {v}")


def build_parser():
    p = argparse.ArgumentParser(prog="sector", description="A from-scratch FAT16 filesystem toolkit.")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("mkfs", help="format a new FAT16 image")
    m.add_argument("image")
    m.add_argument("--size", type=_size_arg, required=True, help="image size, e.g. 4M, 16M, 1048576")
    m.add_argument("--label", default="SECTOR")
    m.set_defaults(func=cmd_mkfs)

    i = sub.add_parser("info", help="print volume/geometry info")
    i.add_argument("image")
    i.set_defaults(func=cmd_info)

    ls = sub.add_parser("ls", help="list a directory")
    ls.add_argument("image")
    ls.add_argument("path", nargs="?", default="/")
    ls.set_defaults(func=cmd_ls)

    tr = sub.add_parser("tree", help="recursively list as a tree")
    tr.add_argument("image")
    tr.add_argument("path", nargs="?", default="/")
    tr.set_defaults(func=cmd_tree)

    mk = sub.add_parser("mkdir", help="create a directory")
    mk.add_argument("image")
    mk.add_argument("path")
    mk.set_defaults(func=cmd_mkdir)

    cpi = sub.add_parser("cp-in", help="copy a host file into the image")
    cpi.add_argument("image")
    cpi.add_argument("host_path")
    cpi.add_argument("image_path")
    cpi.set_defaults(func=cmd_cp_in)

    cpo = sub.add_parser("cp-out", help="copy a file out of the image ('-' for stdout)")
    cpo.add_argument("image")
    cpo.add_argument("image_path")
    cpo.add_argument("host_path")
    cpo.set_defaults(func=cmd_cp_out)

    cat = sub.add_parser("cat", help="print a file's contents to stdout")
    cat.add_argument("image")
    cat.add_argument("path")
    cat.set_defaults(func=cmd_cat)

    st = sub.add_parser("stat", help="show metadata for a file or directory")
    st.add_argument("image")
    st.add_argument("path")
    st.set_defaults(func=cmd_stat)

    return p


def _size_arg(s):
    s = s.strip().upper()
    mult = 1
    if s.endswith("K"):
        mult, s = 1024, s[:-1]
    elif s.endswith("M"):
        mult, s = 1024 * 1024, s[:-1]
    elif s.endswith("G"):
        mult, s = 1024 * 1024 * 1024, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid size: {s!r}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as e:
        print(f"sector: error: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, FileExistsError) as e:
        print(f"sector: error: {e}", file=sys.stderr)
        return 1
    except (DirEntryError, FatFullError, BPBError, ValueError) as e:
        print(f"sector: error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
