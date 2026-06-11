"""Pipeline orchestrator: seed -> fully populated World."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import biomes as biome_mod
from .climate import generate_moisture, generate_temperature
from .hydrology import Hydrology, compute_hydrology
from .terrain import generate_elevation, sea_level_for_land_fraction


@dataclass
class Settlement:
    name: str
    x: int
    y: int
    kind: str  # "capital" | "town" | "village"
    population: int
    founded: int
    note: str


@dataclass
class World:
    seed: int
    width: int
    height: int
    sea_level: float
    elevation: list[float]
    temperature: list[float]
    moisture: list[float]
    biome: list[str]
    hydrology: Hydrology
    settlements: list[Settlement] = field(default_factory=list)

    def idx(self, x: int, y: int) -> int:
        return y * self.width + x

    def is_land(self, i: int) -> bool:
        return self.elevation[i] > self.sea_level


def generate(
    seed: int = 0,
    width: int = 160,
    height: int = 160,
    land_fraction: float = 0.38,
    with_settlements: bool = True,
) -> World:
    if width < 16 or height < 16:
        raise ValueError("map size must be at least 16x16")
    if width * height > 1_048_576:
        raise ValueError("map size too large (max 1,048,576 cells = 1024x1024)")
    elevation = generate_elevation(width, height, seed)
    sea_level = sea_level_for_land_fraction(elevation, land_fraction)
    temperature = generate_temperature(width, height, elevation, sea_level, seed)
    moisture = generate_moisture(width, height, elevation, sea_level, seed)
    hydro = compute_hydrology(width, height, elevation, sea_level, moisture)
    biome = biome_mod.classify(
        width, height, elevation, sea_level, temperature, moisture, hydro.lake
    )
    world = World(
        seed=seed,
        width=width,
        height=height,
        sea_level=sea_level,
        elevation=elevation,
        temperature=temperature,
        moisture=moisture,
        biome=biome,
        hydrology=hydro,
    )
    if with_settlements:
        from .settlements import place_settlements

        world.settlements = place_settlements(world)
    return world
