"""Climate: latitude/altitude temperature and wind-advected moisture.

Temperature peaks at the map's equator (vertical center) and drops toward
the poles and with altitude. Moisture is carried by prevailing winds —
westerlies in the temperate bands, easterlies in the tropics — evaporating
over water and raining out as it climbs terrain, which produces orographic
rain shadows behind mountain ranges.
"""

from __future__ import annotations

from .noise import fbm

LAPSE = 0.55           # temperature lost from sea level to highest peak
EVAPORATION = 0.32     # humidity gained per water cell crossed
BASE_RAIN = 0.055      # fraction of humidity dropped per land cell
UPLIFT_RAIN = 5.0      # extra rain per unit of climb
HUMIDITY_CAP = 1.6


def generate_temperature(
    width: int, height: int, elevation: list[float], sea_level: float, seed: int
) -> list[float]:
    """Temperature grid in [0, 1] (0 = polar, 1 = equatorial sea level)."""
    temp = [0.0] * (width * height)
    half = (height - 1) / 2.0 or 1.0
    for y in range(height):
        lat = abs(y - half) / half  # 0 at equator, 1 at poles
        base = 1.0 - lat * lat * 1.05
        for x in range(width):
            i = y * width + x
            alt = max(0.0, elevation[i] - sea_level) / max(1e-9, 1.0 - sea_level)
            jitter = (fbm(x * 0.05, y * 0.05, seed + 555, octaves=2) - 0.5) * 0.12
            temp[i] = base - alt * LAPSE + jitter
    lo, hi = min(temp), max(temp)
    span = (hi - lo) or 1.0
    return [(t - lo) / span for t in temp]


def wind_direction(y: int, height: int) -> int:
    """+1 = wind blows west->east, -1 = east->west, by latitude band."""
    lat = abs(y - (height - 1) / 2.0) / ((height - 1) / 2.0 or 1.0)
    return -1 if lat < 0.33 else 1  # tropical easterlies, temperate westerlies


def generate_moisture(
    width: int, height: int, elevation: list[float], sea_level: float, seed: int
) -> list[float]:
    """Moisture (annual rainfall proxy) in [0, 1].

    Sweeps each row in the prevailing wind direction, carrying a humidity
    budget that grows over water and is rained out over land, faster on
    uphill slopes. A vertical smoothing pass blends adjacent latitude bands.
    """
    rain = [0.0] * (width * height)
    for y in range(height):
        step = wind_direction(y, height)
        xs = range(width) if step == 1 else range(width - 1, -1, -1)
        humidity = 0.55  # incoming maritime air at the map edge
        prev_elev = sea_level
        for x in xs:
            i = y * width + x
            e = elevation[i]
            if e <= sea_level:
                humidity = min(HUMIDITY_CAP, humidity + EVAPORATION)
                rain[i] = 0.18  # rain over water, only used for shading
                prev_elev = sea_level
                continue
            climb = max(0.0, e - max(prev_elev, sea_level))
            drop = humidity * min(0.85, BASE_RAIN + climb * UPLIFT_RAIN)
            humidity = max(0.0, humidity - drop)
            rain[i] = drop
            prev_elev = e
    # Blend rows so wind bands don't leave hard horizontal seams.
    for _ in range(2):
        blended = rain[:]
        for y in range(height):
            for x in range(width):
                i = y * width + x
                up = rain[i - width] if y > 0 else rain[i]
                down = rain[i + width] if y < height - 1 else rain[i]
                blended[i] = rain[i] * 0.5 + (up + down) * 0.25
        rain = blended
    # Rank-normalize over land: keeps rain-shadow structure (relative wet vs
    # dry) while spreading values across [0,1] so the full biome spectrum is
    # reachable. A handful of orographic peaks would otherwise crush the rest
    # of the map toward zero.
    land = [i for i in range(width * height) if elevation[i] > sea_level]
    if not land:
        return rain
    land.sort(key=lambda i: rain[i])
    denom = max(1, len(land) - 1)
    out = [0.5] * (width * height)  # water keeps a fixed mid value
    for rank, i in enumerate(land):
        base = rank / denom
        jitter = (fbm((i % width) * 0.07, (i // width) * 0.07, seed + 888, octaves=2) - 0.5) * 0.14
        out[i] = min(1.0, max(0.0, base + jitter))
    return out
