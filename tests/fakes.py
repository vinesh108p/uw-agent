"""Test doubles: scripted model, in-memory mailbox/leadgen, and a ToolContext builder."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from uwagent.assessment import build_assessment
from uwagent.config import Settings
from uwagent.models import Lead
from uwagent.policy import load_policy
from uwagent.store import Store
from uwagent.tools import Sender, ToolContext


def tool_use(name: str, args: Any, id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=args, id=id)


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def response(*blocks: SimpleNamespace, stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class ScriptedLLM:
    def __init__(self, responses: list[Any] = (), parsed: list[Any] = ()):
        self.responses = list(responses)
        self.parsed = list(parsed)
        self.create_calls: list[dict[str, Any]] = []
        self.parse_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.create_calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)

    def parse(self, **kwargs: Any) -> Any:
        self.parse_calls.append(kwargs)
        item = self.parsed.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeMailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = False
        self._by_key: dict[str, dict[str, Any]] = {}

    def send(self, *, lead_id, to, from_, subject, body, metadata, idempotency_key) -> dict[str, Any]:
        if self.fail:
            raise httpx.ConnectError("mailbox is down")
        if idempotency_key in self._by_key:
            record = self._by_key[idempotency_key]
        else:
            record = {"id": len(self.sent) + 1, "lead_id": lead_id, "to": to, "from": from_, "subject": subject, "body": body,
                      "metadata": metadata, "received_at": "2026-06-29T08:00:00Z"}
            self.sent.append(record)
            self._by_key[idempotency_key] = record
        return {"id": record["id"], "lead_id": lead_id, "received_at": record["received_at"]}

    def emails_for_lead(self, lead_id: str) -> list[dict[str, Any]]:
        return [record for record in reversed(self.sent) if record["lead_id"] == lead_id]


class FakeLeadgen:
    def __init__(self, queues: dict[int, list[dict[str, Any]]]):
        self.queues = queues
        self.current: list[dict[str, Any]] = []

    def create_queue(self, seed: int | None = None, count: int = 10, difficulty: str = "mixed") -> dict[str, Any]:
        self.current = self.queues[seed]
        return {"seed": seed, "count": len(self.current), "difficulty": difficulty,
                "lead_ids": [item["lead"]["lead_id"] for item in self.current]}

    def get_lead(self, lead_id: str) -> Lead:
        return Lead.model_validate(next(item["lead"] for item in self.current if item["lead"]["lead_id"] == lead_id))

    def get_debug(self, lead_id: str) -> dict[str, Any]:
        return next(item["debug"] for item in self.current if item["lead"]["lead_id"] == lead_id)


def make_context(lead, registry, tmp_path, *, llm=None, decision=None, extra_facts=(), mailbox=None, settings=None):
    settings = settings or Settings(db_path=tmp_path / "ctx.db")
    store = Store(settings.db_path)
    store.upsert_lead(lead)
    for fact in extra_facts:
        store.add_fact(lead.lead_id, fact)
    case = store.get_case(lead.lead_id)
    assessment = build_assessment(lead, registry, extra_facts=list(extra_facts), decision=decision, round_=case["rounds_sent"])
    mailbox = mailbox or FakeMailbox()
    ctx = ToolContext(lead=lead, assessment=assessment, case=case, store=store, registry=registry,
                      policy=load_policy(settings.policy_path), settings=settings,
                      sender=Sender(store, mailbox, settings.from_address), llm=llm, run_id="test-run",
                      other_lead_ids=[lead.lead_id])
    return ctx, mailbox
