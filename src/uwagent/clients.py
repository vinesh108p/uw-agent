"""HTTP clients for the simulation harness (leadgen :8081, mailbox :8025)."""

from __future__ import annotations

from typing import Any

import httpx

from .models import Lead


class LeadgenClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None):
        self._http = http or httpx.Client(base_url=base_url, timeout=10.0)

    def create_queue(self, seed: int | None = None, count: int = 10, difficulty: str = "mixed") -> dict[str, Any]:
        params: dict[str, Any] = {"count": count, "difficulty": difficulty}
        if seed is not None:
            params["seed"] = seed
        response = self._http.post("/queue", params=params)
        response.raise_for_status()
        return response.json()

    def get_lead(self, lead_id: str) -> Lead:
        response = self._http.get(f"/leads/{lead_id}")
        response.raise_for_status()
        return Lead.model_validate(response.json())

    def get_debug(self, lead_id: str) -> dict[str, Any]:
        """Answer key: evals only (requires leadgen DEBUG=true)."""
        response = self._http.get(f"/leads/{lead_id}/debug")
        response.raise_for_status()
        return response.json()


class MailboxClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None):
        self._http = http or httpx.Client(base_url=base_url, timeout=10.0)

    def send(self, *, lead_id: str, to: str, from_: str, subject: str, body: str, metadata: dict[str, Any],
             idempotency_key: str) -> dict[str, Any]:
        payload = {"lead_id": lead_id, "to": to, "from": from_, "subject": subject, "body": body, "metadata": metadata}
        response = self._http.post("/emails", json=payload, headers={"Idempotency-Key": idempotency_key})
        response.raise_for_status()
        return response.json()

    def emails_for_lead(self, lead_id: str) -> list[dict[str, Any]]:
        response = self._http.get(f"/leads/{lead_id}/emails")
        response.raise_for_status()
        return response.json()

    def reset(self) -> None:
        """Empty the mock mailbox (demo Start over)."""
        self._http.post("/reset").raise_for_status()
