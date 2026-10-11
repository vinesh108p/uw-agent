"""Value domains for branching over unknown inputs. Numeric samples straddle the FigJam thresholds."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from ..registry import Registry

NUMERIC_SAMPLES: dict[str, tuple[Any, ...]] = {
    "months_unoccupied": (0, 1, 3),
    "year_built": (1940, 1990, 2010),
    "deck_height_ft": (6, 10, 14),
    "plumbing_age_years": (10, 40),
    "water_heater_age_years": (5, 15),
    "electrical_panel_size_amps": (100, 200),
    "kyc_score": (3, 6, 9),
    "p_f": (0.10, 0.30, 0.70),
    "square_feet": (3000, 8000),
    "dist_to_nearest_fire_hydrant": (500, 2000),
    "min_distance_to_neighbor_ft": (10, 50),
    "slope_angle_deg": (5.0, 30.0),
    "roof_replacement_year": (1995, 2020),
    "acreage": (0.5, 3.0),
}


def make_domain(registry: Registry) -> Callable[[str], Sequence[Any] | None]:
    def domain(name: str) -> Sequence[Any] | None:
        if name in NUMERIC_SAMPLES:
            return NUMERIC_SAMPLES[name]
        if name not in registry:
            return None
        field = registry[name]
        if field.kind == "select":
            return field.options
        if field.kind == "toggle":
            return (True, False)
        return None

    return domain
