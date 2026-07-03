"""High-level porcelain: init/add/status/commit/log/branch/checkout/diff/merge.

This module is the only place that understands the *meaning* of a
Strata repo (working tree <-> index <-> commit graph); everything below
it (store, index, objects, diff, merge) is a reusable, working-tree
agnostic library.
"""

import fnmatch
import os
import time

from . import diff as diffmod
from . import merge as mergemod
from .index import Index
from .objects import (
    MODE_DIR, MODE_EXEC, MODE_FILE, Commit, TreeEntry,
    decode_commit, decode_tree, encode_commit, encode_tree,
)
from .store import ObjectStore, ObjectNotFound

STRATA_DIR = ".strata"
DEFAULT_BRANCH = "main"
DEFAULT_AUTHOR = "Strata User <user@strata.local>"
IGNORE_FILE = ".strataignore"


class RepositoryError(Exception):
    pass


class NotARepository(RepositoryError):
    pass


class DirtyWorktree(RepositoryError):
    pass


class MergeConflict(RepositoryError):
    def __init__(self, paths):
        self.paths = paths
        super().__init__("merge conflict in: " + ", ".join(paths))


def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


class Repository:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.strata_dir = os.path.join(self.root, STRATA_DIR)
        self.objects_dir = os.path.join(self.strata_dir, "objects")
        self.refs_dir = os.path.join(self.strata_dir, "refs", "heads")
        self.head_path = os.path.join(self.strata_dir, "HEAD")
        self.index_path = os.path.join(self.strata_dir, "index")
        self.merge_head_path = os.path.join(self.strata_dir, "MERGE_HEAD")
        self.store = ObjectStore(self.objects_dir)
        self.index = Index(self.index_path)

    # ------------------------------------------------------------- setup --

    @staticmethod
    def init(path):
        root = os.path.abspath(path)
        strata_dir = os.path.join(root, STRATA_DIR)
        if os.path.isdir(strata_dir):
            raise RepositoryError(f"already a strata repository: {strata_dir}")
        os.makedirs(root, exist_ok=True)
        os.makedirs(os.path.join(strata_dir, "objects"), exist_ok=True)
        os.makedirs(os.path.join(strata_dir, "refs", "heads"), exist_ok=True)
        _write_text(os.path.join(strata_dir, "HEAD"), f"ref: refs/heads/{DEFAULT_BRANCH}\n")
        _write_text(os.path.join(strata_dir, "index"), "{}\n")
        return Repository(root)

    @staticmethod
    def discover(start=None):
        cur = os.path.abspath(start or os.getcwd())
        while True:
            if os.path.isdir(os.path.join(cur, STRATA_DIR)):
                return Repository(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                raise NotARepository(
                    "not a strata repository (or any parent up to /): run `strata init`"
                )
            cur = parent

    # --------------------------------------------------------------- HEAD --

    def _read_head(self):
        return _read_text(self.head_path).strip()

    def current_branch(self):
        head = self._read_head()
        if head.startswith("ref: refs/heads/"):
            return head[len("ref: refs/heads/"):]
        return None  # detached HEAD

    def _branch_ref_path(self, name):
        return os.path.join(self.refs_dir, name)

    def branch_commit(self, name):
        path = self._branch_ref_path(name)
        if not os.path.isfile(path):
            return None
        return _read_text(path).strip() or None

    def head_commit(self):
        """The commit id HEAD currently resolves to, or None on a branch with no commits yet."""
        head = self._read_head()
        if head.startswith("ref: refs/heads/"):
            return self.branch_commit(head[len("ref: refs/heads/"):])
        if head == "":
            return None
        return head  # detached HEAD holding a raw commit id

    def set_branch_commit(self, name, commit_id):
        os.makedirs(self.refs_dir, exist_ok=True)
        _write_text(self._branch_ref_path(name), commit_id + "\n")

    def list_branches(self):
        if not os.path.isdir(self.refs_dir):
            return []
        return sorted(os.listdir(self.refs_dir))

    def create_branch(self, name, start_commit=None):
        if not name or any(c in name for c in " \t\n~^:?*[\\"):
            raise RepositoryError(f"invalid branch name: {name!r}")
        if self.branch_commit(name) is not None:
            raise RepositoryError(f"branch already exists: {name}")
        commit_id = start_commit or self.head_commit()
        if commit_id is None:
            raise RepositoryError("cannot branch: no commits yet")
        self.set_branch_commit(name, commit_id)

    def resolve(self, ref):
        """Resolve a branch name / 'HEAD' / raw commit id to a commit id."""
        if ref == "HEAD":
            commit_id = self.head_commit()
            if commit_id is None:
                raise RepositoryError("HEAD has no commits yet")
            return commit_id
        branch_commit = self.branch_commit(ref)
        if branch_commit is not None:
            return branch_commit
        if len(ref) == 64 and all(c in "0123456789abcdef" for c in ref):
            if self.store.has(ref):
                return ref
            raise RepositoryError(f"no such commit: {ref}")
        raise RepositoryError(f"unknown ref: {ref!r}")

    # ---------------------------------------------------------- ignoring --

    def _ignore_patterns(self):
        path = os.path.join(self.root, IGNORE_FILE)
        patterns = []
        if os.path.isfile(path):
            for line in _read_text(path).splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        return patterns

    def _is_ignored(self, rel_path, patterns):
        parts = rel_path.split("/")
        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True
        return False

    def _walk_worktree(self):
        """Yield (rel_path, abs_path) for every non-ignored file under root."""
        patterns = self._ignore_patterns()
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != STRATA_DIR]
            rel_dir = os.path.relpath(dirpath, self.root)
            dirnames[:] = [
                d for d in dirnames
                if not self._is_ignored(
                    os.path.normpath(os.path.join(rel_dir, d)).replace(os.sep, "/"), patterns
                )
            ]
            for name in filenames:
                rel_path = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, "/")
                if self._is_ignored(rel_path, patterns):
                    continue
                yield rel_path, os.path.join(dirpath, name)

    # -------------------------------------------------------------- tree --

    def _flatten_tree(self, tree_id):
        """tree_id -> {rel_path: (blob_hash, mode)}"""
        result = {}
        if tree_id is None:
            return result

        def walk(tid, prefix):
            obj_type, content = self.store.read(tid)
            if obj_type != "tree":
                raise RepositoryError(f"expected tree object, got {obj_type}")
            for entry in decode_tree(content):
                rel = f"{prefix}{entry.name}"
                if entry.kind == "tree":
                    walk(entry.object_id, rel + "/")
                else:
                    result[rel] = (entry.object_id, entry.mode)

        walk(tree_id, "")
        return result

    def _build_tree(self, path_map):
        """path_map: {rel_path: (blob_hash, mode)} -> root tree object id."""
        root = {}
        for rel_path, (blob_hash, mode) in path_map.items():
            parts = rel_path.split("/")
            node = root
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = (blob_hash, mode)

        def write(node):
            entries = []
            for name, value in node.items():
                if isinstance(value, dict):
                    child_id = write(value)
                    entries.append(TreeEntry(mode=MODE_DIR, name=name, object_id=child_id, kind="tree"))
                else:
                    blob_hash, mode = value
                    entries.append(TreeEntry(mode=mode, name=name, object_id=blob_hash, kind="blob"))
            return self.store.write("tree", encode_tree(entries))

        return write(root)

    # --------------------------------------------------------------- add --

    def add(self, paths):
        """Stage files, including staging the deletion of files that were
        tracked but have since been removed from the working tree.
        `paths` may be absolute/relative file or dir paths."""
        staged = []      # (rel_path, abs_path) to hash & stage
        removed = set()  # rel_path entries to drop from the index
        for raw_path in paths:
            abs_path = os.path.abspath(os.path.join(self.root, raw_path))
            if os.path.exists(abs_path):
                if os.path.isdir(abs_path):
                    for rel_path, file_abs in self._walk_worktree():
                        if abs_path == self.root or os.path.commonpath(
                            [abs_path, os.path.join(self.root, rel_path)]
                        ) == abs_path:
                            staged.append((rel_path, file_abs))
                else:
                    rel_path = os.path.relpath(abs_path, self.root).replace(os.sep, "/")
                    staged.append((rel_path, abs_path))
                continue

            # Path no longer exists on disk: if it (or files under it) were
            # tracked, this is a staged deletion, matching real VCS `add` semantics.
            rel_path = os.path.relpath(abs_path, self.root).replace(os.sep, "/")
            matches = [
                p for p in self.index.paths()
                if p == rel_path or p.startswith(rel_path + "/")
            ]
            if not matches:
                raise RepositoryError(f"pathspec did not match any files: {raw_path}")
            removed.update(matches)

        seen = set()
        for rel_path, abs_path in staged:
            if rel_path in seen:
                continue
            seen.add(rel_path)
            with open(abs_path, "rb") as fh:
                data = fh.read()
            mode = MODE_EXEC if os.access(abs_path, os.X_OK) else MODE_FILE
            blob_id = self.store.write("blob", data)
            self.index.set(rel_path, blob_id, mode)
        for rel_path in removed:
            self.index.remove(rel_path)
        self.index.save()
        return {"staged": sorted(seen), "removed": sorted(removed)}

    # ------------------------------------------------------------ status --

    def status(self):
        head_tree = self._head_tree_id()
        head_files = self._flatten_tree(head_tree)
        index_files = {p: e["hash"] for p, e in self.index.entries.items()}
        worktree_files = {}
        for rel_path, abs_path in self._walk_worktree():
            worktree_files[rel_path] = abs_path

        staged_added, staged_modified, staged_deleted = [], [], []
        for path, blob_hash in index_files.items():
            if path not in head_files:
                staged_added.append(path)
            elif head_files[path][0] != blob_hash:
                staged_modified.append(path)
        for path in head_files:
            if path not in index_files:
                staged_deleted.append(path)

        unstaged_modified, unstaged_deleted, untracked = [], [], []
        for path, blob_hash in index_files.items():
            if path not in worktree_files:
                unstaged_deleted.append(path)
            else:
                with open(worktree_files[path], "rb") as fh:
                    data = fh.read()
                from .hashing import hash_object
                if hash_object("blob", data) != blob_hash:
                    unstaged_modified.append(path)
        for path in worktree_files:
            if path not in index_files:
                untracked.append(path)

        return {
            "staged_added": sorted(staged_added),
            "staged_modified": sorted(staged_modified),
            "staged_deleted": sorted(staged_deleted),
            "unstaged_modified": sorted(unstaged_modified),
            "unstaged_deleted": sorted(unstaged_deleted),
            "untracked": sorted(untracked),
        }

    def merge_in_progress(self):
        if not os.path.isfile(self.merge_head_path):
            return None
        return _read_text(self.merge_head_path).strip() or None

    def is_clean(self):
        s = self.status()
        return not any(s[k] for k in (
            "staged_added", "staged_modified", "staged_deleted",
            "unstaged_modified", "unstaged_deleted",
        ))

    # ------------------------------------------------------------ commit --

    def _head_tree_id(self):
        commit_id = self.head_commit()
        if commit_id is None:
            return None
        _, content = self.store.read(commit_id)
        return decode_commit(content).tree

    def commit(self, message, author=DEFAULT_AUTHOR, parents=None, timestamp=None):
        if not message or not message.strip():
            raise RepositoryError("cannot commit: empty commit message")
        path_map = {p: (e["hash"], e["mode"]) for p, e in self.index.entries.items()}
        tree_id = self._build_tree(path_map)

        merge_head = self.merge_in_progress()
        if parents is None:
            head = self.head_commit()
            if merge_head:
                parents = (head, merge_head) if head else (merge_head,)
            else:
                parents = (head,) if head else ()
        else:
            parents = tuple(p for p in parents if p)

        if parents:
            _, pcontent = self.store.read(parents[0])
            parent_commit = decode_commit(pcontent)
            if len(parents) == 1 and parent_commit.tree == tree_id:
                raise RepositoryError("nothing to commit: tree identical to parent commit")

        commit = Commit(
            tree=tree_id, parents=parents, author=author,
            timestamp=timestamp if timestamp is not None else int(time.time()),
            message=message,
        )
        commit_id = self.store.write("commit", encode_commit(commit))

        branch = self.current_branch()
        if branch is not None:
            self.set_branch_commit(branch, commit_id)
        else:
            _write_text(self.head_path, commit_id + "\n")  # detached HEAD moves forward too
        if merge_head and os.path.isfile(self.merge_head_path):
            os.remove(self.merge_head_path)
        return commit_id

    def get_commit(self, commit_id):
        _, content = self.store.read(commit_id)
        return decode_commit(content)

    def log(self, start_ref="HEAD"):
        try:
            start = self.resolve(start_ref)
        except RepositoryError:
            return []
        seen = set()
        stack = [start]
        commits = []
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            commit = self.get_commit(cid)
            commits.append((cid, commit))
            stack.extend(commit.parents)
        commits.sort(key=lambda pair: pair[1].timestamp, reverse=True)
        return commits

    # --------------------------------------------------------- checkout --

    def _write_worktree(self, target_files, current_files):
        for path in current_files:
            if path not in target_files:
                abs_path = os.path.join(self.root, path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                self._prune_empty_dirs(os.path.dirname(abs_path))
        for path, (blob_hash, mode) in target_files.items():
            abs_path = os.path.join(self.root, path)
            os.makedirs(os.path.dirname(abs_path) or self.root, exist_ok=True)
            _, content = self.store.read(blob_hash)
            with open(abs_path, "wb") as fh:
                fh.write(content)
            if mode == MODE_EXEC:
                os.chmod(abs_path, os.stat(abs_path).st_mode | 0o111)

    def _prune_empty_dirs(self, abs_dir):
        while abs_dir and os.path.abspath(abs_dir) != self.root and os.path.isdir(abs_dir):
            try:
                if os.listdir(abs_dir):
                    break
                os.rmdir(abs_dir)
                abs_dir = os.path.dirname(abs_dir)
            except OSError:
                break

    def checkout(self, target, force=False):
        commit_id = self.resolve(target)
        target_commit = self.get_commit(commit_id)
        target_files = self._flatten_tree(target_commit.tree)

        if not force:
            status = self.status()
            dirty_paths = set(status["unstaged_modified"]) | set(status["unstaged_deleted"]) \
                | set(status["staged_added"]) | set(status["staged_modified"]) | set(status["staged_deleted"])
            current_files = {p: v for p, v in self._flatten_tree(self._head_tree_id()).items()}
            would_change = {
                p for p in set(target_files) | set(current_files)
                if target_files.get(p) != current_files.get(p)
            }
            clobbered = sorted(dirty_paths & would_change)
            if clobbered:
                raise DirtyWorktree(
                    "checkout would overwrite local changes to: " + ", ".join(clobbered)
                )

        current_files = self._flatten_tree(self._head_tree_id())
        self._write_worktree(target_files, current_files)

        self.index.entries = {
            p: {"hash": h, "mode": m} for p, (h, m) in target_files.items()
        }
        self.index.save()

        if target in self.list_branches():
            _write_text(self.head_path, f"ref: refs/heads/{target}\n")
        else:
            _write_text(self.head_path, commit_id + "\n")

    # -------------------------------------------------------------- diff --

    def diff_worktree(self):
        """Unified diffs for every path that differs between the index and
        the working tree (what `status` calls unstaged changes)."""
        out = []
        st = self.status()
        for path in st["unstaged_modified"]:
            entry = self.index.get(path)
            _, old_content = self.store.read(entry["hash"])
            with open(os.path.join(self.root, path), "rb") as fh:
                new_content = fh.read()
            out.extend(self._render_blob_diff(path, old_content, new_content))
        for path in st["unstaged_deleted"]:
            entry = self.index.get(path)
            _, old_content = self.store.read(entry["hash"])
            out.extend(self._render_blob_diff(path, old_content, b""))
        return out

    def diff_refs(self, ref_a, ref_b):
        commit_a = self.get_commit(self.resolve(ref_a))
        commit_b = self.get_commit(self.resolve(ref_b))
        files_a = self._flatten_tree(commit_a.tree)
        files_b = self._flatten_tree(commit_b.tree)
        out = []
        for path in sorted(set(files_a) | set(files_b)):
            old_hash = files_a.get(path, (None, None))[0]
            new_hash = files_b.get(path, (None, None))[0]
            if old_hash == new_hash:
                continue
            old_content = self.store.read(old_hash)[1] if old_hash else b""
            new_content = self.store.read(new_hash)[1] if new_hash else b""
            out.extend(self._render_blob_diff(path, old_content, new_content))
        return out

    def _render_blob_diff(self, path, old_content, new_content):
        try:
            old_text = old_content.decode("utf-8")
            new_text = new_content.decode("utf-8")
        except UnicodeDecodeError:
            if old_content == new_content:
                return []
            return [f"Binary files a/{path} and b/{path} differ\n"]
        old_lines = diffmod.split_lines(old_text)
        new_lines = diffmod.split_lines(new_text)
        return diffmod.unified_diff(old_lines, new_lines, f"a/{path}", f"b/{path}")

    # ------------------------------------------------------------- merge --

    def _all_ancestors(self, commit_id):
        seen = set()
        stack = [commit_id]
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            stack.extend(self.get_commit(cid).parents)
        return seen

    def merge_base(self, ref_a, ref_b):
        a = self.resolve(ref_a)
        b = self.resolve(ref_b)
        ancestors_a = self._all_ancestors(a)
        if b in ancestors_a:
            return b
        ancestors_b = self._all_ancestors(b)
        if a in ancestors_b:
            return a
        common = ancestors_a & ancestors_b
        if not common:
            return None
        # pick the common ancestor with the greatest timestamp (most recent) —
        # good enough for a from-scratch VCS; real Git prunes redundant bases too.
        return max(common, key=lambda cid: self.get_commit(cid).timestamp)

    def merge(self, other_ref):
        if self.merge_in_progress():
            raise RepositoryError(
                "a merge is already in progress: resolve conflicts and commit, "
                "or restore .strata/MERGE_HEAD manually to abort"
            )
        if not self.is_clean():
            raise DirtyWorktree("cannot merge: you have uncommitted changes")
        current_branch = self.current_branch()
        if current_branch is None:
            raise RepositoryError("cannot merge in detached HEAD state")
        ours_id = self.resolve("HEAD")
        theirs_id = self.resolve(other_ref)

        if ours_id == theirs_id:
            return {"status": "up-to-date", "commit": ours_id}

        base_id = self.merge_base("HEAD", other_ref)

        if base_id == ours_id:
            self.checkout(other_ref, force=True)
            self.set_branch_commit(current_branch, theirs_id)
            _write_text(self.head_path, f"ref: refs/heads/{current_branch}\n")
            return {"status": "fast-forward", "commit": theirs_id}

        if base_id == theirs_id:
            return {"status": "up-to-date", "commit": ours_id}

        base_files = self._flatten_tree(self.get_commit(base_id).tree) if base_id else {}
        ours_files = self._flatten_tree(self.get_commit(ours_id).tree)
        theirs_files = self._flatten_tree(self.get_commit(theirs_id).tree)

        merged_files = {}
        conflicts = []
        for path in sorted(set(base_files) | set(ours_files) | set(theirs_files)):
            base_hash = base_files.get(path, (None, None))[0]
            ours_hash = ours_files.get(path, (None, None))[0]
            theirs_hash = theirs_files.get(path, (None, None))[0]

            if ours_hash == theirs_hash:
                if ours_hash is not None:
                    merged_files[path] = ours_files[path]
                continue
            if ours_hash == base_hash:
                if theirs_hash is not None:
                    merged_files[path] = theirs_files[path]
                continue
            if theirs_hash == base_hash:
                if ours_hash is not None:
                    merged_files[path] = ours_files[path]
                continue

            base_text = self._blob_text(base_hash)
            ours_text = self._blob_text(ours_hash)
            theirs_text = self._blob_text(theirs_hash)
            if base_text is None or ours_text is None or theirs_text is None:
                conflicts.append(path)
                merged_files[path] = ours_files.get(path) or theirs_files.get(path)
                continue

            result = mergemod.three_way_merge(
                base_text, ours_text, theirs_text,
                ours_label=current_branch, theirs_label=other_ref,
            )
            mode = (ours_files.get(path) or theirs_files.get(path))[1]
            blob_id = self.store.write("blob", result.text.encode("utf-8"))
            merged_files[path] = (blob_id, mode)
            if result.has_conflict:
                conflicts.append(path)

        current_files = self._flatten_tree(self._head_tree_id())
        self._write_worktree(merged_files, current_files)
        self.index.entries = {p: {"hash": h, "mode": m} for p, (h, m) in merged_files.items()}
        self.index.save()

        if conflicts:
            _write_text(self.merge_head_path, theirs_id + "\n")
            raise MergeConflict(sorted(conflicts))

        commit_id = self.commit(
            f"Merge {other_ref} into {current_branch}",
            parents=(ours_id, theirs_id),
        )
        return {"status": "merged", "commit": commit_id}

    def _blob_text(self, blob_hash):
        if blob_hash is None:
            return ""
        try:
            return self.store.read(blob_hash)[1].decode("utf-8")
        except (UnicodeDecodeError, ObjectNotFound):
            return None
