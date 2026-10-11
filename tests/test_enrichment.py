from datetime import date

from uwagent.enrichment import resolve
from uwagent.facts import Fact, FactSet

TODAY = date(2026, 6, 29)


def test_higher_ranked_source_wins():
    facts = FactSet([Fact("year_built", 1990, "reply"), Fact("year_built", 1985, "submission")])
    assert facts.get("year_built") == 1990 and facts.fact("year_built").source == "reply"


def test_resolve_fills_system_fields_with_provenance():
    facts = FactSet.from_submission({
        "distance_to_fire_department": 1.2, "dist_to_nearest_fire_hydrant": 200, "fire_department_type": "Career",
        "roof_material": "Wood Shake", "siding_material": "Stucco", "square_feet": 2000,
        "construction_type": "Frame", "state": "CO", "year_built": 1940,
    })
    resolve("LEAD-T1", facts, TODAY)
    assert facts.get("protection_class") == "3" and facts.fact("protection_class").source == "enrichment"
    assert facts.get("roof_classification") == "Class C" and facts.fact("roof_classification").source == "derived"
    assert facts.get("replacement_cost") == 660000 and facts.get("p_f") is not None
    assert facts.get("has_knob_and_tube_wiring") is True and facts.get("pool_type") == "None"
    assert facts.get("broker_tier") in ("Tier 1", "Tier 2")
