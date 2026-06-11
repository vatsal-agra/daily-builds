"""Atlasforge test suite — exercises every shipped feature.

Run from the project root:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from atlasforge import biomes, cli, noise, png, render, settlements, terrain
from atlasforge.hydrology import priority_flood
from atlasforge.worldgen import generate

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _shared(seed=42, **kw):
    """Cache generated worlds across tests (they're deterministic anyway)."""
    key = (seed, tuple(sorted(kw.items())))
    if key not in _shared.cache:
        _shared.cache[key] = generate(seed=seed, **kw)
    return _shared.cache[key]


_shared.cache = {}


class TestNoise(unittest.TestCase):
    def test_range_and_determinism(self):
        vals = [noise.fbm(x * 0.13, x * 0.07, seed=5) for x in range(500)]
        self.assertTrue(all(0.0 <= v < 1.0 for v in vals))
        self.assertEqual(vals, [noise.fbm(x * 0.13, x * 0.07, seed=5) for x in range(500)])

    def test_seed_changes_field(self):
        a = [noise.fbm(x * 0.1, 0.3, seed=1) for x in range(50)]
        b = [noise.fbm(x * 0.1, 0.3, seed=2) for x in range(50)]
        self.assertNotEqual(a, b)

    def test_negative_seed_and_coords(self):
        v = noise.fbm(-3.7, -9.2, seed=-12345)
        self.assertTrue(0.0 <= v < 1.0)


class TestPNG(unittest.TestCase):
    def test_roundtrip_pixels(self):
        w, h = 5, 3
        pixels = [(x * 40 % 256, y * 90 % 256, (x + y) * 17 % 256)
                  for y in range(h) for x in range(w)]
        data = png.encode_png(w, h, pixels)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        iw, ih, depth, ctype = struct.unpack(">IIBB", data[16:26])
        self.assertEqual((iw, ih, depth, ctype), (w, h, 8, 2))
        # Decode the IDAT stream and verify pixel bytes survive.
        idat_start = data.index(b"IDAT") + 4
        idat_len = struct.unpack(">I", data[idat_start - 8 : idat_start - 4])[0]
        raw = zlib.decompress(data[idat_start : idat_start + idat_len])
        out = []
        for y in range(h):
            row = raw[y * (1 + 3 * w) : (y + 1) * (1 + 3 * w)]
            self.assertEqual(row[0], 0)  # filter: none
            for x in range(w):
                out.append(tuple(row[1 + 3 * x : 4 + 3 * x]))
        self.assertEqual(out, pixels)

    def test_size_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            png.encode_png(2, 2, [(0, 0, 0)] * 3)


class TestTerrain(unittest.TestCase):
    def test_normalized_and_deterministic(self):
        e1 = terrain.generate_elevation(48, 48, seed=9)
        e2 = terrain.generate_elevation(48, 48, seed=9)
        self.assertEqual(e1, e2)
        self.assertAlmostEqual(min(e1), 0.0)
        self.assertAlmostEqual(max(e1), 1.0)

    def test_sea_level_hits_land_fraction(self):
        e = terrain.generate_elevation(64, 64, seed=3)
        for frac in (0.2, 0.38, 0.6):
            sl = terrain.sea_level_for_land_fraction(e, frac)
            land = sum(1 for v in e if v > sl) / len(e)
            self.assertAlmostEqual(land, frac, delta=0.02)


class TestClimateAndBiomes(unittest.TestCase):
    def test_equator_warmer_than_poles(self):
        w = _shared(seed=7, width=96, height=96)
        mid = [w.temperature[w.idx(x, w.height // 2)] for x in range(w.width)]
        pole = [w.temperature[w.idx(x, 1)] for x in range(w.width)]
        self.assertGreater(sum(mid) / len(mid), sum(pole) / len(pole) + 0.2)

    def test_moisture_in_range_on_land(self):
        w = _shared(seed=7, width=96, height=96)
        for i in range(w.width * w.height):
            if w.is_land(i):
                self.assertTrue(0.0 <= w.moisture[i] <= 1.0)

    def test_biomes_valid_and_water_consistent(self):
        w = _shared(seed=7, width=96, height=96)
        for i, b in enumerate(w.biome):
            self.assertIn(b, biomes.ALL_BIOMES)
            if not w.is_land(i):
                self.assertIn(b, (biomes.OCEAN, biomes.SHALLOWS))
            if w.hydrology.lake[i]:
                self.assertEqual(b, biomes.LAKE)

    def test_biome_diversity(self):
        w = _shared(seed=42)
        land_biomes = {b for i, b in enumerate(w.biome) if w.is_land(i)}
        self.assertGreaterEqual(len(land_biomes), 10)

    def test_marsh_is_accent_not_carpet(self):
        for seed in (42, 7, 123):
            w = _shared(seed=seed)
            marsh = sum(1 for b in w.biome if b == biomes.MARSH)
            land = sum(1 for i in range(w.width * w.height) if w.is_land(i))
            self.assertLess(marsh / land, 0.04, f"seed {seed}: marsh carpet")


class TestHydrology(unittest.TestCase):
    def test_priority_flood_drains_everywhere(self):
        w = _shared(seed=7, width=96, height=96)
        filled = priority_flood(w.width, w.height, w.elevation, w.sea_level)
        # Every land cell must have a strictly lower 8-neighbor (or be coastal),
        # which is exactly what flow routing relies on.
        from atlasforge.hydrology import _neighbors

        for i in range(w.width * w.height):
            if not w.is_land(i):
                continue
            self.assertTrue(
                any(filled[j] < filled[i] for j in _neighbors(i, w.width, w.height)),
                f"cell {i} is a pit after filling",
            )

    def test_rivers_never_dangle(self):
        for seed in range(8):
            w = _shared(seed=seed, width=96, height=96)
            hy = w.hydrology
            for path in hy.rivers:
                end = path[-1]
                x, y = end % w.width, end // w.width
                joins_other = sum(1 for q in hy.rivers if end in q) > 1
                at_border = x in (0, w.width - 1) or y in (0, w.height - 1)
                self.assertTrue(
                    (not w.is_land(end)) or hy.lake[end] or joins_other or at_border,
                    f"seed {seed}: river dangles inland at {end}",
                )

    def test_rivers_flow_downhill(self):
        w = _shared(seed=42)
        filled = w.hydrology.filled
        for path in w.hydrology.rivers:
            for a, b in zip(path, path[1:]):
                self.assertGreater(filled[a], filled[b])

    def test_accumulation_grows_downstream(self):
        w = _shared(seed=42)
        acc = w.hydrology.accumulation
        for path in w.hydrology.rivers:
            land_path = [c for c in path if w.is_land(c)]
            if len(land_path) >= 2:
                self.assertGreater(acc[land_path[-1]], acc[land_path[0]])


class TestWorldgen(unittest.TestCase):
    def test_full_determinism(self):
        a = generate(seed=11, width=48, height=48)
        b = generate(seed=11, width=48, height=48)
        self.assertEqual(a.elevation, b.elevation)
        self.assertEqual(a.biome, b.biome)
        self.assertEqual(a.hydrology.rivers, b.hydrology.rivers)
        self.assertEqual(
            [(s.name, s.x, s.y, s.population) for s in a.settlements],
            [(s.name, s.x, s.y, s.population) for s in b.settlements],
        )

    def test_seed_variety(self):
        a = generate(seed=11, width=48, height=48, with_settlements=False)
        b = generate(seed=12, width=48, height=48, with_settlements=False)
        self.assertNotEqual(a.elevation, b.elevation)

    def test_size_validation(self):
        with self.assertRaises(ValueError):
            generate(seed=1, width=8, height=100)
        with self.assertRaises(ValueError):
            generate(seed=1, width=1025, height=1024)

    def test_extreme_land_fractions(self):
        for frac in (0.05, 0.95):
            w = generate(seed=3, width=48, height=48, land_fraction=frac)
            self.assertEqual(len(w.biome), 48 * 48)


class TestSettlements(unittest.TestCase):
    def test_placement_constraints(self):
        w = _shared(seed=42)
        self.assertGreater(len(w.settlements), 0)
        names = [s.name for s in w.settlements]
        self.assertEqual(len(names), len(set(names)), "duplicate settlement names")
        for s in w.settlements:
            i = w.idx(s.x, s.y)
            self.assertTrue(w.is_land(i), f"{s.name} in water")
            self.assertNotIn(w.biome[i], settlements.HOSTILE_BIOMES)
            self.assertGreater(s.population, 0)
            self.assertLess(s.founded, 900)

    def test_kinds_and_spacing(self):
        import math

        w = _shared(seed=42)
        kinds = {s.kind for s in w.settlements}
        self.assertTrue({"capital", "town", "village"} <= kinds)
        caps = [s for s in w.settlements if s.kind == "capital"]
        for a in caps:
            for b in caps:
                if a is not b:
                    self.assertGreaterEqual(math.hypot(a.x - b.x, a.y - b.y), 18)

    def test_name_quality_filters(self):
        import random

        forge = settlements.NameForge(random.Random(99))
        for _ in range(120):
            name = forge.make()
            raw = name.lower().split()[0]
            self.assertTrue(4 <= len(name) <= 15, name)
            self.assertNotIn(raw, settlements.NameForge._BAD_WORDS)
            cons = settlements.NameForge._CONSONANTS
            self.assertFalse(all(c in cons for c in raw[:3]), f"onset: {name}")

    def test_roman(self):
        self.assertEqual([settlements._roman(n) for n in (2, 4, 9, 14)],
                         ["II", "IV", "IX", "XIV"])


class TestRender(unittest.TestCase):
    def test_html_complete_and_escaped(self):
        w = _shared(seed=42)
        html = render.render_html(w, title="<Realm> & Co")
        for token in ("__META__", "__PACKED__", "__TITLE__", "__COAST__",
                      "__RIVERS__", "__IMAGES__", "__SETTLEMENTS__",
                      "__GAZETTEER__", "__LEGEND__", "__SUBTITLE__"):
            self.assertNotIn(token, html)
        self.assertNotIn("<Realm>", html)
        self.assertIn("&lt;Realm&gt; &amp; Co", html)
        self.assertEqual(html.count("data:image/png;base64"), 4)
        # Packed inspector data: correct length and pure hex for each field.
        packed = json.loads(html.split("const PACKED = ", 1)[1].split(";\n", 1)[0])
        n2 = w.width * w.height * 2
        for key in ("elev", "temp", "moist", "biome"):
            self.assertEqual(len(packed[key]), n2)
            self.assertTrue(all(c in "0123456789abcdef" for c in packed[key]))
        stats = render.world_stats(w)
        self.assertTrue(0 < stats["land_pct"] < 100)
        self.assertGreaterEqual(stats["rivers"], 1)

    def test_no_settlement_empty_state(self):
        w = generate(seed=5, width=48, height=48, with_settlements=False)
        html = render.render_html(w)
        self.assertIn("No settlements on this map", html)


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_end_to_end_with_json(self):
        out = os.path.join(self.dir, "w.html")
        jout = os.path.join(self.dir, "w.json")
        rc = cli.main(["--seed", "5", "--width", "48", "--height", "48",
                       "-o", out, "--json", jout, "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.getsize(out) > 10_000)
        with open(jout, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["seed"], 5)
        self.assertEqual(len(data["elevation"]), 48 * 48)
        self.assertEqual(len(data["biome"]), 48 * 48)
        self.assertIn("stats", data)
        for s in data["settlements"]:
            self.assertIn("name", s)

    def test_bad_output_path(self):
        rc = cli.main(["--seed", "1", "--width", "16", "--height", "16",
                       "-o", os.path.join(self.dir, "no", "such", "dir.html"),
                       "--quiet"])
        self.assertEqual(rc, 2)

    def test_argparse_rejections(self):
        for argv in (["--land", "2"], ["--width", "8"], ["--width", "abc"]):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(argv + ["--quiet"])
            self.assertEqual(ctx.exception.code, 2)

    def test_default_seed_is_random_but_runs(self):
        out = os.path.join(self.dir, "r.html")
        rc = cli.main(["--width", "16", "--height", "16", "-o", out, "--quiet"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(out))


@unittest.skipUnless(
    shutil.which("node") and os.environ.get("JSDOM_PATH"),
    "node + JSDOM_PATH required for DOM test",
)
class TestDOM(unittest.TestCase):
    def test_jsdom_smoke(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "w.html")
            self.assertEqual(
                cli.main(["--seed", "42", "-o", out, "--quiet"]), 0
            )
            env = dict(os.environ, NODE_PATH=os.environ["JSDOM_PATH"])
            proc = subprocess.run(
                ["node", os.path.join(PROJECT, "tests", "dom_check.js"), out],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
