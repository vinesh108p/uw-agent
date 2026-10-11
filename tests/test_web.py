from fastapi.testclient import TestClient

from uwagent.web import create_app

from tests.fakes import make_service
from tests.support import load_queue


def test_board_flow(tmp_path, registry):
    service = make_service(tmp_path, registry, {42: load_queue(42)})
    client = TestClient(create_app(service))
    assert client.post("/queue", data={"seed": "42"}, follow_redirects=False).status_code == 303
    page = client.get("/").text
    assert "Needs you (6)" in page and "Email after approval (one message)" in page
    tiers = [row["tier"] for row in service.board()["needs_uw"]]
    assert tiers == sorted(tiers)
    card = service.store.open_card_for("LEAD-00000042-000")
    assert client.post(f"/cards/{card['id']}", data={"choice": "decline"}, follow_redirects=False).status_code == 303
    assert service.store.get_case("LEAD-00000042-000")["state"] == "DECLINED"
    assert "needed to continue your submission" in client.get("/cases/LEAD-00000042-009").text
