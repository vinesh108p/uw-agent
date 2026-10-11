import json

import pytest

from uwagent.config import ROOT

from tests.fakes import make_service
from tests.support import load_queue

GOLD = json.loads((ROOT / "evals" / "gold" / "seed42.json").read_text())


@pytest.fixture
def service(tmp_path, registry):
    svc = make_service(tmp_path, registry, {42: load_queue(42)})
    svc.ingest_queue(seed=42)
    return svc


def test_offline_morning_queue_matches_gold(service):
    service.advance_all()
    for lead_id, gold in GOLD.items():
        emails = service.mailbox.emails_for_lead(lead_id)
        if gold["action"] == "send_followup":
            assert len(emails) == 1 and set(emails[0]["metadata"]["items"]) == set(gold["must_ask"])
        else:
            assert emails == [] and service.store.open_card_for(lead_id)["payload"]["recommendation"] == gold["recommendation"]


def test_tier_1_leads_are_processed_first(service):
    tiers = [service.priority(result.lead_id)[0] for result in service.advance_all()]
    assert tiers == sorted(tiers) and tiers[0] == 1


def test_uw_approval_sends_one_consolidated_email(service):
    service.advance_all()
    lead_id = "LEAD-00000042-002"
    service.resolve_card(service.store.open_card_for(lead_id)["id"], "approve")
    [email] = service.mailbox.emails_for_lead(lead_id)
    assert set(email["metadata"]["items"]) == set(GOLD[lead_id]["must_ask"])
    assert "Terms to expect on the quote:" in email["body"] and "Personal liability coverage is excluded" in email["body"]

from uwagent.simulator import simulate_reply


def test_every_lead_with_asks_gets_exactly_one_email_before_its_outcome(service, registry):
    service.advance_all()
    for card in service.store.list_open_cards():
        if card["payload"]["recommendation"] == "approve":
            service.resolve_card(card["id"], "approve")
    waiting = [lid for lid in service.store.lead_ids() if service.store.get_case(lid)["state"] == "FOLLOW_UP_SENT"]
    assert len(waiting) == 7
    for lead_id in waiting:
        body, _ = simulate_reply("complete", service.last_followup_items(lead_id), registry, lead_id, service.assess(lead_id).values)
        service.receive_reply(lead_id, body)
        assert [e["metadata"]["kind"] for e in service.mailbox.emails_for_lead(lead_id)].count("followup") == 1
    assert {service.store.get_case(lid)["state"] for lid in waiting} <= {"QUOTED", "AWAITING_UW"}
