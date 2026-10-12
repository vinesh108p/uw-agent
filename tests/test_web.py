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
