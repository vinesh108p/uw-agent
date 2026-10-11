import json

import httpx
import respx

from uwagent.clients import LeadgenClient, MailboxClient


@respx.mock
def test_harness_clients():
    respx.post("http://leadgen.test/queue").mock(return_value=httpx.Response(200, json={"seed": 42, "count": 1, "difficulty": "mixed", "lead_ids": ["L1"]}))
    respx.get("http://leadgen.test/leads/L1").mock(return_value=httpx.Response(200, json={
        "lead_id": "L1", "received_at": "2026-06-29T07:00:00Z", "source": "agent_portal", "fields": {"city": "Bend"}}))
    route = respx.post("http://mail.test/emails").mock(return_value=httpx.Response(200, json={"id": 7, "lead_id": "L1", "received_at": "x"}))
    leadgen = LeadgenClient("http://leadgen.test")
    assert leadgen.create_queue(seed=42)["lead_ids"] == ["L1"] and leadgen.get_lead("L1").fields == {"city": "Bend"}
    sent = MailboxClient("http://mail.test").send(lead_id="L1", to="a@b.example", from_="uw@stand.example", subject="s",
                                                   body="b", metadata={}, idempotency_key="k1")
    assert sent["id"] == 7 and route.calls[0].request.headers["Idempotency-Key"] == "k1"
    assert json.loads(route.calls[0].request.content)["from"] == "uw@stand.example"
