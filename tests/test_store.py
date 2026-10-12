from uwagent.facts import Fact
from uwagent.models import UWDecision
from uwagent.store import Store


def test_store_roundtrip(seed42, tmp_path):
    store = Store(tmp_path / "s.db")
    lead = seed42["LEAD-00000042-009"]
    store.upsert_lead(lead)
    store.update_case(lead.lead_id, state="FOLLOW_UP_SENT", rounds_sent=1)
    store.upsert_lead(lead)  # re-ingesting keeps progress
    assert store.get_case(lead.lead_id)["state"] == "FOLLOW_UP_SENT" and store.get_lead(lead.lead_id) == lead
    store.add_fact(lead.lead_id, Fact("acreage", 0.5, "reply", "reply r1"))
    assert store.facts_for(lead.lead_id) == [Fact("acreage", 0.5, "reply", "reply r1")]
    row = store.enqueue_outbox(lead.lead_id, "followup", 1, {"subject": "a"})
    assert store.enqueue_outbox(lead.lead_id, "followup", 1, {"subject": "b"})["id"] == row["id"]
    card = store.create_card(lead.lead_id, 1, {"summary": "x"})
    assert store.close_card(card, "approve") is True
    store.add_decision(card, lead.lead_id, 1, "approve", "", ("condition:exclude_liability",))
    assert store.latest_decision(lead.lead_id) == UWDecision("approve", "", 1, ("condition:exclude_liability",))
def test_reset_starts_over_with_a_new_instance_id(seed42, tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_lead(seed42["LEAD-00000042-009"])
    row = store.enqueue_outbox("LEAD-00000042-009", "followup", 1, {"subject": "a"})
    assert row["created_at"].endswith("Z") and "." in row["created_at"]
    before = store.instance_id
    store.reset()
    assert store.lead_ids() == [] and store.outbox_for("LEAD-00000042-009") == []
    assert store.instance_id != before and Store(tmp_path / "s.db").instance_id == store.instance_id
