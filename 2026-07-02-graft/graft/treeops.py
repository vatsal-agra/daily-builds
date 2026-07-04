"""Build/flatten tree objects from and to a flat {path: (mode, sha1)} mapping."""
from . import objecthash


def build_tree_from_paths(repo, paths):
    """paths: dict of 'a/b/c.txt' -> (mode, sha1). Returns root tree sha1.

    Writes every intermediate tree object. Empty `paths` writes an empty tree.
    """
    root = {}
    for path, (mode, sha1) in paths.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (mode, sha1)

    def write_node(node):
        entries = []
        for name, val in node.items():
            if isinstance(val, dict):
                sub_sha = write_node(val)
                entries.append(objecthash.TreeEntry("40000", name, sub_sha))
            else:
                mode, sha1 = val
                entries.append(objecthash.TreeEntry(mode, name, sha1))
        content = objecthash.encode_tree(entries)
        return repo.write_object("tree", content)

    return write_node(root)


def flatten_tree(repo, tree_sha, prefix=""):
    """Return dict 'a/b/c.txt' -> (mode, sha1) for every blob under tree_sha."""
    if tree_sha is None:
        return {}
    out = {}
    _, content = repo.read_object_any(tree_sha)
    for entry in objecthash.decode_tree(content):
        full = f"{prefix}{entry.name}"
        if entry.is_dir():
            out.update(flatten_tree(repo, entry.sha1, prefix=full + "/"))
        else:
            out[full] = (entry.mode, entry.sha1)
    return out


def tree_of_commit(repo, commit_sha):
    if commit_sha is None:
        return None
    _, content = repo.read_object_any(commit_sha)
    info = objecthash.decode_commit(content)
    return info["tree"]
