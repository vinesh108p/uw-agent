"""Outbound rendering. Code owns structure (subject, numbering, options, signature); the agent supplies wording.

Templates here are the deterministic fallback when the model is unavailable, and the no-LLM eval baseline.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .assessment import AskItem, Assessment

SIGNATURE = "Stand Underwriting\nunderwriting@stand.example"
DEFAULT_DECLINE_REASON = "the property is outside our current underwriting guidelines"
PUBLIC_DECLINE_REASONS = {
    "post_pier": "the foundation and deck construction are outside our current guidelines",
    "fire_simulation": "the property's wildfire exposure is outside our current guidelines",
    "occupancy": "the property's occupancy is outside our current guidelines",
    "electrical": "the electrical system is outside our current guidelines",
    "plumbing": "the plumbing and water heater profile is outside our current guidelines",
    "protection_class": "fire protection and access for the property are outside our current guidelines",
    "roof": "the roof construction is outside our current guidelines",
}


def address(values: Mapping[str, Any]) -> str:
    parts = [values.get("street_address"), values.get("city"), values.get("state")]
    return ", ".join(str(part) for part in parts if part) or "your submission"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def render_followup(lead_id: str, values: Mapping[str, Any], *, intro: str, questions: list[tuple[AskItem, str]],
                    closing: str, fmt: str, terms: Sequence[str] = ()) -> tuple[str, str]:
    subject = f"[{lead_id}] {address(values)}: {_plural(len(questions), 'item')} needed to finalize your quote"
    lines = [intro.strip(), ""]
    if fmt == "incomplete_submission":
        lines.append("To complete underwriting, please complete or confirm these parts of the application:")
        sections: dict[str, list[str]] = {}
        for item, question in questions:
            sections.setdefault(item.section, []).append(question.strip().rstrip("?"))
        lines += [f"- {section}: {'; '.join(asks)}" for section, asks in sections.items()]
    else:
        for number, (item, question) in enumerate(questions, start=1):
            lines.append(f"{number}. {question.strip()}")
            if item.kind == "missing" and item.options:
                lines.append(f"   Options: {', '.join(item.options)}")
    if terms:
        lines += ["", "Terms to expect on the quote:"] + [f"- {term}" for term in terms]
    lines += ["", "You can reply directly to this email; a numbered list of answers is perfect.", "", closing.strip(), "", SIGNATURE]
    return subject, "\n".join(lines)


def render_quote(lead_id: str, values: Mapping[str, Any], *, cover_note: str, conditions: list[str],
                 subjectivities: list[str]) -> tuple[str, str]:
    subject = f"[{lead_id}] {address(values)}: quote ready"
    lines = [cover_note.strip(), "", "Conditions:"]
    lines += [f"- {c}" for c in conditions] or ["- None"]
    lines += ["", "Subjectivities:"]
    lines += [f"- {s}" for s in subjectivities] or ["- None"]
    lines += ["", SIGNATURE]
    return subject, "\n".join(lines)


def render_decline(lead_id: str, values: Mapping[str, Any], *, message: str) -> tuple[str, str]:
    return f"[{lead_id}] {address(values)}: underwriting decision", f"{message.strip()}\n\n{SIGNATURE}"


def template_question(item: AskItem) -> str:
    if item.key == "uw_question":
        return item.note
    question = item.label if item.label.endswith("?") else f"{item.label}?"
    if item.kind == "confirm":
        return f"Please confirm or correct: {item.note} ({item.label.rstrip('?')})"
    if item.kind == "conditional":
        return f"{item.note}: {question}"
    return question


def template_followup_args(a: Assessment) -> dict[str, Any]:
    return {
        "intro": "Thank you for sending this submission. To finalize the quote we need a few more details.",
        "items": [{"key": item.key, "question": template_question(item)} for item in a.required_asks],
        "closing": "Once we have these, we will finalize the quote promptly.",
        "format": a.followup_format,
    }


def template_quote_args(a: Assessment) -> dict[str, Any]:
    return {"cover_note": "Thank you for the complete information. We are ready to quote this property on the terms below."}


def template_decline_message(a: Assessment) -> str:
    reasons = sorted({PUBLIC_DECLINE_REASONS.get(o.tree, DEFAULT_DECLINE_REASON) for o in a.knockouts}) or [DEFAULT_DECLINE_REASON]
    return ("Thank you for the opportunity to review this submission. After careful review, we are unable to offer coverage "
            f"at this time because {'; and '.join(reasons)}. We appreciate you thinking of Stand and welcome future submissions.")


def template_uw_args(a: Assessment) -> dict[str, Any]:
    lines = [o.detail for o in a.knockouts] + [f"{u.title}: {u.detail}" for u in a.uw_items]
    if a.conditions:
        lines.append(f"{len(a.conditions)} playbook condition(s) need approval.")
    if a.required_asks:
        lines.append(f"After your review, one email will ask the broker for {len(a.required_asks)} item(s) and list the terms.")
    recommendation = a.recommendation or "approve"
    wants_notice = recommendation == "decline" or "decline" in a.allowed_recommendations
    return {
        "summary": " ".join(lines)[:800] or "Underwriter review requested.",
        "recommendation": recommendation,
        "rationale": "Recommendation from the underwriting playbook.",
        "decline_message": template_decline_message(a) if wants_notice else "",
    }
