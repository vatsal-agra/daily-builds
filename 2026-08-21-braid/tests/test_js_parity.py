"""Differentially checks that server/static/rga.js is a faithful port of
crdt/rga.py: the same randomized op histories, replayed through each
language's implementation independently, must produce byte-identical
text. Skips (doesn't fail) if `node` isn't on PATH, since this checks a
second, optional implementation consistency property on top of the
Python-only correctness already proven in test_rga.py."""

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest

from crdt.rga import RGA

_HERE = os.path.dirname(os.path.abspath(__file__))


def _run_scenario(seed, n_peers=4, rounds=6, ops_per_round=6):
    rng = random.Random(seed)
    peer_ids = [f"P{i}" for i in range(n_peers)]
    peers = {p: RGA(p) for p in peer_ids}
    history = []
    for _round in range(rounds):
        round_ops = {}
        for p in peer_ids:
            ops = []
            for _ in range(ops_per_round):
                n = len(peers[p])
                if n == 0 or rng.random() < 0.7:
                    ops.append(peers[p].local_insert(rng.randint(0, n), rng.choice("abcXYZ ")))
                else:
                    ops.append(peers[p].local_delete(rng.randint(0, n - 1)))
            round_ops[p] = ops
            history.extend(ops)
        for p in peer_ids:
            from crdt.clock import CausalDeliveryBuffer
            others = [op for q in peer_ids if q != p for op in round_ops[q]]
            buf = CausalDeliveryBuffer(peers[p].has_id)
            rng.shuffle(others)
            for op in others:
                buf.submit(op, peers[p].apply_remote)
    texts = {p: peers[p].text() for p in peer_ids}
    assert len(set(texts.values())) == 1, f"python-internal divergence seed={seed}"
    return history, texts[peer_ids[0]]


def _serialize_op(op):
    def sid(x):
        return None if x is None else list(x)

    out = dict(op)
    out["id"] = sid(op["id"])
    if "parent" in out:
        out["parent"] = sid(out["parent"])
    if "op_id" in out:
        out["op_id"] = sid(out["op_id"])
    out["deps"] = [sid(d) for d in (out.get("deps") or ())]
    return out


@unittest.skipUnless(shutil.which("node"), "node not on PATH")
class TestJSParity(unittest.TestCase):
    def test_js_rga_matches_python_rga(self):
        cases = []
        for seed in range(25):
            history, expected_text = _run_scenario(seed)
            cases.append({
                "seed": seed,
                "ops": [_serialize_op(op) for op in history],
                "expected_text": expected_text,
            })

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cases, f)
            cases_path = f.name
        try:
            result = subprocess.run(
                ["node", os.path.join(_HERE, "js_parity_check.js"), cases_path],
                capture_output=True, text=True, timeout=60,
            )
        finally:
            os.unlink(cases_path)

        self.assertEqual(result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        self.assertIn("PARITY_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
