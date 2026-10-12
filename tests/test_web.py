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


def test_conversation_times_are_localised_by_the_browser(tmp_path, registry):
    client, _ = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    page = client.get("/cases/LEAD-00000042-009").text
    assert page.count("data-when") >= 3 and 'datetime="20' in page


def test_banner_queue_and_case_agree_on_what_was_asked(tmp_path, registry):
    client, service = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    card = service.store.open_card_for("LEAD-00000042-002")
    page = client.post(f"/cards/{card['id']}", data={"choice": "ask_broker", "note": "Is the home occupied?", "back": "/"},
                       headers={"accept": "text/html"}).text
    assert page.count("6 items and your question") >= 2  # the banner and the queue row say the same thing
    assert "6 items and your question" in client.get("/cases/LEAD-00000042-002").text


def test_start_over_with_the_mailbox_down_clears_nothing(tmp_path, registry):
    client, service = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    service.mailbox.fail = True
    page = client.post("/demo/reset", headers={"accept": "text/html"}).text
    assert "did not respond" in page and len(service.store.lead_ids()) == 10


def test_paste_reply_box_has_a_label_and_missing_addresses_are_marked(tmp_path, registry):
    client, _ = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    assert 'for="paste-body"' in client.get("/cases/LEAD-00000042-009").text
    assert "is-missing" in client.get("/").text  # lead 000 has no street address


def test_a_lead_not_worked_yet_shows_its_real_tier_and_checks(tmp_path, registry):
    client, service = client_for(tmp_path, registry)
    service.ingest_queue(seed=42)  # ingested only: no agent run, no stored assessment
    page = client.get("/cases/LEAD-00000042-009").text
    assert "Tier ?" not in page and "checks passed" in page


def test_pasting_a_reply_shows_a_banner(tmp_path, registry):
    client, _ = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    page = client.post("/cases/LEAD-00000042-009/reply", data={"body": "1. 0.5"}, headers={"accept": "text/html"}).text
    assert "Reply recorded. Quote sent to" in page


def test_queue_lists_tier_1_brokers_first(tmp_path, registry):
    client, service = client_for(tmp_path, registry)
    client.post("/queue", data={"seed": "42"})
    page = client.get("/").text
    waiting = service.board()["needs_uw"]
    tiers = [row["tier"] for row in waiting]
    assert tiers == sorted(tiers) and tiers[0] == 1  # lower number = higher priority
    positions = [page.index(f'id="card-{row["card"]["id"]}"') for row in waiting]
    assert positions == sorted(positions)  # and the page shows the cards in that order
