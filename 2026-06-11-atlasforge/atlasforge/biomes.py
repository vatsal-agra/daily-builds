"""Whittaker-style biome classification from temperature and moisture."""

from __future__ import annotations

OCEAN = "ocean"
SHALLOWS = "shallows"
LAKE = "lake"
BEACH = "beach"
GLACIER = "glacier"
ALPINE = "alpine"
TUNDRA = "tundra"
TAIGA = "taiga"
COLD_STEPPE = "cold steppe"
TEMPERATE_FOREST = "temperate forest"
TEMPERATE_RAINFOREST = "temperate rainforest"
GRASSLAND = "grassland"
SHRUBLAND = "shrubland"
DESERT = "desert"
SAVANNA = "savanna"
TROPICAL_FOREST = "tropical forest"
TROPICAL_RAINFOREST = "tropical rainforest"
MARSH = "marsh"

ALL_BIOMES = [
    OCEAN, SHALLOWS, LAKE, BEACH, GLACIER, ALPINE, TUNDRA, TAIGA,
    COLD_STEPPE, TEMPERATE_FOREST, TEMPERATE_RAINFOREST, GRASSLAND,
    SHRUBLAND, DESERT, SAVANNA, TROPICAL_FOREST, TROPICAL_RAINFOREST, MARSH,
]

# Base colors (hillshading is applied at render time).
BIOME_COLORS = {
    OCEAN: (38, 70, 112),
    SHALLOWS: (66, 110, 152),
    LAKE: (78, 132, 168),
    BEACH: (214, 198, 156),
    GLACIER: (235, 240, 244),
    ALPINE: (158, 152, 144),
    TUNDRA: (176, 180, 158),
    TAIGA: (94, 124, 96),
    COLD_STEPPE: (168, 166, 122),
    TEMPERATE_FOREST: (88, 134, 78),
    TEMPERATE_RAINFOREST: (62, 116, 82),
    GRASSLAND: (144, 162, 96),
    SHRUBLAND: (172, 162, 110),
    DESERT: (210, 184, 130),
    SAVANNA: (178, 168, 92),
    TROPICAL_FOREST: (74, 134, 66),
    TROPICAL_RAINFOREST: (44, 110, 58),
    MARSH: (104, 142, 110),
}


def classify_cell(
    elevation: float,
    sea_level: float,
    temperature: float,
    moisture: float,
    is_lake: bool,
    near_coast: bool,
) -> str:
    if elevation <= sea_level:
        return SHALLOWS if sea_level - elevation < 0.035 else OCEAN
    if is_lake:
        return LAKE
    alt = (elevation - sea_level) / max(1e-9, 1.0 - sea_level)
    if temperature < 0.14:
        return GLACIER
    if alt > 0.72:
        return GLACIER if temperature < 0.35 else ALPINE
    if near_coast and alt < 0.04 and moisture < 0.75 and temperature > 0.3:
        return BEACH
    if alt < 0.06 and moisture > 0.82 and temperature > 0.3:
        return MARSH
    if temperature < 0.3:
        return TUNDRA if moisture < 0.4 else TAIGA
    if temperature < 0.62:
        if moisture < 0.18:
            return COLD_STEPPE
        if moisture < 0.42:
            return GRASSLAND
        if moisture < 0.72:
            return TEMPERATE_FOREST
        return TEMPERATE_RAINFOREST
    # hot
    if moisture < 0.16:
        return DESERT
    if moisture < 0.34:
        return SHRUBLAND
    if moisture < 0.55:
        return SAVANNA
    if moisture < 0.78:
        return TROPICAL_FOREST
    return TROPICAL_RAINFOREST


def classify(
    width: int,
    height: int,
    elevation: list[float],
    sea_level: float,
    temperature: list[float],
    moisture: list[float],
    lake: list[bool],
) -> list[str]:
    n = width * height
    is_water = [elevation[i] <= sea_level for i in range(n)]
    near_coast = [False] * n
    for i in range(n):
        if is_water[i]:
            continue
        x, y = i % width, i // width
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and is_water[ny * width + nx]:
                near_coast[i] = True
                break
    return [
        classify_cell(
            elevation[i], sea_level, temperature[i], moisture[i], lake[i], near_coast[i]
        )
        for i in range(n)
    ]
