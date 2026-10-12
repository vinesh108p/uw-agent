"""UW board web app: underwriter-facing pages, decision forms and demo controls."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import views
from .assessment import UW_CHOICES
from .service import NeedsNote, Service

HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))


def create_app(service: Service) -> FastAPI:
    app = FastAPI(title="Stand UW assistant")
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def queue(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "queue.html", views.queue_page(service, request.query_params))

    @app.get("/cases/{lead_id}", response_class=HTMLResponse)
    def case(request: Request, lead_id: str) -> HTMLResponse:
        view = service.case_view(lead_id)
        if view is None:
            raise HTTPException(404, f"unknown lead {lead_id}")
        # Interim (replaced in Task 4): the old case template inside the new header.
        return TEMPLATES.TemplateResponse(request, "case.html", {**view, "chrome": views.chrome(service), "banner": None})

    @app.post("/queue")
    def run_queue(seed: str = Form("")) -> RedirectResponse:
        try:
            parsed = int(seed) if seed.strip() else None
        except ValueError:
            raise HTTPException(400, "seed must be an integer")
        service.ingest_queue(seed=parsed)
        service.advance_all()
        return RedirectResponse("/", status_code=303)

    @app.post("/cards/{card_id}")
    def decide(card_id: int, choice: str = Form(...), note: str = Form(""), message: str = Form("")) -> RedirectResponse:
        if choice not in UW_CHOICES:
            raise HTTPException(400, f"choice must be one of {UW_CHOICES}")
        try:
            service.resolve_card(card_id, choice, note=note, message=message or None)
        except NeedsNote as exc:
            raise HTTPException(400, str(exc))
        except KeyError:
            raise HTTPException(404, "unknown card")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return RedirectResponse("/", status_code=303)

    @app.post("/cases/{lead_id}/reply")
    def reply(lead_id: str, body: str = Form(...)) -> RedirectResponse:
        try:
            service.receive_reply(lead_id, body)
        except KeyError:
            raise HTTPException(404, f"unknown lead {lead_id}")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return RedirectResponse(f"/cases/{lead_id}", status_code=303)

    @app.post("/simulate-replies")
    def simulate() -> RedirectResponse:
        service.simulate_replies()
        return RedirectResponse("/", status_code=303)

    return app
