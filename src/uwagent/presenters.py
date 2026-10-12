"""Underwriter-facing wording and formatting for the UW board.

Pure functions and lookup tables only (no store, no I/O), so every label an underwriter reads lives in one place.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from .registry import Registry

STATUS: dict[str, tuple[str, str]] = {
    "NEW": ("Queued", "grey"),
    "ASSESSED": ("Working", "grey"),
    "AWAITING_UW": ("Needs your decision", "amber"),
    "FOLLOW_UP_SENT": ("Waiting on broker", "blue"),
    "QUOTED": ("Quote sent", "green"),
    "DECLINED": ("Declined", "slate"),
}
RECOMMENDATIONS: dict[str | None, tuple[str, str]] = {
    "decline": ("Recommended: Decline", "red"),
    "approve": ("Recommended: Approve", "navy"),
    "ask_broker": ("Recommended: Ask broker", "amber"),
    None: ("Needs review", "amber"),
}
CHANNELS = {"agent_portal": "Agent portal", "broker_email": "Broker email", "direct_web": "Direct web"}
PROVIDERS = {
    "crm": "Account records",
    "kyc_vendor": "KYC screening",
    "usgs_dem": "Terrain data",
    "building_footprints": "Building footprints",
    "aerial_imagery": "Aerial imagery",
    "road_graph": "Road network",
    "iso_ppc": "ISO protection class",
    "rce_estimator": "Replacement cost estimator",
    "fire_simulation": "Fire simulation",
}
PAGE_NAMES = {
    "occupancy": "Occupancy",
    "profile": "Profile (KYC)",
    "fire_simulation": "Fire simulation",
    "protection_class": "Protection class 9 & 10",
    "roof": "Roof class",
    "siding": "Siding",
    "post_pier": "Post & pier",
    "plumbing": "Plumbing",
    "electrical": "Electrical",
    "pools": "Swimming pools",
    "trusts": "Trusts & LLCs",
    "replacement_cost": "Replacement cost",
}
DECLINE_SHORT = {
    "fire_simulation": "wildfire exposure",
    "post_pier": "foundation & deck",
    "occupancy": "occupancy",
    "electrical": "electrical system",
    "plumbing": "plumbing & water heater",
    "protection_class": "fire protection & access",
    "roof": "roof",
}
SECTION_NAMES = {"Primary Coverages": "Coverage"}
MONEY_FIELDS = frozenset({"coverage_a", "replacement_cost"})
UNITS = {
    "square_feet": "sq ft",
    "dist_to_nearest_fire_hydrant": "ft",
    "min_distance_to_neighbor_ft": "ft",
    "distance_to_fire_department": "mi",
    "acreage": "acres",
    "slope_angle_deg": "°",
}
KEY_FACTS = (
    ("coverage_a", "Coverage A (Dwelling)"),
    ("replacement_cost", "Replacement cost"),
    ("year_built", "Year built"),
    ("square_feet", "Living area"),
    ("construction_type", "Construction type"),
    ("roof_material", "Roof"),
    ("foundation_type", "Foundation"),
    ("protection_class", "Protection class"),
    ("p_f", "Wildfire failure probability"),
    ("dwelling_use_type", "Occupancy type"),
    ("kyc_score", "Profile score (KYC)"),
)
TOOL_NAMES = {
    "send_followup": "Send follow-up",
    "request_uw_decision": "Ask the underwriter",
    "mark_quote_ready": "Send quote",
    "send_decline_notice": "Send decline notice",
}
EVENT_NAMES = {
    "ingested": "Lead received",
    "followup_sent": "Follow-up sent",
    "uw_card_created": "Decision requested",
    "uw_decision": "Underwriter decision",
    "reply_received": "Broker reply received",
    "simulated_reply": "Simulated broker reply",
    "quoted": "Quote sent",
    "declined": "Decline notice sent",
    "escalated": "Escalated to the underwriter",
}
ERRORS = {
    "already_decided": "This decision was already made; no second email was sent.",
    "needs_question": "Add a question for the broker; there's nothing else to ask.",
    "bad_seed": "The seed must be a whole number.",
    "bad_choice": "That isn't a valid decision.",
    "declined": "This lead is declined; replies are no longer accepted.",
    "unknown": "That lead or card no longer exists.",
}
FAILED_DELIVERY = "Email queued. The mailbox didn't respond, so it will be retried on your next action."


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def status_label(state: str) -> str:
    return STATUS.get(state, (state.replace("_", " ").title(), "grey"))[0]


def status_tone(state: str) -> str:
    return STATUS.get(state, ("", "grey"))[1]


def recommendation_badge(recommendation: str | None) -> tuple[str, str]:
    return RECOMMENDATIONS.get(recommendation, RECOMMENDATIONS[None])


def tier_label(tier: int | None) -> str:
    return f"Tier {tier}" if tier and tier < 9 else "Tier ?"


def model_name(model_id: str) -> str:
    """'claude-opus-5-5' -> 'Claude Opus 5.5'; anything else is shown as given."""
    parts = model_id.split("-")
    if len(parts) < 3 or parts[0] != "claude":
        return model_id
    return f"Claude {parts[1].title()} {'.'.join(parts[2:])}"


def insured_name(values: Mapping[str, Any]) -> str:
    name = " ".join(str(values[key]).strip() for key in ("first_name", "last_name") if values.get(key))
    return name or "Insured name not provided"


def property_line(values: Mapping[str, Any]) -> str:
    street = values.get("street_address")
    if not street:
        return "Address not provided"
    place = " ".join(str(values[key]) for key in ("city", "state") if values.get(key))
    return f"{street}, {place}" if place else str(street)


def _as_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def fmt_date(value: str | date, *, year: bool = False) -> str:
    day = _as_date(value)
    return f"{day:%b} {day.day}, {day.year}" if year else f"{day:%b} {day.day}"


def days_label(value: str | date | None, morning: date) -> tuple[str, bool]:
    """'Jul 8 · 9 days' (upcoming) or 'Jun 26 · 3 days ago' (overdue), counted from the queue morning."""
    if not value:
        return "Not provided", False
    day = _as_date(value)
    delta = (day - morning).days
    if delta == 0:
        return f"{fmt_date(day)} · today", False
    if delta > 0:
        return f"{fmt_date(day)} · {plural(delta, 'day')}", False
    return f"{fmt_date(day)} · {plural(-delta, 'day')} ago", True


def fmt_money(value: Any) -> str:
    return f"${int(round(float(value))):,}"


def fmt_value(field: str, value: Any, registry: Registry | None = None) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field in MONEY_FIELDS:
        return fmt_money(value)
    if field == "p_f":
        return f"{float(value):.2f} (fails above 0.50)"
    if field in UNITS:
        number = f"{value:,}" if isinstance(value, int) else f"{value:g}"
        return f"{number}°" if UNITS[field] == "°" else f"{number} {UNITS[field]}"
    if registry is not None and field in registry and registry[field].kind == "date":
        try:
            return fmt_date(value, year=True)
        except ValueError:
            return str(value)
    return str(value)


def fmt_when(iso: str, now: datetime | None = None) -> str:
    """When an action happened, in the machine's local time: 'today at 14:42' or 'Oct 7 at 14:42'."""
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    now = (now or datetime.now(timezone.utc)).astimezone()
    clock = f"{moment:%H:%M}"
    return f"today at {clock}" if moment.date() == now.date() else f"{fmt_date(moment.date())} at {clock}"


