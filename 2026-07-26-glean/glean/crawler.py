"""Walks a directory tree and yields (relpath, text, mtime) for indexable files."""
import os

DEFAULT_EXTENSIONS = (".md", ".txt")
SKIP_DIRS = {".git", ".glean", "node_modules", "__pycache__", ".venv", "venv"}


def crawl(root, extensions=DEFAULT_EXTENSIONS):
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if not name.lower().endswith(tuple(extensions)):
                continue
            full_path = os.path.join(dirpath, name)
            relpath = os.path.relpath(full_path, root)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            yield relpath, text, mtime
