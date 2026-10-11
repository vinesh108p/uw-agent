from datetime import date

import pytest

from uwagent.playbook import PLAYBOOK, account, evaluate_playbook
from uwagent.playbook.base import Kind, View

TODAY = date(2026, 6, 29)
STAND_PRIMARY = {"has_primary_policy_with_stand": True, "broker_tier": "Tier 2"}


@pytest.mark.parametrize("tree, values, expected", [
    (account.occupancy, {"months_unoccupied": 3, **STAND_PRIMARY}, (Kind.DECLINE, "")),
    (account.occupancy, {"is_rental": "Short-Term Rentals", **STAND_PRIMARY}, (Kind.CONDITION, "str_surcharge_endorsement")),
    (account.profile, {"kyc_score": 9}, (Kind.CONDITION, "exclude_liability")),
    (account.trusts, {"residence_held_in_trust": True}, (Kind.ADVISORY, "trust_questionnaire")),
    (account.pools, {"pool_type": "Inground", "pool_security": "Fenced", "pool_has_diving_board_or_slide": True},
     (Kind.CONDITION, "pool_limitation_of_liability")),
    (account.replacement_cost, {"coverage_a": 760_000, "replacement_cost": 500_000}, (Kind.CONDITION, "rc_quote_at_rce")),
    (account.protection_class, {"protection_class": "10", "dist_to_nearest_fire_hydrant": 5000,
                                "road_access": "Limited / Dead-end / No Turnaround"}, (Kind.DECLINE, "")),
])
def test_account_trees(tree, values, expected):
    outcome = tree(View(values, TODAY))[0]
    assert (outcome.kind, outcome.code) == expected


def test_playbook_registers_all_twelve_pages(registry):
    results = evaluate_playbook({"protection_class": "4"}, registry, TODAY)
    assert len(PLAYBOOK) == 12 and [r.tree for r in results] == list(PLAYBOOK)