def source_label(entry: Mapping[str, Any], registry: Registry | None = None) -> str:
    source, detail = entry.get("source"), entry.get("detail") or ""
    if source == "submission":
        return "From application"
    if source == "reply":
        match = re.search(r"r(\d+)$", detail)
        return f"Broker reply (round {match.group(1)})" if match else "Broker reply"
    if source == "uw":
        return "Underwriter"
    if source == "enrichment":
        return f"Looked up: {PROVIDERS.get(detail, detail or 'data source')}"
    if source == "derived":
        label = registry[detail].label if registry is not None and detail in registry else detail
        return f"Derived from {label}"
    if source == "default":
        return "Playbook default"
    return str(source)


def reason_text(detail: str) -> str:
    return detail.replace("P(F)", "wildfire failure probability")


def page_name(tree: str) -> str:
    return PAGE_NAMES.get(tree, tree.replace("_", " ").capitalize())


def tree_badge(tree: Mapping[str, Any]) -> tuple[str, str]:
    kinds = {outcome["kind"] for outcome in tree.get("outcomes", [])}
    if tree.get("certain_decline"):
        return "Decline", "red"
    if "judgment" in kinds:
        return "Needs your judgment", "amber"
    if "condition" in kinds:
        return "Condition", "amber"
    if "advisory" in kinds:
        return "Note", "blue"
    if tree.get("possible_decline") or tree.get("unknowns"):
        return "Waiting on info", "grey"
    return "Pass", "green"


