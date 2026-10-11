import json

import pytest

from uwagent.assessment import build_assessment
from uwagent.config import ROOT
from uwagent.facts import Fact
from uwagent.models import UWDecision

GOLD = json.loads((ROOT / "evals" / "gold" / "seed42.json").read_text())


@pytest.mark.parametrize("lead_id", sorted(GOLD))
def test_seed42_matches_blind_gold(seed42, registry, lead_id):
    gold = GOLD[lead_id]
    assessment = build_assessment(seed42[lead_id], registry)
    assert assessment.allowed_actions == [gold["action"]]
    assert assessment.required_ask_keys == set(gold["must_ask"])
    if gold["action"] == "request_uw_decision":
        assert assessment.recommendation == gold["recommendation"]
    else:
        assert assessment.followup_format == gold["format"]


def test_uw_review_then_one_email_with_terms_then_quote(seed42, registry):
    lead = seed42["LEAD-00000042-002"]  # KYC 8 (liability exclusion) and six things to ask
    review = build_assessment(lead, registry)
    approval = UWDecision("approve", scope=tuple(review.scope))
    email = build_assessment(lead, registry, decision=approval)
    assert email.allowed_actions == ["send_followup"] and email.terms == ["Personal liability coverage is excluded"]
    trust = next(a for a in email.required_asks if a.key == "trust_name")
    assert trust.kind == "conditional" and trust.note.startswith("Only if")
    answers = [Fact(k, v, "reply", "reply r1") for k, v in {
        "residence_held_in_trust": False, "coverage_a": 500000, "roof_shape": "Hip",
        "electrical_panel_brand": "Square D", "dist_to_nearest_fire_hydrant": 300}.items()]
    quote = build_assessment(lead, registry, extra_facts=answers, decision=approval, round_=1)
    assert quote.allowed_actions == ["mark_quote_ready"]  # same scope as approved: no second UW click


def test_ask_broker_without_a_question_cannot_quote_a_decline_lead(seed42, registry):
    base = seed42["LEAD-00000042-009"]
    complete = base.model_copy(update={"fields": {**base.fields, "acreage": 0.5, "foundation_type": "Piers",
                                                  "post_pier_supports_living_area": True, "deck_height_ft": 6}})
    assessment = build_assessment(complete, registry, decision=UWDecision("ask_broker", round=0))
    assert assessment.allowed_actions == ["request_uw_decision"]


def test_review_only_leads_recommend_approve(seed42, registry):
    assert build_assessment(seed42["LEAD-00000042-007"], registry).allowed_recommendations == ["approve"]


def test_the_card_shows_the_asks_that_would_be_sent(seed42, registry):
    assessment = build_assessment(seed42["LEAD-00000042-006"], registry)
    assert assessment.required_asks == [] and len(assessment.released_asks) > 10
