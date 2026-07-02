"""Placeholder pack-file lookup API; the real packfile format lands in Phase 4."""
import os


def _pack_dir(gitdir):
    return os.path.join(gitdir, "objects", "pack")


def find_object(gitdir, sha1):
    return None


def matching_prefixes(gitdir, prefix):
    return set()
