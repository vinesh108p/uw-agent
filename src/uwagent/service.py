"""Orchestration: every event (ingest, UW click, reply) leads to one agent run for that lead."""

from __future__ import annotations

import threading
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .agent import RunResult, run_agent
from .assessment import UW_CHOICES, Assessment, build_assessment
from .config import Settings
from .llm import LLM
from .policy import Policy
from .replies import parse_reply, validate_extraction
from .simulator import persona_for, simulate_reply
from .registry import Registry
from .render import address, template_decline_message
from .store import Store
from .tools import Sender, ToolContext, escalate_to_uw, handle_tool

ACTIONABLE = ("NEW", "ASSESSED")
STATE_NOTES = {
    "NEW": "Not processed yet",
    "ASSESSED": "Re-assessing",
    "FOLLOW_UP_SENT": "Waiting on broker reply",
    "AWAITING_UW": "Needs an underwriter decision",
    "QUOTED": "Quote sent",
    "DECLINED": "Decline notice sent",
}


class Service:
    def __init__(self, *, settings: Settings, store: Store, registry: Registry, policy: Policy, leadgen: Any, mailbox: Any,
                 llm: LLM | None):
        self.settings = settings
        self.store = store
        self.registry = registry
        self.policy = policy
        self.leadgen = leadgen
        self.mailbox = mailbox
        self.llm = llm
        self.sender = Sender(store, mailbox, settings.from_address)
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    def _lock(self, lead_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks[lead_id]

    def ingest_queue(self, seed: int | None = None, count: int = 10, difficulty: str = "mixed") -> list[str]:
        queue = self.leadgen.create_queue(seed=seed, count=count, difficulty=difficulty)
        for lead_id in queue["lead_ids"]:
            self.store.upsert_lead(self.leadgen.get_lead(lead_id))
            self.store.add_event(lead_id, "ingested", {"seed": queue["seed"]})
        return list(queue["lead_ids"])

    def assess(self, lead_id: str) -> Assessment:
        case = self.store.get_case(lead_id)
        return build_assessment(self.store.get_lead(lead_id), self.registry, extra_facts=self.store.facts_for(lead_id),
                                decision=self.store.latest_decision(lead_id), flags=self.store.open_flags(lead_id),
                                round_=case["rounds_sent"], ask_threshold=self.settings.ask_threshold,
                                autosend_enabled=self.settings.autosend_enabled)

    def _context(self, lead_id: str, assessment: Assessment) -> ToolContext:
        return ToolContext(lead=self.store.get_lead(lead_id), assessment=assessment, case=self.store.get_case(lead_id),
                           store=self.store, registry=self.registry, policy=self.policy, settings=self.settings,
                           sender=self.sender, llm=self.llm, run_id=uuid.uuid4().hex[:12], other_lead_ids=self.store.lead_ids())

    def advance(self, lead_id: str) -> RunResult | None:
        with self._lock(lead_id):
            if self.store.get_case(lead_id)["state"] not in ACTIONABLE:
                return None
            assessment = self.assess(lead_id)
            self.store.update_case(lead_id, assessment=assessment.to_dict())
            return run_agent(self._context(lead_id, assessment))

    def priority(self, lead_id: str) -> tuple[int, str, str]:
        return self.assess(lead_id).priority

    def advance_all(self, lead_ids: list[str] | None = None) -> list[RunResult]:
        self.sender.flush()
        ids = list(lead_ids) if lead_ids is not None else self.store.lead_ids()
        ids.sort(key=self.priority)  # Tier 1 brokers first, then the nearest effective date
        with ThreadPoolExecutor(max_workers=self.settings.concurrency) as pool:
            return [result for result in pool.map(self.advance, ids) if result is not None]

    def last_followup_items(self, lead_id: str) -> list[str]:
        rows = [row for row in self.store.outbox_for(lead_id) if row["kind"] == "followup"]
        return list(rows[-1]["payload"]["items"]) if rows else []

    def receive_reply(self, lead_id: str, body: str) -> RunResult | None:
        case = self.store.get_case(lead_id)
        if case is None:
            raise KeyError(lead_id)
        if case["state"] == "DECLINED":
            raise ValueError(f"{lead_id} is declined; replies are no longer accepted")
        round_ = case["rounds_sent"]
        asked = self.last_followup_items(lead_id)
        extraction = parse_reply(self.llm, self.registry, asked, body)
        facts, flags = validate_extraction(extraction, self.registry, asked, round_=round_)
        self.store.add_message_in(lead_id, round_, body, extraction.model_dump())
        for fact in facts:
            self.store.add_fact(lead_id, fact)
        for flag in flags:
            self.store.add_flag(lead_id, round_, flag)
        open_card = self.store.open_card_for(lead_id)
        if open_card is not None:
            self.store.close_card(open_card["id"], "superseded")
        self.store.update_case(lead_id, state="ASSESSED")
        self.store.add_event(lead_id, "reply_received", {"round": round_, "facts": [f.field for f in facts], "flags": flags,
                                                         "intent": extraction.intent})
        return self.advance(lead_id)

    def simulate_replies(self) -> int:
        count = 0
        for lead_id in self.store.lead_ids():
            case = self.store.get_case(lead_id)
            if case["state"] != "FOLLOW_UP_SENT":
                continue
            persona = persona_for(lead_id, case["rounds_sent"])
            body, expected = simulate_reply(persona, self.last_followup_items(lead_id), self.registry, lead_id,
                                            self.assess(lead_id).values)
            self.store.add_event(lead_id, "simulated_reply", {"round": case["rounds_sent"], "persona": persona, "expected": expected})
            self.receive_reply(lead_id, body)
            count += 1
        return count

    def board(self) -> dict[str, Any]:
        rows = []
        for lead_id in self.store.lead_ids():
            lead = self.store.get_lead(lead_id)
            case = self.store.get_case(lead_id)
            card = self.store.open_card_for(lead_id)
            assessment = self.assess(lead_id)
            draft = ""
            if card is not None and not card["payload"].get("decline_message"):
                draft = template_decline_message(assessment)
            rows.append({"lead_id": lead_id, "address": address(lead.fields), "tier": assessment.tier,
                         "priority": assessment.priority, "state": case["state"], "rounds": case["rounds_sent"],
                         "effective_date": assessment.effective_date, "card": card,
                         "note": STATE_NOTES.get(case["state"], case["state"]), "draft_decline": draft})
        rows.sort(key=lambda row: row["priority"])  # Tier 1 brokers first, then the nearest effective date
        return {"cases": rows, "needs_uw": [row for row in rows if row["card"]], "counts": dict(Counter(row["state"] for row in rows))}

    def case_view(self, lead_id: str) -> dict[str, Any] | None:
        case = self.store.get_case(lead_id)
        if case is None:
            return None
        lead = self.store.get_lead(lead_id)
        return {"lead": lead, "address": address(lead.fields), "case": case, "assessment": case["assessment"] or {},
                "card": self.store.open_card_for(lead_id), "outbox": self.store.outbox_for(lead_id),
                "messages": self.store.messages_for(lead_id), "tool_calls": self.store.tool_calls_for(lead_id),
                "events": self.store.events_for(lead_id), "quote": self.store.get_quote(lead_id)}

    def resolve_card(self, card_id: int, choice: str, note: str = "", message: str | None = None) -> None:
        if choice not in UW_CHOICES:
            raise ValueError(f"choice must be one of {UW_CHOICES}")
        card = self.store.get_card(card_id)
        if card is None:
            raise KeyError(card_id)
        if not self.store.close_card(card_id, choice):
            raise ValueError("this card was already resolved")
        lead_id = card["lead_id"]
        self.store.add_decision(card_id, lead_id, card["round"], choice, note, tuple(card["payload"].get("scope", [])))
        if choice == "approve":
            self.store.resolve_flags(lead_id)
        self.store.update_case(lead_id, state="ASSESSED")
        self.store.add_event(lead_id, "uw_decision", {"card_id": card_id, "choice": choice, "note": note})
        if choice != "decline":
            self.advance(lead_id)
            return
        with self._lock(lead_id):
            assessment = self.assess(lead_id)
            ctx = self._context(lead_id, assessment)
            ctx.use_templates = True  # UW-authored or pre-approved text: deterministic checks only
            text = (message or "").strip() or card["payload"].get("decline_message") or template_decline_message(assessment)
            result = handle_tool("send_decline_notice", {"message": text}, ctx)
            if not result.ok:
                escalate_to_uw(ctx, result.content)
