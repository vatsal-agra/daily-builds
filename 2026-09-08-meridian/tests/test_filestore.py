import hashlib
import unittest

from meridian import nodeid
from meridian.filestore import (
    build_manifest,
    chunk_bytes,
    chunk_raw_key,
    get_file,
    manifest_raw_key,
    put_file,
)
from meridian.simulator import Simulation


class TestChunking(unittest.TestCase):
    def test_empty_data_produces_no_chunks(self):
        self.assertEqual(chunk_bytes(b"", 10), [])

    def test_exact_multiple(self):
        data = b"a" * 20
        chunks = chunk_bytes(data, 10)
        self.assertEqual(chunks, [b"a" * 10, b"a" * 10])

    def test_remainder_chunk(self):
        data = b"a" * 25
        chunks = chunk_bytes(data, 10)
        self.assertEqual([len(c) for c in chunks], [10, 10, 5])
        self.assertEqual(b"".join(chunks), data)

    def test_rejects_nonpositive_chunk_size(self):
        with self.assertRaises(ValueError):
            chunk_bytes(b"abc", 0)
        with self.assertRaises(ValueError):
            chunk_bytes(b"abc", -5)


class TestManifest(unittest.TestCase):
    def test_manifest_records_correct_hashes(self):
        data = b"hello world" * 500
        m = build_manifest("f.txt", data, chunk_size=100)
        self.assertEqual(m["sha256"], hashlib.sha256(data).hexdigest())
        chunks = chunk_bytes(data, 100)
        self.assertEqual(m["chunk_hashes"], [hashlib.sha256(c).hexdigest() for c in chunks])
        self.assertEqual(m["size"], len(data))

    def test_manifest_key_is_deterministic(self):
        data = b"same content"
        m1 = build_manifest("a.txt", data)
        m2 = build_manifest("a.txt", data)
        self.assertEqual(manifest_raw_key(m1), manifest_raw_key(m2))

    def test_manifest_key_differs_for_different_filenames(self):
        data = b"same content"
        m1 = build_manifest("a.txt", data)
        m2 = build_manifest("b.txt", data)
        self.assertNotEqual(manifest_raw_key(m1), manifest_raw_key(m2))

    def test_chunk_raw_key_roundtrips_hash(self):
        h = hashlib.sha256(b"x").hexdigest()
        self.assertEqual(chunk_raw_key(h), b"chunk:" + h.encode())


def _settled_swarm(seed, n=15, loss_prob=0.0):
    sim = Simulation(seed=seed, loss_prob=loss_prob, k=20, alpha=3)
    nodes = sim.bootstrap_swarm(n)
    sim.run_until(n * 30 + 400)
    return sim, nodes


def _put_sync(sim, node, filename, data, chunk_size=None):
    box = {}
    kwargs = {} if chunk_size is None else {"chunk_size": chunk_size}
    put_file(node, filename, data, on_complete=lambda mk, mf, ok: box.update(key=mk, manifest=mf, ok=ok, done=True), **kwargs)
    completed = sim.pump_until(lambda: box.get("done", False))
    assert completed, "put_file never completed within pump_until's budget"
    return box


def _get_sync(sim, node, manifest_key):
    box = {}
    get_file(node, manifest_key, lambda d, ok, err, mf: box.update(data=d, ok=ok, err=err, manifest=mf, done=True))
    completed = sim.pump_until(lambda: box.get("done", False))
    assert completed, "get_file never completed within pump_until's budget"
    return box


