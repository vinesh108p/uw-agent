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
    assert "Terms that would apply to a quote:" in email["body"] and "Personal liability coverage is excluded" in email["body"]

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


def test_ask_broker_needs_a_question_when_there_is_nothing_to_ask(tmp_path, registry):
    from uwagent.service import NeedsNote

    queue = load_queue(42)
    assert queue[9]["lead"]["lead_id"] == "LEAD-00000042-009"
    queue[9]["lead"]["fields"].update({"acreage": 0.5, "foundation_type": "Piers", "post_pier_supports_living_area": True,
                                       "deck_height_ft": 6})
    svc = make_service(tmp_path, registry, {42: queue})
    svc.ingest_queue(seed=42)
    svc.advance_all()
    card = svc.store.open_card_for("LEAD-00000042-009")
    with pytest.raises(NeedsNote):
        svc.resolve_card(card["id"], "ask_broker")
    assert svc.mailbox.emails_for_lead("LEAD-00000042-009") == []


def test_any_uw_decision_resolves_reply_flags(service):
    service.advance_all()
    lead_id = "LEAD-00000042-002"
    service.store.add_flag(lead_id, 0, "Broker reply needs review (negotiation): too strict")
    service.resolve_card(service.store.open_card_for(lead_id)["id"], "ask_broker", note="Is the home occupied year-round?")
    assert service.store.open_flags(lead_id) == []


def test_advance_does_nothing_while_a_card_is_open(service):
    service.advance_all()
    lead_id = "LEAD-00000042-000"
    service.store.update_case(lead_id, state="ASSESSED")
    assert service.advance(lead_id) is None
    assert [c["lead_id"] for c in service.store.list_open_cards()].count(lead_id) == 1


def test_start_over_waits_for_runs_in_flight(tmp_path, registry, monkeypatch):
    import threading
    import time

    import uwagent.service as service_module

    svc = make_service(tmp_path, registry, {42: load_queue(42)})
    svc.ingest_queue(seed=42)
    started, release = threading.Event(), threading.Event()
    real_run = service_module.run_agent

    def slow_run(ctx, **kwargs):
        started.set()
        release.wait(5)  # stands in for model latency
        return real_run(ctx, **kwargs)

    monkeypatch.setattr(service_module, "run_agent", slow_run)
    run = threading.Thread(target=lambda: svc.advance("LEAD-00000042-009"))
    run.start()
    assert started.wait(5)
    reset = threading.Thread(target=svc.reset)
    reset.start()
    time.sleep(0.3)
    assert reset.is_alive()  # Start over waits for the run that holds the lead's lock
    release.set()
    run.join(5)
    reset.join(5)
    assert svc.store.lead_ids() == [] and svc.mailbox.sent == []
    assert svc.advance("LEAD-00000042-009") is None  # a run queued behind the reset finds nothing to do
