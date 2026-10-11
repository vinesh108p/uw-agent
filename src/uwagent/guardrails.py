"""Deterministic guardrails: content checks for every outbound message, preconditions for follow-ups."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .assessment import Assessment
from .config import Settings
from .policy import BANNED_TERMS, FOLLOWUP_BANNED
from .registry import Registry

MessageKind = Literal["followup", "quote", "decline"]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def _term_present(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def check_content(kind: MessageKind, subject: str, body: str, *, lead_id: str, street: str | None,
                  registry: Registry, other_lead_ids: Iterable[str] = ()) -> Verdict:
    reasons: list[str] = []
    text = f"{subject}\n{body}"
    lower = text.lower()
    if lead_id not in text:
        reasons.append("missing lead reference")
    if street and street.lower() not in lower:
        reasons.append("missing property address")
    if not 80 <= len(body) <= 4000:
        reasons.append(f"body length {len(body)} is outside 80-4000 characters")
    banned = BANNED_TERMS + (FOLLOWUP_BANNED if kind == "followup" else ())
    reasons += [f"banned term: {term}" for term in banned if _term_present(term, lower)]
    reasons += [f"internal field key: {name}" for name in registry.names() if "_" in name and name in text]
    if re.search(r"https?://|www\.", lower):
        reasons.append("links are not allowed")
    reasons += [f"mentions another lead: {other}" for other in other_lead_ids if other != lead_id and other in text]
    if not re.search(r"(?m)^Stand Underwriting\s*$", body):
        reasons.append("missing signature")
    return Verdict(not reasons, reasons)


def check_followup(args: dict[str, Any], assessment: Assessment, case: dict[str, Any], settings: Settings) -> Verdict:
    reasons: list[str] = []
    if "send_followup" not in assessment.allowed_actions:
        reasons.append(f"send_followup is not an allowed action (allowed: {', '.join(assessment.allowed_actions)})")
    if case["state"] in ("FOLLOW_UP_SENT", "QUOTED", "DECLINED"):
        reasons.append(f"case is {case['state']}; no new follow-up this round")
    if case["rounds_sent"] >= settings.max_rounds:
        reasons.append("maximum follow-up rounds reached; request an underwriter decision")
    items = args.get("items") or []
    keys = [item.get("key") for item in items]
    if len(keys) != len(set(keys)):
        reasons.append("duplicate items")
    extra = sorted(set(keys) - assessment.allowed_ask_keys)
    if extra:
        reasons.append(f"items not allowed (system-owned, deferred, already provided, or not required): {extra}")
    missing = sorted(assessment.required_ask_keys - set(keys))
    if missing:
        reasons.append(f"required items missing: {missing}")
    if args.get("format") != assessment.followup_format:
        reasons.append(f"format must be {assessment.followup_format}")
    reasons += [f"empty question for {item.get('key')}" for item in items if not str(item.get("question", "")).strip()]
    return Verdict(not reasons, reasons)
