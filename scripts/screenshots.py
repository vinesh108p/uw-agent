"""Capture the UW board for review (dev-only).

Renders pages in-process from the seed-42 fixture (fake leadgen and mailbox, no Docker needed), then screenshots them
with headless Chrome. Usage: uv run python scripts/screenshots.py [output_dir]   (default: docs/screenshots)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from tests.fakes import make_service  # noqa: E402
from tests.support import load_queue  # noqa: E402
from uwagent.registry import Registry  # noqa: E402
from uwagent.web import create_app  # noqa: E402

CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser")


def find_chrome() -> str | None:
    for candidate in CHROME:
        found = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if found:
            return found
    return None


class Camera:
    def __init__(self, chrome: str, out_dir: Path, work: Path):
        self.chrome = chrome
        self.out_dir = out_dir
        self.html = work / "html"
        self.html.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "src" / "uwagent" / "static", self.html / "static", dirs_exist_ok=True)

    def shoot(self, client: TestClient, url: str, name: str, height: int) -> None:
        page = self.html / f"{name}.html"
        page.write_text(client.get(url).text.replace('"/static/', '"static/'))
        target = self.out_dir / f"{name}.png"
        subprocess.run([self.chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size=1440,{height}",
                        f"--screenshot={target}", page.as_uri()], check=True, capture_output=True)
        print(target)


def main() -> int:
    chrome = find_chrome()
    if chrome is None:
        print("Headless Chrome not found; skipping screenshots.")
        return 0
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="uw-screens-"))
    camera = Camera(chrome, out_dir, work)
    registry = Registry.load(ROOT / "sim-harness" / "shared" / "field_registry.json")

    (work / "main").mkdir()
    service = make_service(work / "main", registry, {42: load_queue(42)})
    client = TestClient(create_app(service))
    loaded = client.post("/queue", data={"seed": "42"}, follow_redirects=False).headers["location"]
    camera.shoot(client, loaded, "queue", 2600)
    camera.shoot(client, "/cases/LEAD-00000042-002", "case_needs_decision", 1800)
    camera.shoot(client, "/cases/LEAD-00000042-009", "case_waiting_on_broker", 1500)

    decline = service.store.open_card_for("LEAD-00000042-000")
    declined = client.post(f"/cards/{decline['id']}", data={"choice": "decline", "back": "/cases/LEAD-00000042-000"},
                           follow_redirects=False).headers["location"]
    camera.shoot(client, declined, "case_declined", 1500)
    approve = service.store.open_card_for("LEAD-00000042-002")
    client.post(f"/cards/{approve['id']}", data={"choice": "approve", "back": "/"})
    replied = client.post("/simulate-replies", follow_redirects=False).headers["location"]
    camera.shoot(client, replied, "queue_after_replies", 2200)
    camera.shoot(client, "/cases/LEAD-00000042-009", "case_quoted", 1800)

    (work / "paused").mkdir()
    paused = make_service(work / "paused", registry, {42: load_queue(42)}, autosend_enabled=False)
    paused_client = TestClient(create_app(paused))
    paused_client.post("/queue", data={"seed": "42"})
    camera.shoot(paused_client, "/cases/LEAD-00000042-009", "card_ask_broker", 1500)
    return 0


if __name__ == "__main__":
    sys.exit(main())
