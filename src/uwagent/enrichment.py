"""Fill system-owned gaps: world lookups, registry derivations and FigJam defaults, iterated to a fixed point."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping

from . import world
from .facts import SOURCE_RANK, Fact, FactSet

ROOF_CLASS = {
    "Architecture Shingles": "Class A",
    "Asphalt Fiberglass Composite": "Class A",
    "Clay Tile": "Class A",
    "Concrete Tile": "Class A",
    "Metal Shingles / Sheets": "Class A",
    "Slate": "Class A",
    "Standing Seam Metal": "Class A",
    "Wood Shake": "Class C",
    "Wood Shingle": "Class C",
    "Other": "Class B",
}

SIDING_CLASS = {
    "Brick / Masonry Veneer": "A",
    "Fire Resistive": "A",
    "Cement Fiber": "B",
    "Stucco": "B",
    "Aluminum / Steel": "C",
    "Vinyl": "C",
    "Wood": "D",
    "Wood Shake / Shingle": "D",
    "Other": "C",
}

Lookup = Callable[[str, Mapping[str, Any], date], Any]


def _knob_and_tube_default(lead_id: str, values: Mapping[str, Any], today: date) -> bool | None:
    year_built = values.get("year_built")
    return None if year_built is None else year_built < 1950


# (field, source, detail, lookup). Order matters within a pass: geo and siding class feed the fire simulation.
RESOLVERS: list[tuple[str, str, str, Lookup]] = [
    ("broker_tier", "enrichment", "crm", lambda lid, v, t: world.crm_broker_tier(lid)),
    ("has_primary_policy_with_stand", "enrichment", "crm", lambda lid, v, t: world.crm_has_primary_policy(lid)),
    ("kyc_score", "enrichment", "kyc_vendor", lambda lid, v, t: world.kyc_score(lid)),
    ("slope_angle_deg", "enrichment", "usgs_dem", lambda lid, v, t: world.slope_angle_deg(lid)),
    ("min_distance_to_neighbor_ft", "enrichment", "building_footprints", lambda lid, v, t: world.min_distance_to_neighbor_ft(lid)),
    ("vegetation_clearance", "enrichment", "aerial_imagery", lambda lid, v, t: world.vegetation_clearance(lid)),
    ("road_access", "enrichment", "road_graph", lambda lid, v, t: world.road_access(lid)),
    ("roof_classification", "derived", "roof_material", lambda lid, v, t: ROOF_CLASS.get(v.get("roof_material"))),
    ("siding_classification", "derived", "siding_material", lambda lid, v, t: SIDING_CLASS.get(v.get("siding_material"))),
    ("protection_class", "enrichment", "iso_ppc", lambda lid, v, t: world.ppc(v)),
    ("protection_class", "default", "FigJam: assume PC 9 when missing", lambda lid, v, t: "9"),
    ("replacement_cost", "enrichment", "rce_estimator", lambda lid, v, t: world.replacement_cost(v)),
    ("p_f", "enrichment", "fire_simulation", lambda lid, v, t: world.fire_probability(v)),
    ("has_knob_and_tube_wiring", "default", "FigJam: assume from year built (before 1950)", _knob_and_tube_default),
    ("pool_type", "default", "FigJam: nothing on imagery, assume no pool", lambda lid, v, t: "None"),
]


def resolve(lead_id: str, facts: FactSet, today: date, max_passes: int = 3) -> list[Fact]:
    """Add facts for missing system values until nothing changes; returns the facts added."""
    added: list[Fact] = []
    for _ in range(max_passes):
        changed = False
        for field, source, detail, lookup in RESOLVERS:
            current = facts.fact(field)
            if current is not None and SOURCE_RANK[current.source] >= SOURCE_RANK[source]:
                continue
            value = lookup(lead_id, facts.values(), today)
            if value is None:
                continue
            fact = Fact(field, value, source, detail)
            facts.add(fact)
            added.append(fact)
            changed = True
        if not changed:
            break
    return added
