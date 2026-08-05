"""Python <-> JavaScript engine parity: feed the same randomized op
stream (insert/delete/undo interleaved) through crdt/site.py and
static/rga.js and assert every replica ends up with the identical text
in both languages. Requires Node (skips cleanly if it's not on PATH,
matching this repo's convention for browser/Node-dependent checks)."""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from crdt.site import Site

NODE_AVAILABLE = shutil.which("node") is not None

_PARITY_HARNESS_JS = r"""
const { Site } = require(process.argv[2]);
const fs = require("fs");
const opsBySite = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const siteIds = Object.keys(opsBySite);
const sites = {};
for (const sid of siteIds) sites[sid] = new Site(sid);
for (const sid of siteIds) {
  for (const op of opsBySite[sid]) {
    if (op.__local === "insert") sites[sid].typeInsert(op.index, op.value);
    else if (op.__local === "delete") sites[sid].typeDelete(op.index);
    else if (op.__local === "undo") sites[sid].undo();
    else if (op.__local === "redo") sites[sid].redo();
  }
}
for (const sid of siteIds) {
  for (const op of sites[sid].opLog) {
    for (const other of siteIds) if (other !== sid) sites[other].receive(op);
  }
}
for (const sid of siteIds) sites[sid]._drainPending();
const result = {};
for (const sid of siteIds) result[sid] = sites[sid].text();
console.log(JSON.stringify(result));
"""


def _gen_script(seed, num_sites=4, num_ops=45):
    rng = random.Random(seed)
    alphabet = "abcdefgh"
    sites = [chr(65 + i) for i in range(num_sites)]
    script = {sid: [] for sid in sites}
    lengths = {sid: 0 for sid in sites}
    undo_stacks = {sid: [] for sid in sites}
    for _ in range(num_ops):
        sid = rng.choice(sites)
        r = rng.random()
        length = lengths[sid]
        if r < 0.1 and undo_stacks[sid]:
            script[sid].append({"__local": "undo"})
            kind = undo_stacks[sid].pop()
            lengths[sid] += -1 if kind == "insert" else 1
        elif length == 0 or r < 0.65:
            idx = rng.randint(0, length)
            script[sid].append({"__local": "insert", "index": idx, "value": rng.choice(alphabet)})
            lengths[sid] += 1
            undo_stacks[sid].append("insert")
        else:
            idx = rng.randint(0, length - 1)
            script[sid].append({"__local": "delete", "index": idx})
            lengths[sid] -= 1
            undo_stacks[sid].append("delete")
    return script


def _run_python(script):
    sites = {sid: Site(sid) for sid in script}
    for sid, ops in script.items():
        s = sites[sid]
        for op in ops:
            if op["__local"] == "insert":
                s.type_insert(op["index"], op["value"])
            elif op["__local"] == "delete":
                s.type_delete(op["index"])
            elif op["__local"] == "undo":
                s.undo()
            elif op["__local"] == "redo":
                s.redo()
    for sid in script:
        for op in sites[sid].op_log:
            for other in script:
                if other != sid:
                    sites[other].receive(op)
    for sid in script:
        sites[sid]._drain_pending()
    return {sid: sites[sid].text() for sid in script}


@unittest.skipUnless(NODE_AVAILABLE, "node is not on PATH")
class TestPythonJsParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="braid-parity-")
        cls.harness_path = os.path.join(cls.tmpdir, "harness.js")
        with open(cls.harness_path, "w") as f:
            f.write(_PARITY_HARNESS_JS)

    def _run_js(self, script):
        script_path = os.path.join(self.tmpdir, "script.json")
        with open(script_path, "w") as f:
            json.dump(script, f)
        rga_path = os.path.join(BASE_DIR, "static", "rga.js")
        out = subprocess.run(
            ["node", self.harness_path, rga_path, script_path],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_parity_sweep(self):
        mismatches = []
        for seed in range(25):
            script = _gen_script(seed)
            py_result = _run_python(script)
            js_result = self._run_js(script)
            if py_result != js_result:
                mismatches.append((seed, py_result, js_result))
            if len(set(py_result.values())) != 1:
                mismatches.append((seed, "PYTHON SELF-DIVERGED", py_result))
        self.assertEqual(mismatches, [], f"{len(mismatches)} mismatch(es): {mismatches[:2]}")

    def test_emoji_and_sequential_insert_parity(self):
        """Direct parity check for REVIEW.md #3 and #4."""
        script = {
            "A": [{"__local": "insert", "index": 0, "value": "😀"},
                  {"__local": "insert", "index": 1, "value": "a"},
                  {"__local": "insert", "index": 2, "value": "b"}],
            "B": [],
        }
        py_result = _run_python(script)
        js_result = self._run_js(script)
        self.assertEqual(py_result, js_result)
        self.assertEqual(py_result["A"], "\U0001F600ab")


if __name__ == "__main__":
    unittest.main()
