"""Settlement placement and naming.

Settlements are placed by a habitability score — fresh water access, flat
ground, temperate climate, decent rainfall — with minimum-spacing rules so
capitals anchor regions and villages fill in between. Names come from an
order-2 character Markov chain trained on a built-in corpus, with rejection
of duplicates so every map gets unique names. Everything is driven by
`random.Random(seed)`: same seed, same towns.
"""

from __future__ import annotations

import math
import random
from collections import deque

from .biomes import ALPINE, DESERT, GLACIER, LAKE, MARSH, TUNDRA
from .worldgen import Settlement, World

NAME_CORPUS = [
    "Aldermere", "Ashford", "Brackenholm", "Briarwick", "Caldermoor",
    "Cinderfall", "Coldhaven", "Cragmore", "Dunbarrow", "Eastvale",
    "Eldenbrook", "Emberlyn", "Fairmarch", "Fenwick", "Frostmere",
    "Galloway", "Glenhollow", "Greyford", "Harrowgate", "Hartsmere",
    "Havenwood", "Highmoor", "Hollowbrook", "Ironford", "Kestrelmoor",
    "Kingsmere", "Larkspur", "Lindenfell", "Lowdale", "Marrowick",
    "Mistral", "Moorcliff", "Nethermoor", "Northwick", "Oakhampton",
    "Oldcastle", "Pinemarch", "Quillford", "Ravenglass", "Redmane",
    "Rookhaven", "Saltmarsh", "Silverbeck", "Smallbrook", "Snowmere",
    "Stagholt", "Stonebridge", "Stormwall", "Sunderholm", "Swiftwater",
    "Tarnbrook", "Thistlewood", "Thornbury", "Umberfield", "Valewatch",
    "Wandermere", "Westmarch", "Whitford", "Wildebrook", "Windermoor",
    "Wolfden", "Wyrmgate", "Yarrowdale",
]

EVENT_TEMPLATES = [
    "Rebuilt after the flood of {y2}.",
    "Site of the treaty signed in {y2}.",
    "Its market charter dates to {y2}.",
    "Survived the long winter of {y2}.",
    "Famed for the harvest fair held since {y2}.",
    "Walls raised against raiders in {y2}.",
    "A great fire reshaped its streets in {y2}.",
    "Pilgrims have come here every spring since {y2}.",
    "The old bridge was completed in {y2}.",
    "Miners struck silver nearby in {y2}.",
]

HOSTILE_BIOMES = {GLACIER, ALPINE, DESERT, TUNDRA, MARSH}


class NameForge:
    """Order-2 character Markov chain over the corpus."""

    def __init__(self, rng: random.Random, corpus: list[str] | None = None):
        self.rng = rng
        self.chain: dict[str, list[str]] = {}
        self.used: set[str] = set()
        for name in corpus or NAME_CORPUS:
            word = "^^" + name.lower() + "$"
            for k in range(len(word) - 2):
                self.chain.setdefault(word[k : k + 2], []).append(word[k + 2])

    def _candidate(self) -> str:
        out = "^^"
        while len(out) < 16:
            nxt = self.rng.choice(self.chain.get(out[-2:], ["$"]))
            if nxt == "$":
                break
            out += nxt
        return out[2:]

    _BAD_WORDS = {
        "marsh", "march", "haven", "brook", "beach", "ocean", "glacier",
        "tundra", "taiga", "desert", "savanna", "water",
    }
    _CONSONANTS = set("bcdfghjklmnpqrstvwxz")

    def _acceptable(self, raw: str) -> bool:
        if not 5 <= len(raw) <= 12:
            return False
        if raw in self._BAD_WORDS:  # confusing on a map full of real marshes
            return False
        if all(c in self._CONSONANTS for c in raw[:3]):  # "Stmarroor"
            return False
        for k in range(len(raw) - 5):  # stuttering names like "Thermermer"
            if raw[k : k + 3] == raw[k + 3 : k + 6]:
                return False
        return True

    def make(self) -> str:
        for _ in range(200):
            raw = self._candidate()
            if not self._acceptable(raw):
                continue
            name = raw.capitalize()
            if name in self.used:
                continue
            self.used.add(name)
            return name
        # Pathological RNG streak: disambiguate deterministically.
        base = self._candidate().capitalize() or "Nameless"
        n = 2
        while f"{base} {_roman(n)}" in self.used:
            n += 1
        name = f"{base} {_roman(n)}"
        self.used.add(name)
        return name


