"""Deterministic stand-ins for third-party and internal data sources (the simulated "world").

Production sources: CRM/policy admin, Verisk ISO PPC, an RCE estimator (360Value/CoreLogic),
Stand's fire simulation, USGS DEM, building footprints, aerial imagery, a road graph, a KYC vendor.
Every function returns None when the source cannot answer (UNAVAILABLE). Values are keyed by a
hash of the lead id so runs are reproducible. Evals may import this module (it is the world, not
the engine).
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping


def unit(lead_id: str, salt: str) -> float:
    digest = hashlib.sha256(f"{lead_id}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16) / 0x1_0000_0000


def crm_broker_tier(lead_id: str) -> str:
    return "Tier 1" if unit(lead_id, "broker_tier") < 0.4 else "Tier 2"


def crm_has_primary_policy(lead_id: str) -> bool:
    return False  # mirrors the generator's base leads: no existing Stand primary policy


def kyc_score(lead_id: str) -> int | None:
    if unit(lead_id, "kyc_available") < 0.15:
        return None
    return 1 + int(unit(lead_id, "kyc_value") * 4)


def ppc(values: Mapping[str, Any]) -> str | None:
    distance = values.get("distance_to_fire_department")
    hydrant = values.get("dist_to_nearest_fire_hydrant")
    if distance is None or hydrant is None:
        return None
    if distance > 5:
        return "10"
    if hydrant > 1000:
        return "9"
    staffing = {"Career": 3, "Mostly Career": 4, "Mostly Volunteer": 5, "Volunteer": 6}
    return str(staffing.get(values.get("fire_department_type"), 5))


RCE_RATE = {"Frame": 300, "Masonry": 330, "Concrete": 340, "Steel": 350, "Log": 320, "Modular": 260, "Mobile / Manufactured": 180}
STATE_FACTOR = {"CA": 1.35, "CO": 1.10, "OR": 1.10, "FL": 1.05, "AZ": 1.00, "NC": 0.95}


def replacement_cost(values: Mapping[str, Any]) -> int | None:
    square_feet = values.get("square_feet")
    if square_feet is None:
        return None
    rate = RCE_RATE.get(values.get("construction_type"), 300)
    factor = STATE_FACTOR.get(values.get("state"), 1.0)
    return int(round(square_feet * rate * factor, -3))


def slope_angle_deg(lead_id: str) -> float:
    return round(2 + 10 * unit(lead_id, "slope"), 1)


def min_distance_to_neighbor_ft(lead_id: str) -> int:
    return 25 + int(80 * unit(lead_id, "neighbor"))


def vegetation_clearance(lead_id: str) -> str:
    return "Adequate" if unit(lead_id, "vegetation") < 0.8 else "Marginal"


def road_access(lead_id: str) -> str:
    return "Multiple Access Points" if unit(lead_id, "road") < 0.85 else "Single Access Point"


VEGETATION_RISK = {"Adequate": 0.0, "Marginal": 0.10, "Too Close": 0.25, "Unknown": 0.10}
SIDING_RISK = {"A": 0.0, "B": 0.03, "C": 0.08, "D": 0.15}


def fire_probability(values: Mapping[str, Any]) -> float | None:
    needed = ("slope_angle_deg", "vegetation_clearance", "min_distance_to_neighbor_ft", "siding_classification")
    if any(values.get(name) is None for name in needed):
        return None
    neighbor = values["min_distance_to_neighbor_ft"]
    probability = (
        0.05
        + 0.01 * max(0.0, values["slope_angle_deg"] - 10)
        + VEGETATION_RISK.get(values["vegetation_clearance"], 0.10)
        + (0.15 if neighbor < 15 else 0.05 if neighbor < 30 else 0.0)
        + SIDING_RISK.get(values["siding_classification"], 0.08)
    )
    return round(min(0.95, max(0.01, probability)), 2)
