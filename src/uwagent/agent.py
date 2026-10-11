"""Per-lead agent loop: Claude picks exactly one guarded action tool; deterministic templates are the fallback."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .assessment import AskItem, Assessment
from .render import (
    DEFAULT_DECLINE_REASON, PUBLIC_DECLINE_REASONS, address, template_decline_message, template_followup_args,
    template_quote_args, template_uw_args,
)
from .tools import TOOLS, ToolContext, escalate_to_uw, handle_tool

PROMPT_VERSION = "agent-v1"

SYSTEM_PROMPT = """You are the underwriting assistant for Stand, a property insurer that works with homeowners to make their properties safer.
You handle ONE lead per run. The lead has already been investigated: data lookups, derivations, conflict checks, the underwriting
playbook and (when needed) the underwriter's review. The assessment in the user message is the result. Trust it: it decides what is
missing, what the playbook requires, and which actions are allowed.

Finish the run by calling exactly ONE action tool from "allowed_actions":
- send_followup: this is the ONLY email the broker gets for this round, so it must carry everything. Ask for exactly the
  "required_items" (you may add "optional_items"). Write a short, warm, professional intro (one or two sentences, mention the
  property), one clear plain-language question per item, and a short closing. For "confirm" items, say what we have on file and ask
  them to confirm or correct it. For "conditional" items, keep the "Only if ..." condition in the question. If an underwriter question
  is present, include it. Code appends the terms to expect on the quote. Use the "followup_format" given.
- request_uw_decision: brief the underwriter in two to four sentences (what is going on and why), recommend one of
  "allowed_recommendations" (prefer "engine_recommendation" unless the facts clearly support another allowed option), give a
  one-sentence rationale, and when recommending decline write a courteous decline_message for the broker using only
  "public_decline_reasons"; otherwise pass an empty string.
- mark_quote_ready: write a two-sentence cover note; code appends the conditions and subjectivities.
- send_decline_notice: write a courteous decline message using only "public_decline_reasons", thank the broker, invite future submissions.

Never mention internal scores or screening (KYC, fraud, fire-simulation probabilities, broker tiers, account status) or field keys.
Never promise coverage, price or approval. If a tool rejects your call, read the reasons, fix the problem and call again.
Do not answer in plain text."""

TEMPLATES: dict[str, Callable[[Assessment], dict[str, Any]]] = {
    "send_followup": template_followup_args,
    "request_uw_decision": template_uw_args,
    "mark_quote_ready": template_quote_args,
    "send_decline_notice": lambda a: {"message": template_decline_message(a)},
}


@dataclass(frozen=True)
class RunResult:
    lead_id: str
    run_id: str
    action: str | None
    ok: bool
    rejections: int
    steps: int
    fallback: str | None = None


def _item(item: AskItem) -> dict[str, Any]:
    return {"key": item.key, "label": item.label, "kind": item.kind, "options": list(item.options) if item.options else None,
            "current_value": item.current_value, "note": item.note}


def build_case_prompt(ctx: ToolContext) -> str:
    a = ctx.assessment
    data = {
        "lead_id": ctx.lead.lead_id,
        "source": ctx.lead.source,
        "received_at": ctx.lead.received_at,
        "property": address(a.values),
        "round": ctx.case["rounds_sent"],
        "allowed_actions": a.allowed_actions,
        "followup_format": a.followup_format,
        "required_items": [_item(i) for i in a.required_asks],
        "optional_items": [_item(i) for i in a.optional_asks],
        "terms_to_expect": a.terms,
        "subjectivities": a.subjectivities,
        "underwriter_items": [asdict(u) for u in a.uw_items],
        "knockouts": [{"tree": o.tree, "detail": o.detail} for o in a.knockouts],
        "public_decline_reasons": sorted({PUBLIC_DECLINE_REASONS.get(o.tree, DEFAULT_DECLINE_REASON) for o in a.knockouts}),
        "engine_recommendation": a.recommendation,
        "allowed_recommendations": a.allowed_recommendations,
        "underwriter_decision": asdict(a.decision) if a.decision else None,
    }
    return "Assessment for this lead (JSON):\n" + json.dumps(data, indent=2, default=str)


def run_template(ctx: ToolContext, *, reason: str, rejections: int = 0, steps: int = 0) -> RunResult:
    ctx.use_templates = True
    action = ctx.assessment.allowed_actions[0]
    result = handle_tool(action, TEMPLATES[action](ctx.assessment), ctx)
    if result.ok:
        return RunResult(ctx.lead.lead_id, ctx.run_id, action, True, rejections, steps, fallback=reason)
    escalate_to_uw(ctx, result.content)
    return RunResult(ctx.lead.lead_id, ctx.run_id, "request_uw_decision", False, rejections, steps, fallback=f"{reason}; escalated")


def run_agent(ctx: ToolContext, *, max_steps: int = 6, max_rejections: int = 2) -> RunResult:
    if ctx.llm is None:
        return run_template(ctx, reason="offline")
    system = f"{SYSTEM_PROMPT}\n\nCOMMUNICATION POLICY (version {ctx.policy.version}):\n{ctx.policy.text}"
    messages: list[dict[str, Any]] = [{"role": "user", "content": build_case_prompt(ctx)}]
    rejections = steps = 0
    reprompted = False
    while steps < max_steps:
        steps += 1
        try:
            response = ctx.llm.create(system=system, messages=messages, tools=TOOLS)
        except Exception as exc:  # network/API failure: never block the queue on the model
            return run_template(ctx, reason=f"llm error: {type(exc).__name__}", rejections=rejections, steps=steps)
        if response.stop_reason == "refusal":
            return run_template(ctx, reason="refusal", rejections=rejections, steps=steps)
        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        if not tool_uses:
            if reprompted:
                break
            reprompted = True
            messages.append({"role": "user", "content": "Call exactly one of the allowed action tools now."})
            continue
        results: list[dict[str, Any]] = []
        finished: str | None = None
        for block in tool_uses:
            if finished is not None:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "Ignored: only one action is allowed per run.", "is_error": True})
                continue
            outcome = handle_tool(block.name, block.input, ctx)
            if outcome.ok and outcome.terminal:
                finished = block.name
            elif not outcome.ok:
                rejections += 1
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": outcome.content, "is_error": not outcome.ok})
        messages.append({"role": "user", "content": results})
        if finished is not None:
            return RunResult(ctx.lead.lead_id, ctx.run_id, finished, True, rejections, steps)
        if rejections > max_rejections:
            break
    return run_template(ctx, reason="agent did not complete", rejections=rejections, steps=steps)