def _roman(n: int) -> str:
    vals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _water_distance(world: World) -> list[int]:
    """BFS distance (in cells) to the nearest river, lake or coast water."""
    w, h = world.width, world.height
    n = w * h
    dist = [99] * n
    queue: deque[int] = deque()
    river_cells = {c for path in world.hydrology.rivers for c in path}
    for i in range(n):
        if not world.is_land(i) or world.hydrology.lake[i] or i in river_cells:
            dist[i] = 0
            queue.append(i)
    while queue:
        i = queue.popleft()
        x, y = i % w, i // w
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            j = ny * w + nx
            if 0 <= nx < w and 0 <= ny < h and dist[j] > dist[i] + 1:
                dist[j] = dist[i] + 1
                queue.append(j)
    return dist


def _slope(world: World, i: int) -> float:
    w, h = world.width, world.height
    x, y = i % w, i // w
    e = world.elevation
    worst = 0.0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < w and 0 <= ny < h:
            worst = max(worst, abs(e[ny * w + nx] - e[i]))
    return worst


def habitability(world: World, water_dist: list[int], i: int) -> float:
    """0 (uninhabitable) .. ~1 (prime real estate)."""
    if not world.is_land(i) or world.hydrology.lake[i]:
        return 0.0
    if world.biome[i] in HOSTILE_BIOMES:
        return 0.0
    water = max(0.0, 1.0 - water_dist[i] / 7.0)
    flat = max(0.0, 1.0 - _slope(world, i) * 22.0)
    temp = 1.0 - abs(world.temperature[i] - 0.55) * 1.9
    rain = 0.4 + 0.6 * min(1.0, world.moisture[i] * 1.6)
    return max(0.0, water) * max(0.0, flat) * max(0.05, temp) * rain


def place_settlements(world: World) -> list[Settlement]:
    rng = random.Random(world.seed ^ 0x5E771E)
    names = NameForge(rng)
    water_dist = _water_distance(world)
    n = world.width * world.height
    scored = sorted(
        ((habitability(world, water_dist, i), i) for i in range(n)),
        reverse=True,
    )
    scored = [(s, i) for s, i in scored if s > 0.05]
    if not scored:
        return []

    land_cells = sum(1 for i in range(n) if world.is_land(i))
    capitals = max(1, min(3, land_cells // 4500))
    towns = max(2, min(8, land_cells // 1500))
    villages = max(3, min(14, land_cells // 800))
    plan = [("capital", capitals, 18), ("town", towns, 9), ("village", villages, 6)]

    placed: list[Settlement] = []
    diag = math.hypot(world.width, world.height)
    for kind, want, spacing in plan:
        spacing = min(spacing, max(3, int(diag / 8)))
        got = 0
        for score, i in scored:
            if got >= want:
                break
            x, y = i % world.width, i // world.width
            if any(math.hypot(s.x - x, s.y - y) < spacing for s in placed):
                continue
            placed.append(_found(world, rng, names, kind, x, y, score))
            got += 1
    return placed


def _found(
    world: World,
    rng: random.Random,
    names: NameForge,
    kind: str,
    x: int,
    y: int,
    score: float,
) -> Settlement:
    pop_range = {
        "capital": (18000, 90000),
        "town": (1800, 14000),
        "village": (90, 850),
    }[kind]
    lo, hi = pop_range
    population = int(lo + (hi - lo) * (0.35 * rng.random() + 0.65 * score))
    founded = {
        "capital": rng.randint(60, 300),
        "town": rng.randint(250, 620),
        "village": rng.randint(500, 880),
    }[kind]
    event_year = rng.randint(founded + 5, 900)
    note = rng.choice(EVENT_TEMPLATES).format(y2=f"AF {event_year}")
    return Settlement(
        name=names.make(),
        x=x,
        y=y,
        kind=kind,
        population=population,
        founded=founded,
        note=note,
    )
