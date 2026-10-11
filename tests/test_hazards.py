from datetime import date

import pytest

from uwagent.playbook import hazards
from uwagent.playbook.base import Kind, View, evaluate
from uwagent.playbook.domains import make_domain

TODAY = date(2026, 6, 29)
TIER2 = {"broker_tier": "Tier 2", "has_primary_policy_with_stand": False}


@pytest.mark.parametrize("tree, values, expected", [
    (hazards.post_pier, {"foundation_type": "Piers", "post_pier_supports_living_area": True}, (Kind.DECLINE, "")),
    (hazards.post_pier, {"foundation_type": "Piers", "post_pier_supports_living_area": False, "year_built": 2005,
                         "deck_height_ft": 10}, (Kind.CONDITION, "surcharge_25_deck")),
    (hazards.fire_simulation, {"p_f": 0.8, "road_access": "Multiple Access Points", "min_distance_to_neighbor_ft": 12}, (Kind.DECLINE, "")),
    (hazards.roof, {"p_f": 0.3, "roof_classification": "Class C"}, (Kind.CONDITION, "roof_class_a_first_term")),
    (hazards.siding, {"siding_material": "Wood Shake / Shingle", "p_f": 0.7}, (Kind.CONDITION, "siding_class_a_uw_period")),
    (hazards.electrical, {"has_knob_and_tube_wiring": False, "electrical_panel_brand": "Federal Pacific",
                          "electrical_panel_size_amps": 200, **TIER2}, (Kind.DECLINE, "")),
    (hazards.plumbing, {"plumbing_age_years": 40, "water_heater_type": "Tankless", "broker_tier": "Tier 1"},
     (Kind.CONDITION, "plumbing_inspection_first_term")),
])
def test_hazard_trees(tree, values, expected):
    outcome = tree(View(values, TODAY))[0]
    assert (outcome.kind, outcome.code) == expected


def test_tall_deck_with_unknown_support_is_a_certain_decline(registry):
    values = {"foundation_type": "Piers", "deck_height_ft": 20, "year_built": 2010}
    result = evaluate("post_pier", hazards.post_pier, values, TODAY, make_domain(registry))
    assert result.certain_decline and result.relevant_unknowns == set()
