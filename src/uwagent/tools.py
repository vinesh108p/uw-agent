"""Agent action tools. Each checks preconditions against the assessment and content against policy before acting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

import httpx

from .assessment import UW_CHOICES, Assessment
from .config import Settings
from .guardrails import Verdict, check_content, check_followup
from .llm import LLM
from .models import Lead
from .moderation import moderate
from .policy import Policy
from .registry import Registry
from .render import render_decline, render_followup, render_quote
from .store import Store


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


SEND_FOLLOWUP = {
    "name": "send_followup",
    "description": "Send ONE follow-up email to the producer of record asking for exactly the required items. "
                   "Code renders the subject, numbering, options and signature.",
    "strict": True,
    "input_schema": _schema({
        "intro": {"type": "string", "description": "One or two sentences of context."},
        "items": {"type": "array", "items": _schema({"key": {"type": "string"}, "question": {"type": "string"}})},
        "closing": {"type": "string"},
        "format": {"type": "string", "enum": ["itemized", "incomplete_submission"]},
    }),
}
REQUEST_UW_DECISION = {
    "name": "request_uw_decision",
    "description": "Create one decision card for the underwriter with a short brief, a recommendation and (when "
                   "recommending decline) the customer-facing decline message; pass an empty string otherwise.",
    "strict": True,
    "input_schema": _schema({
        "summary": {"type": "string"},
        "recommendation": {"type": "string", "enum": list(UW_CHOICES)},
        "rationale": {"type": "string"},
        "decline_message": {"type": "string"},
    }),
}
MARK_QUOTE_READY = {
    "name": "mark_quote_ready",
    "description": "Send the quote-ready email. Write a two-sentence cover note; code appends conditions and subjectivities.",
    "strict": True,
    "input_schema": _schema({"cover_note": {"type": "string"}}),
}
SEND_DECLINE_NOTICE = {
    "name": "send_decline_notice",
    "description": "Send the decline notice after an underwriter decided to decline. Use only the public reasons.",
    "strict": True,
    "input_schema": _schema({"message": {"type": "string"}}),
}
TOOLS = [SEND_FOLLOWUP, REQUEST_UW_DECISION, MARK_QUOTE_READY, SEND_DECLINE_NOTICE]
TERMINAL_TOOLS = frozenset(tool["name"] for tool in TOOLS)


class Sender:
    """Outbox-backed delivery: enqueue (idempotent per lead/kind/round), then deliver; failures are retried by flush()."""

    def __init__(self, store: Store, mailbox: Any, from_address: str):
        self.store = store
        self.mailbox = mailbox
        self.from_address = from_address

    def send(self, lead_id: str, kind: str, round_: int, payload: dict[str, Any], revision: int = 0) -> dict[str, Any]:
        row = self.store.enqueue_outbox(lead_id, kind, round_, payload, revision)
        if row["status"] != "sent":
            self._deliver(row)
        return self.store.get_outbox(row["id"])

    def flush(self) -> int:
        return sum(1 for row in self.store.pending_outbox() if self._deliver(row))

    def _deliver(self, row: dict[str, Any]) -> bool:
        payload = row["payload"]
        metadata = {"kind": row["kind"], "round": row["round"], "items": payload.get("items", []),
                    "format": payload.get("format"), "instance": self.store.instance_id}
        try:
            result = self.mailbox.send(lead_id=row["lead_id"], to=payload["to"], from_=self.from_address,
                                       subject=payload["subject"], body=payload["body"], metadata=metadata,
                                       idempotency_key=row["idempotency_key"])
        except httpx.HTTPError as exc:
            self.store.mark_outbox_failed(row["id"], str(exc))
            return False
        self.store.mark_outbox_sent(row["id"], result["id"])
        return True


@dataclass
class ToolContext:
    lead: Lead
    assessment: Assessment
    case: dict[str, Any]
    store: Store
    registry: Registry
    policy: Policy
    settings: Settings
    sender: Sender
    llm: LLM | None
    run_id: str
    other_lead_ids: list[str]
    use_templates: bool = False


@dataclass(frozen=True)
class ToolResult:
    content: str
    ok: bool
    terminal: bool = True


def _reject(verdict: Verdict) -> ToolResult:
    return ToolResult("Rejected: " + "; ".join(verdict.reasons), ok=False)


def _require(args: dict[str, Any], spec: dict[str, type]) -> None:
    for key, kind in spec.items():
        if not isinstance(args.get(key), kind):
            raise ValueError(f"'{key}' must be a {kind.__name__}")


def _not_allowed(name: str, a: Assessment) -> ToolResult:
    return _reject(Verdict(False, [f"{name} is not an allowed action (allowed: {', '.join(a.allowed_actions)})"]))


def _check_message(kind: str, subject: str, body: str, ctx: ToolContext) -> Verdict:
    verdict = check_content(kind, subject, body, lead_id=ctx.lead.lead_id, street=ctx.assessment.values.get("street_address"),
                            registry=ctx.registry, other_lead_ids=ctx.other_lead_ids)
    if not verdict.ok or ctx.use_templates:
        return verdict
    result = moderate(ctx.llm, ctx.policy, subject, body)
    reasons = [f"moderation: {reason}" for reason in result.reasons] or ([] if result.passed else ["moderation: failed"])
    return Verdict(result.passed, reasons)


def _send_followup(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    _require(args, {"intro": str, "items": list, "closing": str, "format": str})
    for item in args["items"]:
        if not (isinstance(item, dict) and isinstance(item.get("key"), str) and isinstance(item.get("question"), str)):
            raise ValueError("each item needs a string 'key' and 'question'")
    a = ctx.assessment
    verdict = check_followup(args, a, ctx.case, ctx.settings)
    if not verdict.ok:
        return _reject(verdict)
    asks = {item.key: item for item in a.required_asks + a.optional_asks}
    questions = [(asks[item["key"]], item["question"]) for item in args["items"]]
    subject, body = render_followup(ctx.lead.lead_id, a.values, intro=args["intro"], questions=questions,
                                    closing=args["closing"], fmt=args["format"], terms=a.terms)
    verdict = _check_message("followup", subject, body, ctx)
    if not verdict.ok:
        return _reject(verdict)
    round_ = ctx.case["rounds_sent"] + 1
    keys = [item["key"] for item in args["items"]]
    ctx.sender.send(ctx.lead.lead_id, "followup", round_,
                    {"to": a.recipient, "subject": subject, "body": body, "items": keys, "format": args["format"],
                     "conditional": [item.key for item in a.required_asks if item.kind == "conditional"],
                     "policy_version": ctx.policy.version})
    ctx.store.update_case(ctx.lead.lead_id, state="FOLLOW_UP_SENT", rounds_sent=round_)
    ctx.store.add_event(ctx.lead.lead_id, "followup_sent", {"round": round_, "items": keys})
    return ToolResult(f"Follow-up sent to {a.recipient} with {len(keys)} item(s).", ok=True)


def _request_uw_decision(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    _require(args, {"summary": str, "recommendation": str, "rationale": str, "decline_message": str})
    a = ctx.assessment
    if "request_uw_decision" not in a.allowed_actions:
        return _not_allowed("request_uw_decision", a)
    reasons = []
    if args["recommendation"] not in a.allowed_recommendations:
        reasons.append(f"recommendation must be one of {a.allowed_recommendations}")
    if not args["summary"].strip():
        reasons.append("summary is required")
    message = args["decline_message"].strip()
    if args["recommendation"] == "decline" and not message:
        reasons.append("decline_message is required when recommending decline")
    if reasons:
        return _reject(Verdict(False, reasons))
    if message:
        subject, body = render_decline(ctx.lead.lead_id, a.values, message=message)
        verdict = _check_message("decline", subject, body, ctx)
        if not verdict.ok:
            return _reject(Verdict(False, [f"decline_message: {reason}" for reason in verdict.reasons]))
    payload = {"summary": args["summary"].strip(), "recommendation": args["recommendation"], "rationale": args["rationale"].strip(),
               "decline_message": message, "uw_items": [asdict(u) for u in a.uw_items],
               "knockouts": [o.detail for o in a.knockouts], "conditions": [o.detail for o in a.conditions],
               "asks": [item.label for item in a.released_asks], "terms": a.terms, "scope": a.scope,
               "ask_items": [{"label": item.label, "section": item.section, "kind": item.kind} for item in a.released_asks],
               "written_by": "template" if ctx.use_templates else "agent",
               "allowed_choices": list(UW_CHOICES)}
    card_id = ctx.store.create_card(ctx.lead.lead_id, ctx.case["rounds_sent"], payload)
    ctx.store.update_case(ctx.lead.lead_id, state="AWAITING_UW")
    ctx.store.add_event(ctx.lead.lead_id, "uw_card_created", {"card_id": card_id, "recommendation": args["recommendation"]})
    return ToolResult(f"Decision card {card_id} created for the underwriter.", ok=True)


def _mark_quote_ready(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    _require(args, {"cover_note": str})
    a = ctx.assessment
    if "mark_quote_ready" not in a.allowed_actions:
        return _not_allowed("mark_quote_ready", a)
    conditions = [o.detail for o in a.conditions]
    subject, body = render_quote(ctx.lead.lead_id, a.values, cover_note=args["cover_note"], conditions=conditions,
                                 subjectivities=a.subjectivities)
    verdict = _check_message("quote", subject, body, ctx)
    if not verdict.ok:
        return _reject(verdict)
    ctx.store.save_quote(ctx.lead.lead_id, {"conditions": conditions, "subjectivities": a.subjectivities,
                                            "approved_by_uw": a.decision is not None and a.decision.choice == "approve"})
    revision = sum(1 for row in ctx.store.outbox_for(ctx.lead.lead_id) if row["kind"] == "quote")  # a re-quote is a new message
    ctx.sender.send(ctx.lead.lead_id, "quote", ctx.case["rounds_sent"],
                    {"to": a.recipient, "subject": subject, "body": body, "policy_version": ctx.policy.version}, revision)
    ctx.store.update_case(ctx.lead.lead_id, state="QUOTED")
    ctx.store.add_event(ctx.lead.lead_id, "quoted", {"conditions": conditions})
    return ToolResult("Quote sent.", ok=True)


def _send_decline_notice(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    _require(args, {"message": str})
    a = ctx.assessment
    if "send_decline_notice" not in a.allowed_actions:
        return _reject(Verdict(False, ["send_decline_notice requires an underwriter decline decision"]))
    subject, body = render_decline(ctx.lead.lead_id, a.values, message=args["message"])
    verdict = _check_message("decline", subject, body, ctx)
    if not verdict.ok:
        return _reject(verdict)
    ctx.sender.send(ctx.lead.lead_id, "decline", ctx.case["rounds_sent"],
                    {"to": a.recipient, "subject": subject, "body": body, "policy_version": ctx.policy.version})
    ctx.store.update_case(ctx.lead.lead_id, state="DECLINED")
    ctx.store.add_event(ctx.lead.lead_id, "declined", {})
    return ToolResult("Decline notice sent.", ok=True)


HANDLERS: dict[str, Callable[[dict[str, Any], ToolContext], ToolResult]] = {
    "send_followup": _send_followup,
    "request_uw_decision": _request_uw_decision,
    "mark_quote_ready": _mark_quote_ready,
    "send_decline_notice": _send_decline_notice,
}


def handle_tool(name: str, args: Any, ctx: ToolContext) -> ToolResult:
    """Run a tool; never raises on bad arguments (the agent gets a readable rejection instead). Every call is logged."""
    handler = HANDLERS.get(name)
    if handler is None:
        result = ToolResult(f"Rejected: unknown tool {name!r}", ok=False)
    elif not isinstance(args, dict):
        result = ToolResult("Rejected: arguments must be a JSON object", ok=False)
    else:
        try:
            result = handler(args, ctx)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            result = ToolResult(f"Rejected: malformed arguments for {name}: {exc}", ok=False)
    logged_args = args if isinstance(args, dict) else {"raw": repr(args)}
    ctx.store.log_tool_call(ctx.lead.lead_id, ctx.run_id, name, logged_args, result.ok, [] if result.ok else [result.content])
    return result


def escalate_to_uw(ctx: ToolContext, why: str) -> int:
    """Last resort when no automatic action passes the guardrails: hand the lead to the underwriter."""
    a = ctx.assessment
    payload = {"summary": f"Automatic action could not pass the guardrails: {why}", "recommendation": None,
               "rationale": "Escalated by the runner.", "decline_message": "", "uw_items": [asdict(u) for u in a.uw_items],
               "knockouts": [o.detail for o in a.knockouts], "conditions": [o.detail for o in a.conditions],
               "asks": [item.label for item in a.released_asks], "terms": a.terms, "scope": a.scope,
               "ask_items": [{"label": item.label, "section": item.section, "kind": item.kind} for item in a.released_asks],
               "written_by": "system",
               "allowed_choices": list(UW_CHOICES)}
    card_id = ctx.store.create_card(ctx.lead.lead_id, ctx.case["rounds_sent"], payload)
    ctx.store.update_case(ctx.lead.lead_id, state="AWAITING_UW")
    ctx.store.add_event(ctx.lead.lead_id, "escalated", {"why": why})
    return card_id
