"""Repository layout: .graft/{objects,refs/heads,HEAD,index}."""
import os

from . import objecthash

GRAFT_DIR = ".graft"


class RepoError(Exception):
    pass


def find_repo_root(start=None):
    """Walk upward from `start` (default: cwd) looking for a .graft dir."""
    path = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(path, GRAFT_DIR)
        if os.path.isdir(candidate):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            raise RepoError("not a graft repository (or any parent up to /)")
        path = parent


class Repository:
    def __init__(self, worktree):
        self.worktree = os.path.abspath(worktree)
        self.gitdir = os.path.join(self.worktree, GRAFT_DIR)
        self.objects_dir = os.path.join(self.gitdir, "objects")
        self.refs_dir = os.path.join(self.gitdir, "refs", "heads")
        self.head_path = os.path.join(self.gitdir, "HEAD")
        self.index_path = os.path.join(self.gitdir, "index")

    @classmethod
    def discover(cls, start=None):
        return cls(find_repo_root(start))

    @classmethod
    def init(cls, path):
        worktree = os.path.abspath(path)
        os.makedirs(worktree, exist_ok=True)
        repo = cls(worktree)
        if os.path.isdir(repo.gitdir):
            raise RepoError(f"repository already exists at {repo.gitdir}")
        os.makedirs(repo.objects_dir)
        os.makedirs(repo.refs_dir)
        with open(repo.head_path, "w") as f:
            f.write("ref: refs/heads/main\n")
        return repo

    # ---- objects ----

    def write_object(self, obj_type, content):
        return objecthash.write_object(self.objects_dir, obj_type, content)

    def read_object(self, sha1):
        return objecthash.read_object_raw(self.objects_dir, sha1)

    def has_object(self, sha1):
        return os.path.exists(objecthash.object_path(self.objects_dir, sha1)) or (
            self._find_in_pack(sha1) is not None
        )

    def _find_in_pack(self, sha1):
        from . import packfile
        return packfile.find_object(self.gitdir, sha1)

    def read_object_any(self, sha1):
        """Read from loose storage, falling back to any pack files."""
        path = objecthash.object_path(self.objects_dir, sha1)
        if os.path.exists(path):
            return self.read_object(sha1)
        hit = self._find_in_pack(sha1)
        if hit is None:
            raise objecthash.ObjectError(f"object {sha1} not found (loose or packed)")
        return hit

    # ---- refs / HEAD ----

    def read_head(self):
        """Return ('ref', 'refs/heads/main') or ('sha', '<sha1>')."""
        with open(self.head_path) as f:
            content = f.read().strip()
        if content.startswith("ref: "):
            return "ref", content[len("ref: "):]
        return "sha", content

    def write_head_ref(self, ref):
        with open(self.head_path, "w") as f:
            f.write(f"ref: {ref}\n")

    def write_head_detached(self, sha1):
        with open(self.head_path, "w") as f:
            f.write(sha1 + "\n")

    def ref_path(self, ref):
        return os.path.join(self.gitdir, ref)

    def read_ref(self, ref):
        path = self.ref_path(ref)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return f.read().strip()

    def write_ref(self, ref, sha1):
        path = self.ref_path(ref)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(sha1 + "\n")

    def delete_ref(self, ref):
        path = self.ref_path(ref)
        if os.path.exists(path):
            os.remove(path)

    def list_branches(self):
        if not os.path.isdir(self.refs_dir):
            return []
        return sorted(os.listdir(self.refs_dir))

    def current_branch(self):
        """Return branch name if HEAD is attached, else None (detached)."""
        kind, value = self.read_head()
        if kind == "ref" and value.startswith("refs/heads/"):
            return value[len("refs/heads/"):]
        return None

    def resolve_head(self):
        """Return the commit sha1 HEAD points at, or None (unborn branch)."""
        kind, value = self.read_head()
        if kind == "sha":
            return value
        return self.read_ref(value)

    def resolve_ref_or_sha(self, name):
        """Resolve a branch name, HEAD, or raw sha1 prefix to a full sha1."""
        if name == "HEAD":
            sha = self.resolve_head()
            if sha is None:
                raise RepoError("HEAD does not point to any commit yet")
            return sha
        branch_ref = f"refs/heads/{name}"
        sha = self.read_ref(branch_ref)
        if sha is not None:
            return sha
        if self._looks_like_sha(name):
            return self._resolve_prefix(name)
        raise RepoError(f"unknown revision {name!r}")

    @staticmethod
    def _looks_like_sha(name):
        return len(name) >= 4 and all(c in "0123456789abcdef" for c in name.lower())

    def _resolve_prefix(self, prefix):
        prefix = prefix.lower()
        if len(prefix) == 40:
            if self.has_object(prefix):
                return prefix
            raise RepoError(f"object {prefix} not found")
        matches = set()
        subdir = os.path.join(self.objects_dir, prefix[:2])
        if os.path.isdir(subdir):
            for fname in os.listdir(subdir):
                full = prefix[:2] + fname
                if full.startswith(prefix):
                    matches.add(full)
        from . import packfile
        matches |= packfile.matching_prefixes(self.gitdir, prefix)
        if len(matches) == 1:
            return next(iter(matches))
        if not matches:
            raise RepoError(f"no object matches prefix {prefix!r}")
        raise RepoError(f"ambiguous prefix {prefix!r} ({len(matches)} matches)")
