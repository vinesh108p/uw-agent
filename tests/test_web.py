from fastapi.testclient import TestClient

from uwagent.web import create_app

from tests.fakes import make_service
from tests.support import load_queue


def client_for(tmp_path, registry):
    service = make_service(tmp_path, registry, {42: load_queue(42)})
    return TestClient(create_app(service)), service


def test_queue_page_speaks_underwriter(tmp_path, registry):
    client, _ = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    page = client.get("/").text
    assert "Needs your decision (6)" in page and "Priya Whitfield" in page
    assert "Tier 1" in page and "Waiting on broker" in page
    assert "AWAITING_UW" not in page and "FOLLOW_UP_SENT" not in page
    assert client.get("/static/app.css").status_code == 200


def test_case_page_leads_with_where_it_stands(tmp_path, registry):
    client, _ = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    page = client.get("/cases/LEAD-00000042-009").text
    assert "Where this stands" in page and "$1,025,000" in page
    main = page.split("Details for reviewers")[0]
    assert [key for key in registry.names() if "_" in key and key in main] == []


def test_browser_decline_shows_a_banner(tmp_path, registry):
    client, service = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    card = service.store.open_card_for("LEAD-00000042-000")
    page = client.post(f"/cards/{card['id']}", data={"choice": "decline", "back": "/"}, headers={"accept": "text/html"}).text
    assert "Decline notice sent" in page and service.store.get_case("LEAD-00000042-000")["state"] == "DECLINED"


def test_start_over_clears_leads_and_rotates_the_instance(tmp_path, registry):
    client, service = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    before = service.store.instance_id
    page = client.post("/demo/reset", headers={"accept": "text/html"}).text
    assert "Started over" in page and service.store.lead_ids() == [] and service.store.instance_id != before
