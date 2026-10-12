"""UW board web app: underwriter-facing pages, decision forms and demo controls."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import views
from .assessment import UW_CHOICES
from .service import NeedsNote, Service

HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _redirect(path: str, **params: Any) -> RedirectResponse:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return RedirectResponse(f"{path}?{query}" if query else path, status_code=303)


def _fail(request: Request, key: str, status: int, detail: str, back: str = "/", **params: Any) -> RedirectResponse:
    """Browser form posts get a friendly banner on the page they came from; other clients keep the status code."""
    if _wants_html(request):
        return _redirect(back, error=key, **params)
    raise HTTPException(status, detail)


def _safe_back(path: str) -> str:
    """Only redirect to local pages, so the hidden 'back' field cannot become an open redirect."""
    return path if path.startswith("/") and not path.startswith("//") and "\\" not in path else "/"


def _count(service: Service, state: str) -> int:
    return sum(1 for lead_id in service.store.lead_ids() if service.store.get_case(lead_id)["state"] == state)


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
        page = views.case_page(service, lead_id, request.query_params)
        if page is None:
            raise HTTPException(404, f"unknown lead {lead_id}")
        return TEMPLATES.TemplateResponse(request, "case.html", page)

    @app.post("/queue")
    def run_queue(request: Request, seed: str = Form("")) -> RedirectResponse:
        try:
            parsed = int(seed) if seed.strip() else None
        except ValueError:
            return _fail(request, "bad_seed", 400, "seed must be an integer")
        lead_ids = service.ingest_queue(seed=parsed)
        service.advance_all()
        return _redirect("/", notice="queue_loaded", n=len(lead_ids), m=len(service.store.list_open_cards()))

    @app.post("/cards/{card_id}")
    def decide(request: Request, card_id: int, choice: str = Form(...), note: str = Form(""), message: str = Form(""),
               back: str = Form("/")) -> RedirectResponse:
        back = _safe_back(back)
        if choice not in UW_CHOICES:
            return _fail(request, "bad_choice", 400, f"choice must be one of {UW_CHOICES}", back)
        card = service.store.get_card(card_id)
        try:
            service.resolve_card(card_id, choice, note=note, message=message or None)
        except NeedsNote as exc:
            return _fail(request, "needs_question", 400, str(exc), back, card=card_id)
        except KeyError:
            return _fail(request, "unknown", 404, "unknown card", back)
        except ValueError as exc:
            return _fail(request, "already_decided", 409, str(exc), back)
        return _redirect(back, notice="decided", lead=card["lead_id"], choice=choice)

    @app.post("/cases/{lead_id}/reply")
    def reply(request: Request, lead_id: str, body: str = Form(...)) -> RedirectResponse:
        back = f"/cases/{lead_id}"
        try:
            service.receive_reply(lead_id, body)
        except KeyError:
            return _fail(request, "unknown", 404, f"unknown lead {lead_id}")
        except ValueError as exc:
            return _fail(request, "declined", 409, str(exc), back)
        return RedirectResponse(back, status_code=303)

    @app.post("/simulate-replies")
    def simulate() -> RedirectResponse:
        before = _count(service, "QUOTED")
        updated = service.simulate_replies()
        return _redirect("/", notice="replies_simulated", updated=updated, quoted=_count(service, "QUOTED") - before)

    @app.post("/demo/reset")
    def start_over() -> RedirectResponse:
        service.reset()
        return _redirect("/", notice="reset")

    return app
