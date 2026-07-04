"""The staging area, commit workflow, branches, and working-tree operations."""

from __future__ import annotations

import json
import os
import stat as statmod
import time
from dataclasses import dataclass, field
from typing import Optional

from .objects import (
    Commit,
    MODE_DIR,
    MODE_EXEC,
    MODE_FILE,
    MODE_SYMLINK,
    ObjectStore,
    TreeEntry,
    mode_for_path,
)

PLM_DIR = ".plm"
DEFAULT_BRANCH = "main"


class RepoError(Exception):
    """User-facing repository error (bad ref, dirty checkout, etc)."""


class NotARepository(RepoError):
    pass


@dataclass
class IndexEntry:
    path: str  # posix-style, relative to repo root
    mode: str
    sha: str


def find_repo_root(start: str = ".") -> str:
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, PLM_DIR)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise NotARepository(
                "not a palimpsest repository (or any parent up to /)"
            )
        cur = parent


class Repository:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.plm_dir = os.path.join(self.root, PLM_DIR)
        self.objects = ObjectStore(os.path.join(self.plm_dir, "objects"))

    # -- init ----------------------------------------------------------

    @staticmethod
    def init(path: str) -> "Repository":
        root = os.path.abspath(path)
        plm_dir = os.path.join(root, PLM_DIR)
        if os.path.isdir(plm_dir):
            raise RepoError(f"repository already exists at {plm_dir}")
        os.makedirs(os.path.join(plm_dir, "objects"), exist_ok=True)
        os.makedirs(os.path.join(plm_dir, "refs", "heads"), exist_ok=True)
        with open(os.path.join(plm_dir, "HEAD"), "w") as f:
            f.write(f"ref: refs/heads/{DEFAULT_BRANCH}\n")
        with open(os.path.join(plm_dir, "index"), "w") as f:
            json.dump([], f)
        os.makedirs(root, exist_ok=True)
        return Repository(root)

    # -- HEAD / refs -----------------------------------------------------

    def _head_path(self) -> str:
        return os.path.join(self.plm_dir, "HEAD")

    def head_ref(self) -> Optional[str]:
        """Return the branch name HEAD points to, or None if detached."""
        with open(self._head_path()) as f:
            content = f.read().strip()
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
        return None

    def _ref_path(self, branch: str) -> str:
        return os.path.join(self.plm_dir, "refs", "heads", branch)

    def resolve_ref(self, name: str) -> Optional[str]:
        """Resolve a branch name, 'HEAD', or raw sha prefix to a full sha."""
        if name == "HEAD":
            return self.head_commit()
        ref_path = self._ref_path(name)
        if os.path.exists(ref_path):
            with open(ref_path) as f:
                return f.read().strip()
        # Detached sha (allow abbreviation down to 4 hex chars).
        if all(c in "0123456789abcdef" for c in name.lower()) and len(name) >= 4:
            matches = self._find_shas_with_prefix(name.lower())
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise RepoError(f"ambiguous object prefix: {name}")
        return None

    def _find_shas_with_prefix(self, prefix: str) -> list[str]:
        matches = []
        objects_dir = self.objects.objects_dir
        subdir = prefix[:2]
        rest = prefix[2:]
        search_dirs = [subdir] if len(prefix) >= 2 else os.listdir(objects_dir)
        for d in search_dirs:
            dpath = os.path.join(objects_dir, d)
            if not os.path.isdir(dpath):
                continue
            for fn in os.listdir(dpath):
                full = d + fn
                if full.startswith(prefix):
                    matches.append(full)
        return matches

    def head_commit(self) -> Optional[str]:
        branch = self.head_ref()
        if branch is not None:
            ref_path = self._ref_path(branch)
            if not os.path.exists(ref_path):
                return None  # unborn branch
            with open(ref_path) as f:
                return f.read().strip()
        with open(self._head_path()) as f:
            content = f.read().strip()
        return content or None

    def set_head_to_branch(self, branch: str) -> None:
        with open(self._head_path(), "w") as f:
            f.write(f"ref: refs/heads/{branch}\n")

    def set_head_detached(self, sha: str) -> None:
        with open(self._head_path(), "w") as f:
            f.write(sha + "\n")

    def update_branch(self, branch: str, sha: str) -> None:
        with open(self._ref_path(branch), "w") as f:
            f.write(sha + "\n")

    def list_branches(self) -> list[str]:
        heads_dir = os.path.join(self.plm_dir, "refs", "heads")
        return sorted(os.listdir(heads_dir)) if os.path.isdir(heads_dir) else []

    def create_branch(self, name: str, at_sha: Optional[str] = None) -> None:
        if os.path.exists(self._ref_path(name)):
            raise RepoError(f"branch already exists: {name}")
        sha = at_sha if at_sha is not None else self.head_commit()
        if sha is None:
            raise RepoError("cannot branch: no commits yet")
        self.update_branch(name, sha)

    # -- index -----------------------------------------------------------

    def _index_path(self) -> str:
        return os.path.join(self.plm_dir, "index")

    def read_index(self) -> list[IndexEntry]:
        with open(self._index_path()) as f:
            raw = json.load(f)
        return [IndexEntry(**e) for e in raw]

    def write_index(self, entries: list[IndexEntry]) -> None:
        entries = sorted(entries, key=lambda e: e.path)
        with open(self._index_path(), "w") as f:
            json.dump([e.__dict__ for e in entries], f, indent=0)

    # -- working tree helpers ---------------------------------------------

    def _relpath(self, path: str) -> str:
        abspath = os.path.abspath(os.path.join(self.root, path))
        rel = os.path.relpath(abspath, self.root)
        if rel.startswith(".."):
            raise RepoError(f"path {path!r} is outside the repository")
        return rel.replace(os.sep, "/")

    def _walk_working_files(self) -> list[str]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != PLM_DIR]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                out.append(self._relpath(full))
        return sorted(out)

    def add(self, paths: list[str]) -> list[str]:
        """Stage the given paths (files or directories).

        Mirrors `git add`'s handling of removals: a path that no longer
        exists on disk but is still tracked in the index (directly, or as
        a directory prefix) has its removal staged rather than erroring.
        Returns the list of paths that were staged (added/modified or
        staged-as-deleted).
        """
        entries = {e.path: e for e in self.read_index()}
        staged: list[str] = []
        targets: list[str] = []
        to_remove: list[str] = []
        for p in paths:
            abspath = os.path.join(self.root, p)
            if os.path.isdir(abspath):
                present = set()
                for dirpath, dirnames, filenames in os.walk(abspath):
                    dirnames[:] = [d for d in dirnames if d != PLM_DIR]
                    for fn in filenames:
                        rel = self._relpath(os.path.join(dirpath, fn))
                        targets.append(rel)
                        present.add(rel)
                rel_dir = self._relpath(abspath)
                prefix = "" if rel_dir == "." else rel_dir + "/"
                for tracked in entries:
                    if tracked.startswith(prefix) and tracked not in present:
                        to_remove.append(tracked)
            elif os.path.isfile(abspath) or os.path.islink(abspath):
                targets.append(self._relpath(abspath))
            else:
                rel = self._relpath(abspath)
                if rel in entries:
                    to_remove.append(rel)
                else:
                    raise RepoError(f"pathspec did not match any files: {p!r}")
        for rel in targets:
            full = os.path.join(self.root, rel)
            if os.path.islink(full):
                data = os.readlink(full).encode("utf-8")
            else:
                with open(full, "rb") as f:
                    data = f.read()
            sha = self.objects.write_blob(data)
            mode = mode_for_path(full)
            entries[rel] = IndexEntry(path=rel, mode=mode, sha=sha)
            staged.append(rel)
        for rel in to_remove:
            entries.pop(rel, None)
            staged.append(rel)
        self.write_index(list(entries.values()))
        return staged

    def remove_from_index(self, paths: list[str]) -> None:
        entries = {e.path: e for e in self.read_index()}
        for p in paths:
            entries.pop(self._relpath(os.path.join(self.root, p)), None)
        self.write_index(list(entries.values()))

    # -- tree <-> index conversion -----------------------------------------

    def build_tree_from_index(self) -> str:
        entries = self.read_index()
        return self._build_tree(
            {e.path: (e.mode, e.sha) for e in entries}
        )

    def _build_tree(self, flat: dict[str, tuple[str, str]]) -> str:
        """flat: {"a/b/c.txt": (mode, sha)} -> recursively build tree objects."""
        root: dict = {}
        for path, (mode, sha) in flat.items():
            parts = path.split("/")
            node = root
            for i, part in enumerate(parts[:-1]):
                seen = "/".join(parts[: i + 1])
                if part in node and not isinstance(node[part], dict):
                    raise RepoError(
                        f"{seen!r} cannot be both a file and a directory "
                        "— remove the old entries first"
                    )
                node = node.setdefault(part, {})
            last = parts[-1]
            if last in node and isinstance(node[last], dict):
                raise RepoError(
                    f"{path!r} cannot be both a file and a directory "
                    "— remove the old entries first"
                )
            node[last] = (mode, sha)

        def build(node: dict) -> str:
            tree_entries = []
            for name, value in node.items():
                if isinstance(value, dict):
                    sha = build(value)
                    tree_entries.append(TreeEntry(mode=MODE_DIR, name=name, sha=sha))
                else:
                    mode, sha = value
                    tree_entries.append(TreeEntry(mode=mode, name=name, sha=sha))
            return self.objects.write_tree(tree_entries)

        if not root:
            return self.objects.write_tree([])
        return build(root)

    def flatten_tree(self, tree_sha: str, prefix: str = "") -> dict[str, tuple[str, str]]:
        """tree sha -> {"a/b/c.txt": (mode, blob_sha)} recursively."""
        out: dict[str, tuple[str, str]] = {}
        for entry in self.objects.read_tree(tree_sha):
            full_name = f"{prefix}{entry.name}"
            if entry.mode == MODE_DIR:
                out.update(self.flatten_tree(entry.sha, full_name + "/"))
            else:
                out[full_name] = (entry.mode, entry.sha)
        return out

    # -- commit ------------------------------------------------------------

    def commit(
        self,
        message: str,
        author_name: str = "Palimpsest",
        author_email: str = "palimpsest@local",
        timestamp: Optional[int] = None,
        allow_empty: bool = False,
        extra_parents: Optional[list[str]] = None,
    ) -> str:
        if not message.strip():
            raise RepoError("cannot commit: empty message")
        tree_sha = self.build_tree_from_index()
        parent = self.head_commit()
        parents = [parent] if parent else []
        if extra_parents:
            parents += extra_parents
        if parent and not extra_parents:
            parent_tree = self.objects.read_commit(parent).tree
            if parent_tree == tree_sha and not allow_empty:
                raise RepoError("nothing to commit, working tree matches HEAD")
        elif not parent and not extra_parents and not allow_empty:
            empty_tree = self.objects.write_tree([])
            if tree_sha == empty_tree:
                raise RepoError(
                    "nothing to commit (create/copy files and use "
                    "'plm add' to track)"
                )
        ts = timestamp if timestamp is not None else int(time.time())
        commit_obj = Commit(
            tree=tree_sha,
            parents=parents,
            author_name=author_name,
            author_email=author_email,
            author_time=ts,
            author_tz="+0000",
            committer_name=author_name,
            committer_email=author_email,
            committer_time=ts,
            committer_tz="+0000",
            message=message,
        )
        sha = self.objects.write_commit(commit_obj)
        branch = self.head_ref()
        if branch is not None:
            self.update_branch(branch, sha)
        else:
            self.set_head_detached(sha)
        return sha

    # -- log -----------------------------------------------------------

    def log(self, start_sha: Optional[str] = None) -> list[Commit]:
        sha = start_sha if start_sha is not None else self.head_commit()
        out = []
        seen = set()
        # First-parent-only linear log (matches typical `git log` default view).
        cur = sha
        while cur and cur not in seen:
            seen.add(cur)
            c = self.objects.read_commit(cur)
            out.append((cur, c))
            cur = c.parents[0] if c.parents else None
        return out

    def all_ancestors(self, sha: str) -> set[str]:
        seen = set()
        stack = [sha]
        while stack:
            cur = stack.pop()
            if cur in seen or cur is None:
                continue
            seen.add(cur)
            c = self.objects.read_commit(cur)
            stack.extend(c.parents)
        return seen

    # -- status ----------------------------------------------------------

    def status(self) -> dict:
        head_tree_files: dict[str, tuple[str, str]] = {}
        head = self.head_commit()
        if head:
            head_commit = self.objects.read_commit(head)
            head_tree_files = self.flatten_tree(head_commit.tree)

        index_entries = {e.path: (e.mode, e.sha) for e in self.read_index()}
        working_files = set(self._walk_working_files())

        staged_added = []
        staged_modified = []
        staged_deleted = []
        for path, (mode, sha) in index_entries.items():
            if path not in head_tree_files:
                staged_added.append(path)
            elif head_tree_files[path] != (mode, sha):
                staged_modified.append(path)
        for path in head_tree_files:
            if path not in index_entries:
                staged_deleted.append(path)

        not_staged_modified = []
        not_staged_deleted = []
        for path, (mode, sha) in index_entries.items():
            full = os.path.join(self.root, path)
            if path not in working_files:
                not_staged_deleted.append(path)
                continue
            with open(full, "rb") as f:
                data = f.read()
            from .objects import hash_object_bytes

            cur_sha, _ = hash_object_bytes("blob", data)
            cur_mode = mode_for_path(full)
            if cur_sha != sha or cur_mode != mode:
                not_staged_modified.append(path)

        untracked = sorted(working_files - set(index_entries.keys()))

        return {
            "staged_added": sorted(staged_added),
            "staged_modified": sorted(staged_modified),
            "staged_deleted": sorted(staged_deleted),
            "not_staged_modified": sorted(not_staged_modified),
            "not_staged_deleted": sorted(not_staged_deleted),
            "untracked": untracked,
            "clean": not any(
                [
                    staged_added,
                    staged_modified,
                    staged_deleted,
                    not_staged_modified,
                    not_staged_deleted,
                    untracked,
                ]
            ),
        }

    # -- checkout / switch -------------------------------------------------

    def _dirty_paths(self) -> set[str]:
        st = self.status()
        return set(
            st["staged_added"]
            + st["staged_modified"]
            + st["staged_deleted"]
            + st["not_staged_modified"]
            + st["not_staged_deleted"]
        )

    def checkout(self, ref: str, force: bool = False) -> str:
        target_sha = self.resolve_ref(ref)
        if target_sha is None:
            raise RepoError(f"unknown revision or branch: {ref!r}")

        if not force:
            dirty = self._dirty_paths()
            if dirty:
                raise RepoError(
                    "your local changes would be overwritten by checkout; "
                    f"commit, stash, or use force. Dirty paths: {sorted(dirty)}"
                )

        target_commit = self.objects.read_commit(target_sha)
        target_files = self.flatten_tree(target_commit.tree)
        current_files = set(self._walk_working_files())

        for path in current_files - set(target_files.keys()):
            full = os.path.join(self.root, path)
            os.remove(full)
        self._prune_empty_dirs()

        new_index = []
        for path, (mode, sha) in target_files.items():
            full = os.path.join(self.root, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            data = self.objects.read_blob(sha)
            if mode == MODE_SYMLINK:
                if os.path.lexists(full):
                    os.remove(full)
                os.symlink(data.decode("utf-8"), full)
            else:
                with open(full, "wb") as f:
                    f.write(data)
                if mode == MODE_EXEC:
                    st = os.stat(full)
                    os.chmod(full, st.st_mode | 0o111)
            new_index.append(IndexEntry(path=path, mode=mode, sha=sha))
        self.write_index(new_index)

        if ref in self.list_branches():
            self.set_head_to_branch(ref)
        else:
            self.set_head_detached(target_sha)
        return target_sha

    def _prune_empty_dirs(self) -> None:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True):
            dirnames[:] = [d for d in dirnames if d != PLM_DIR]
            if dirpath != self.root:
                candidates.append(dirpath)
        for dirpath in sorted(candidates, key=len, reverse=True):
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                pass