def tree_reason(tree: Mapping[str, Any], registry: Registry | None = None) -> str:
    if tree.get("certain_decline"):
        return reason_text("; ".join(tree.get("decline_reasons", [])))
    outcomes = tree.get("outcomes", [])
    for kind in ("judgment", "condition", "advisory"):
        for outcome in outcomes:
            if outcome["kind"] == kind:
                return reason_text(outcome["detail"])
    if tree.get("possible_decline") or tree.get("unknowns"):
        labels = [registry[name].label if registry is not None and name in registry else name
                  for name in tree.get("unknowns", [])]
        return "Waiting on: " + ", ".join(labels) if labels else "Waiting on more information"
    return reason_text(outcomes[0]["detail"]) if outcomes else "Pass"


def whats_next(state: str, *, card_payload: Mapping[str, Any] | None = None, followup_items: Iterable[str] | None = None,
               followup_round: int = 0, quote: Mapping[str, Any] | None = None, knockout_trees: Iterable[str] = ()) -> str:
    if state == "AWAITING_UW":
        payload = card_payload or {}
        recommendation = payload.get("recommendation")
        if recommendation == "decline":
            return "Recommended: decline"
        if recommendation == "approve":
            count = len(payload.get("conditions") or [])
            return f"Recommended: approve {plural(count, 'condition')}" if count else "Recommended: approve"
        if recommendation == "ask_broker":
            return "Recommended: ask the broker"
        return "Needs review"
    if state == "FOLLOW_UP_SENT":
        return f"Asked broker for {plural(len(list(followup_items or [])), 'item')} (round {followup_round})"
    if state == "QUOTED":
        count = len((quote or {}).get("conditions") or [])
        return f"Quote sent with {plural(count, 'condition')}" if count else "Quote sent, no conditions"
    if state == "DECLINED":
        for tree in knockout_trees:
            if tree in DECLINE_SHORT:
                return f"Declined: {DECLINE_SHORT[tree]}"
        return "Declined by underwriter"
    if state == "NEW":
        return "Queued for processing"
    return "Re-checking after the latest update"


def email_preview(ask_items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for item in ask_items:
        section = SECTION_NAMES.get(item.get("section") or "", item.get("section") or "Other")
        groups.setdefault(section, []).append(item["label"])
    return {
        "count": sum(len(labels) for labels in groups.values()),
        "summary": " · ".join(f"{section} {len(labels)}" for section, labels in groups.items()),
        "groups": [{"section": section, "labels": labels} for section, labels in groups.items()],
    }


def key_facts(facts: Mapping[str, Mapping[str, Any]], registry: Registry | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for field, label in KEY_FACTS:
        entry = facts.get(field)
        if not entry or entry.get("value") is None:
            continue
        value = fmt_value(field, entry["value"], registry)
        if field == "roof_material" and facts.get("roof_classification"):
            value = f"{value} · {facts['roof_classification']['value']}"
        rows.append({"label": label, "value": value, "source": source_label(entry, registry)})
    return rows


def banner_text(notice: str, *, state: str | None = None, choice: str | None = None, recipient: str = "",
                items: int = 0, street: str = "", reason: str = "", failed: bool = False, n: int = 0, m: int = 0,
                updated: int = 0, quoted: int = 0) -> str | None:
    if failed:
        return FAILED_DELIVERY
    if notice == "queue_loaded":
        return f"Queue loaded: {plural(n, 'lead')}, {m} need your decision."
    if notice == "replies_simulated":
        return f"Broker replies simulated: {plural(updated, 'lead')} updated, {quoted} now quoted."
    if notice == "reset":
        return "Started over. Load a new queue from the Demo menu."
    if notice != "decided":
        return None
    if state == "FOLLOW_UP_SENT":
        if choice == "ask_broker":
            return f"Question sent to the broker, with {plural(items, 'item')}." if items else "Question sent to the broker."
        return f"Approved. One email asking for {plural(items, 'item')} went to {recipient}."
    if state == "QUOTED":
        return f"Approved. Quote sent to {recipient}."
    if state == "DECLINED":
        return f"Decline notice sent to {recipient} for {street}." if street else f"Decline notice sent to {recipient}."
    if state == "AWAITING_UW":
        return f"Decision recorded. The lead needs another look: {reason}." if reason else "Decision recorded. The lead needs another look."
    return "Decision recorded."


def error_text(key: str) -> str:
    return ERRORS.get(key, ERRORS["unknown"])


def tool_label(name: str) -> str:
    return TOOL_NAMES.get(name, name.replace("_", " ").capitalize())


def event_label(kind: str) -> str:
    return EVENT_NAMES.get(kind, kind.replace("_", " ").capitalize())