class TestPutGetRoundTrip(unittest.TestCase):
    def test_round_trip_from_a_different_node(self):
        sim, nodes = _settled_swarm(seed=1)
        data = b"the quick brown fox jumps over the lazy dog " * 200
        uploader, downloader = nodes[0], nodes[-1]
        self.assertNotEqual(uploader.id, downloader.id)

        put_box = _put_sync(sim, uploader, "fox.txt", data, chunk_size=512)
        self.assertTrue(put_box["ok"])
        self.assertGreater(len(put_box["manifest"]["chunk_hashes"]), 1)

        dl_box = _get_sync(sim, downloader, put_box["key"])
        self.assertTrue(dl_box["ok"], dl_box.get("err"))
        self.assertEqual(dl_box["data"], data)

    def test_empty_file_round_trips(self):
        sim, nodes = _settled_swarm(seed=2)
        uploader, downloader = nodes[0], nodes[-1]
        put_box = _put_sync(sim, uploader, "empty.bin", b"")
        self.assertTrue(put_box["ok"])

        dl_box = _get_sync(sim, downloader, put_box["key"])
        self.assertTrue(dl_box["ok"], dl_box.get("err"))
        self.assertEqual(dl_box["data"], b"")

    def test_single_chunk_file(self):
        sim, nodes = _settled_swarm(seed=3)
        uploader, downloader = nodes[0], nodes[-1]
        data = b"tiny"
        put_box = _put_sync(sim, uploader, "tiny.txt", data)
        dl_box = _get_sync(sim, downloader, put_box["key"])
        self.assertTrue(dl_box["ok"])
        self.assertEqual(dl_box["data"], data)

    def test_survives_a_crashed_chunk_holder_via_replica_fallback(self):
        sim, nodes = _settled_swarm(seed=4, n=25)
        uploader, downloader = nodes[0], nodes[-1]
        data = b"resilience test payload " * 300
        put_box = _put_sync(sim, uploader, "res.txt", data, chunk_size=512)

        chunk0_key_id = nodeid.sha1_int(chunk_raw_key(put_box["manifest"]["chunk_hashes"][0]))
        holders = [e["node"] for e in sim.trace if e["kind"] == "stored" and e.get("key") == chunk0_key_id]
        self.assertTrue(holders)
        sim.network.set_live(holders[0], False)  # crash exactly one holder, others remain

        dl_box = _get_sync(sim, downloader, put_box["key"])
        self.assertTrue(dl_box["ok"], dl_box.get("err"))
        self.assertEqual(dl_box["data"], data)


class TestFailureModes(unittest.TestCase):
    def test_get_unknown_manifest_key_reports_not_found(self):
        sim, nodes = _settled_swarm(seed=5)
        box = _get_sync(sim, nodes[0], b"manifest:does-not-exist")
        self.assertFalse(box["ok"])
        self.assertIn("not found", box["err"])

    def test_malformed_manifest_shape_is_reported_not_crashed(self):
        """Regression test for a real bug found in adversarial review:
        get_file only guarded against invalid JSON *syntax*, not against
        syntactically-valid JSON that isn't a manifest object (e.g. a
        tampered/bit-rotted value storing a JSON string or list) -- that
        used to raise an uncaught AttributeError from inside a scheduled
        network callback instead of reporting a clean error."""
        sim, nodes = _settled_swarm(seed=7)
        uploader, downloader = nodes[0], nodes[-1]

        bogus_key = b"manifest:not-really-a-manifest"
        put_box = {}
        uploader.put(bogus_key, b'"just a json string, not an object"', on_complete=lambda ok, total: put_box.update(done=True))
        completed = sim.pump_until(lambda: put_box.get("done", False))
        self.assertTrue(completed)

        box = _get_sync(sim, downloader, bogus_key)
        self.assertFalse(box["ok"])
        self.assertIn("not a valid manifest", box["err"])

    def test_tampered_chunk_is_detected_not_silently_accepted(self):
        sim, nodes = _settled_swarm(seed=6, n=20)
        uploader, downloader = nodes[0], nodes[-1]
        data = b"integrity matters " * 400
        put_box = _put_sync(sim, uploader, "t.txt", data, chunk_size=512)

        chunk0_key_id = nodeid.sha1_int(chunk_raw_key(put_box["manifest"]["chunk_hashes"][0]))
        tampered = False
        for n in nodes:
            if chunk0_key_id in n.storage:
                n.storage[chunk0_key_id].value = b"corrupted!!" + n.storage[chunk0_key_id].value
                tampered = True
        self.assertTrue(tampered)

        box = _get_sync(sim, downloader, put_box["key"])
        self.assertFalse(box["ok"])
        self.assertIn("hash mismatch", box["err"])


if __name__ == "__main__":
    unittest.main()
