from uwagent.models import Lead

from tests.support import load_queue


def test_seed42_fixture_is_a_registry_shaped_queue(registry):
    queue = load_queue(42)
    assert len(queue) == 10 and queue[0]["lead"]["lead_id"] == "LEAD-00000042-000"
    lead = Lead.model_validate(queue[0]["lead"])
    assert set(lead.fields) == set(registry.names()) and lead.received_date.year == 2026
    assert "injected_archetypes" in queue[0]["debug"]
