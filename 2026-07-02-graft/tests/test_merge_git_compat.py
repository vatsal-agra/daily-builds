"""Differential fuzz test: compare graft's merge3_lines against real git's
`git merge-file`, which performs exactly the same three-way line merge.
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graft import merge as merge_mod

HAVE_GIT = shutil.which("git") is not None


def rand_edit(base, rng):
    lines = list(base)
    if not lines or rng.random() < 0.3:
        pos = rng.randint(0, len(lines))
        lines.insert(pos, f"NEW{rng.randint(0, 999)}")
    elif rng.random() < 0.5:
        pos = rng.randint(0, len(lines) - 1)
        del lines[pos]
    else:
        pos = rng.randint(0, len(lines) - 1)
        lines[pos] = lines[pos] + "_MOD"
    return lines


def git_merge_file(tmpdir, base, ours, theirs):
    """Return (conflict: bool, merged_lines or None)."""
    paths = {}
    for name, lines in [("ours.txt", ours), ("base.txt", base), ("theirs.txt", theirs)]:
        p = os.path.join(tmpdir, name)
        with open(p, "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        paths[name] = p
    result = subprocess.run(
        ["git", "merge-file", "-p", "--diff3", "--marker-size=7",
         paths["ours.txt"], paths["base.txt"], paths["theirs.txt"]],
        capture_output=True, text=True,
    )
    conflict = result.returncode != 0
    merged = result.stdout
    lines = merged.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return conflict, lines


@unittest.skipUnless(HAVE_GIT, "real git binary not available")
class TestMergeGitCompat(unittest.TestCase):
    def test_conflict_detection_matches_real_git(self):
        rng = random.Random(99)
        with tempfile.TemporaryDirectory() as tmp:
            mismatches = []
            for trial in range(1000):
                base = [f"L{i}" for i in range(rng.randint(3, 12))]
                ours = rand_edit(base, rng)
                theirs = rand_edit(base, rng)
                git_conflict, _ = git_merge_file(tmp, base, ours, theirs)
                _, graft_conflict = merge_mod.merge3_lines(
                    base, ours, theirs, "ours", "theirs"
                )
                if git_conflict != graft_conflict:
                    mismatches.append((trial, base, ours, theirs, git_conflict, graft_conflict))
            self.assertEqual(
                mismatches, [],
                f"{len(mismatches)}/1000 conflict-detection mismatches vs real git: "
                f"{mismatches[:3]}",
            )

    def test_clean_merge_content_matches_real_git(self):
        rng = random.Random(123)
        with tempfile.TemporaryDirectory() as tmp:
            checked = 0
            for trial in range(1000):
                base = [f"L{i}" for i in range(rng.randint(3, 12))]
                ours = rand_edit(base, rng)
                theirs = rand_edit(base, rng)
                git_conflict, git_lines = git_merge_file(tmp, base, ours, theirs)
                graft_lines, graft_conflict = merge_mod.merge3_lines(base, ours, theirs)
                if not git_conflict and not graft_conflict:
                    checked += 1
                    self.assertEqual(graft_lines, git_lines, (base, ours, theirs))
            self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
