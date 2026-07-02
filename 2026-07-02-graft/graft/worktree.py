"""Working-tree scanning: file discovery, mode detection, ignore patterns."""
import fnmatch
import os
import stat

from . import objecthash
from .repository import GRAFT_DIR

IGNORE_FILE = ".graftignore"


def load_ignore_patterns(worktree):
    path = os.path.join(worktree, IGNORE_FILE)
    patterns = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns


def is_ignored(rel_path, patterns):
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(os.path.basename(rel_path), pat):
            return True
    return False


def list_worktree_files(worktree):
    """Return sorted list of tracked-candidate relative paths (posix style)."""
    patterns = load_ignore_patterns(worktree)
    results = []
    for root, dirs, files in os.walk(worktree):
        dirs[:] = sorted(d for d in dirs if d != GRAFT_DIR)
        rel_root = os.path.relpath(root, worktree)
        for name in files:
            rel = name if rel_root == "." else f"{rel_root}/{name}"
            rel = rel.replace(os.sep, "/")
            if is_ignored(rel, patterns):
                continue
            results.append(rel)
    return sorted(results)


def file_mode(abspath):
    st = os.lstat(abspath)
    if stat.S_ISLNK(st.st_mode):
        return "120000"
    if st.st_mode & stat.S_IXUSR:
        return "100755"
    return "100644"


def read_blob_bytes(abspath):
    mode = file_mode(abspath)
    if mode == "120000":
        return os.readlink(abspath).encode("utf-8")
    with open(abspath, "rb") as f:
        return f.read()


def hash_working_file(abspath):
    """Return (mode, sha1) for a file WITHOUT writing an object."""
    mode = file_mode(abspath)
    content = read_blob_bytes(abspath)
    sha1, _ = objecthash.hash_bytes("blob", content)
    return mode, sha1
