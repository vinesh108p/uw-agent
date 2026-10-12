"""Page data for the UW board: Service data plus presenters, shaped for the templates."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from . import presenters as p
from .render import template_decline_message
from .service import Service

MAILBOX_UI = "http://127.0.0.1:8025/"  # the browser-facing mock inbox (container-internal URLs are not reachable)


def _int(value: str | None) -> int:
    return int(value) if value and value.isdigit() else 0


def _assessment(service: Service, lead_id: str) -> dict[str, Any]:
    case = service.store.get_case(lead_id) or {}
    return case.get("assessment") or {}


def _values(service: Service, lead_id: str) -> dict[str, Any]:
    """Current field values: the latest assessment's facts (includes broker replies), else the original submission."""
    facts = _assessment(service, lead_id).get("facts") or {}
    if facts:
        return {name: entry["value"] for name, entry in facts.items()}
    return dict(service.store.get_lead(lead_id).fields)


def _latest(rows: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    matching = [row for row in rows if row["kind"] == kind]
    return matching[-1] if matching else None


def morning_of(service: Service) -> date | None:
    """The queue morning: the earliest received date among loaded leads (days-to-effective are counted from it)."""
    dates = [service.store.get_lead(lead_id).received_date for lead_id in service.store.lead_ids()]
    return min(dates) if dates else None


def chrome(service: Service) -> dict[str, Any]:
    """Header data shared by every page."""
    morning = morning_of(service)
    count = len(service.store.lead_ids())
    settings = service.settings
    return {
        "subtitle": f"morning of {p.fmt_date(morning)} · {p.plural(count, 'lead')}" if morning else "",
        "mode": f"Live agent · {p.model_name(settings.model)}" if settings.live_llm else "Offline templates",
        "live": settings.live_llm,
        "autosend_paused": not settings.autosend_enabled,
        "mailbox_url": MAILBOX_UI,
    }


def reasons(payload: Mapping[str, Any], assessment: Mapping[str, Any]) -> list[dict[str, str]]:
    """Why a card needs the underwriter: knockouts (tagged by playbook page), UW items, conditions; duplicates collapse."""
    trees = {entry["detail"]: entry["tree"] for entry in assessment.get("knockouts", [])}
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(tag: str, text: str) -> None:
        text = p.reason_text(text)
        if text and text not in seen:
            seen.add(text)
            out.append({"tag": tag, "text": text})

    for detail in payload.get("knockouts", []):
        add(p.page_name(trees[detail]) if detail in trees else "Playbook", detail)
    for item in payload.get("uw_items", []):
        add(item.get("title") or "Review", item.get("detail", ""))
    conditions = payload.get("conditions") or []
    if conditions:
        add("Conditions", f"{p.plural(len(conditions), 'playbook condition')} to approve")
    if not out:  # cards with no playbook reason still say why they are here
        if payload.get("written_by") == "system":
            add("Escalation", payload.get("summary") or "The automatic action could not pass the guardrails.")
        elif payload.get("recommendation") == "ask_broker":
            add("Auto-send paused", "The follow-up email waits for your release while auto-send is paused.")
    return out


def banner(service: Service, params: Mapping[str, str]) -> dict[str, str] | None:
    """Banner after an action. The text is read from the store's current state (what happened), not what was tried."""
    error = params.get("error")
    if error:
        return {"kind": "error", "text": p.error_text(error)}
    notice = params.get("notice")
    if not notice:
        return None
    context: dict[str, Any] = {"n": _int(params.get("n")), "m": _int(params.get("m")),
                               "updated": _int(params.get("updated")), "quoted": _int(params.get("quoted"))}
    lead_id = params.get("lead") or ""
    case = service.store.get_case(lead_id) if lead_id else None
    if case is not None:
        assessment = case.get("assessment") or {}
        outbox = service.store.outbox_for(lead_id)
        followup = _latest(outbox, "followup")
        card = service.store.open_card_for(lead_id)
        why = reasons(card["payload"], assessment) if card else []
        asked = followup["payload"].get("items", []) if followup else []
        context.update(state=case["state"], choice=params.get("choice"),
                       recipient=assessment.get("recipient") or "the broker",
                       items=len([key for key in asked if key != "uw_question"]),
                       street=_values(service, lead_id).get("street_address") or "",
                       reason=why[0]["text"] if why else "",
                       failed=bool(outbox) and outbox[-1]["status"] == "failed")
    text = p.banner_text(notice, **context)
    return {"kind": "notice", "text": text} if text else None


def decision_card(service: Service, card: Mapping[str, Any], *, morning: date | None, back: str,
                  show_case_link: bool = False, draft: str | None = None, in_case: bool = False) -> dict[str, Any]:
    lead_id = card["lead_id"]
    payload = card["payload"]
    assessment = _assessment(service, lead_id)
    values = _values(service, lead_id)
    recipient = assessment.get("recipient") or "the broker"
    recommendation = payload.get("recommendation")
    badge, tone = p.recommendation_badge(recommendation)
    # Cards written before ask sections were recorded only carry labels.
    ask_items = payload.get("ask_items") or [{"label": label, "section": "", "kind": "missing"}
                                             for label in payload.get("asks", [])]
    asks = len(ask_items)
    conditions = len(payload.get("conditions") or [])
    approving = f"Approves {p.plural(conditions, 'condition')}" if conditions else "Records your approval"
    message = payload.get("decline_message") or draft or template_decline_message(service.assess(lead_id))
    actions = {
        "approve": {
            "choice": "approve", "short": "Approve", "panel_id": f"approve-{card['id']}",
            "label": "Approve and send email" if asks else "Approve and send quote",
            "consequence": (f"{approving}, then sends one email to {recipient} asking for {p.plural(asks, 'item')}."
                            if asks else f"{approving} and sends the quote to {recipient}."),
        },
        "ask_broker": {
            "choice": "ask_broker", "short": "Ask broker…", "panel_id": f"ask-{card['id']}",
            "label": "Send email to broker" if asks else "Send question to broker", "question_required": asks == 0,
            "consequence": (f"Sends one email to {recipient} asking for {p.plural(asks, 'item')}, plus your question if you add one."
                            if asks else f"Sends one email to {recipient} with your question."),
        },
        "decline": {
            "choice": "decline", "short": "Decline…", "panel_id": f"decline-{card['id']}",
            "label": "Send decline notice", "message": message,
            "consequence": f"Sends this decline notice to {recipient}.",
        },
    }
    primary = actions.get(recommendation) if recommendation else None
    if morning is not None:
        effective, overdue = p.days_label(values.get("effective_date"), morning)
    else:
        effective, overdue = p.fmt_value("effective_date", values.get("effective_date")), False
    return {
        "id": card["id"], "lead_id": lead_id, "name": p.insured_name(values), "property": p.property_line(values),
        "tier": p.tier_label(assessment.get("tier", 9)), "effective": effective, "overdue": overdue,
        "badge": badge, "tone": tone, "decline_edge": recommendation == "decline",
        "reasons": reasons(payload, assessment),
        "agent_note": payload.get("summary", "") if payload.get("written_by") == "agent" else "",
        "primary": primary, "others": [action for action in actions.values() if action is not primary],
        "preview": p.email_preview(ask_items) if ask_items else None,
        "preview_label": ("If you approve or ask the broker instead:" if recommendation == "decline"
                          else "The email this releases:"),
        "terms": payload.get("terms") or [], "back": back, "show_case_link": show_case_link, "in_case": in_case,
    }


def _whats_next(service: Service, lead_id: str, state: str, card: Mapping[str, Any] | None) -> str:
    assessment = _assessment(service, lead_id)
    followup = _latest(service.store.outbox_for(lead_id), "followup")
    return p.whats_next(state, card_payload=card["payload"] if card else None,
                        followup_items=followup["payload"].get("items", []) if followup else [],
                        followup_round=followup["round"] if followup else 0,
                        quote=service.store.get_quote(lead_id),
                        knockout_trees=[entry["tree"] for entry in assessment.get("knockouts", [])])


def queue_page(service: Service, params: Mapping[str, str]) -> dict[str, Any]:
    morning = morning_of(service)
    board = service.board()
    rows = []
    for row in board["cases"]:
        lead_id = row["lead_id"]
        values = _values(service, lead_id)
        effective, overdue = p.days_label(row["effective_date"], morning) if morning else ("", False)
        rows.append({"lead_id": lead_id, "name": p.insured_name(values), "property": p.property_line(values),
                     "tier": p.tier_label(row["tier"]), "effective": effective, "overdue": overdue,
                     "status": p.status_label(row["state"]), "tone": p.status_tone(row["state"]),
                     "next": _whats_next(service, lead_id, row["state"], row["card"])})
    cards = [decision_card(service, row["card"], morning=morning, back="/", show_case_link=True,
                           draft=row["draft_decline"] or None) for row in board["needs_uw"]]
    counts = board["counts"]
    tiles = [
        {"label": "Needs your decision", "count": len(cards), "tone": "amber", "href": "#needs-decision"},
        {"label": "Waiting on broker", "count": counts.get("FOLLOW_UP_SENT", 0), "tone": "blue", "href": "#all-leads"},
        {"label": "Quotes sent", "count": counts.get("QUOTED", 0), "tone": "green", "href": "#all-leads"},
        {"label": "Declined", "count": counts.get("DECLINED", 0), "tone": "slate", "href": "#all-leads"},
    ]
    return {"chrome": chrome(service), "banner": banner(service, params), "tiles": tiles, "cards": cards,
            "rows": rows, "waiting": counts.get("FOLLOW_UP_SENT", 0)}


EMAIL_KINDS = {"followup": "Follow-up", "quote": "Quote", "decline": "Decline notice"}
DECISION_TEXT = {"approve": "You approved", "ask_broker": "You asked the broker", "decline": "You declined"}


def _stands(state: str, view: Mapping[str, Any], assessment: Mapping[str, Any], recipient: str) -> dict[str, Any]:
    """The 'Where this stands' panel for leads without an open decision card."""
    outbox = view["outbox"]
    if state == "FOLLOW_UP_SENT":
        row = _latest(outbox, "followup")
        count = len(row["payload"].get("items", [])) if row else 0
        when = p.fmt_when(row["created_at"]) if row else "earlier"
        round_ = row["round"] if row else 0
        return {"text": f"We asked the broker for {p.plural(count, 'item')} {when} (round {round_}). "
                        "When they reply, the assistant re-checks the lead automatically."}
    if state == "QUOTED":
        quote = view["quote"] or {}
        row = _latest(outbox, "quote")
        when = p.fmt_when(row["created_at"]) if row else "earlier"
        conditions = quote.get("conditions") or []
        text = (f"Quote sent {when} with {p.plural(len(conditions), 'condition')}." if conditions
                else f"Quote sent {when} with no conditions.")
        return {"text": text, "conditions": conditions, "subjectivities": quote.get("subjectivities") or []}
    if state == "DECLINED":
        row = _latest(outbox, "decline")
        when = p.fmt_when(row["created_at"]) if row else "earlier"
        found = [{"tag": p.page_name(entry["tree"]), "text": p.reason_text(entry["detail"])}
                 for entry in assessment.get("knockouts", [])]
        return {"text": f"Declined {when}.", "reasons": found, "after": f"Decline notice sent to {recipient}."}
    if state == "AWAITING_UW":
        return {"text": "This lead needs your decision."}
    return {"text": "The assistant is working on this lead."}


def _conversation(service: Service, lead_id: str, view: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every email sent, every broker reply (with what the assistant read from it) and every UW decision, in order."""
    registry = service.registry
    read_as: dict[str, list[dict[str, str]]] = {}
    for fact in service.store.facts_for(lead_id):
        if fact.source == "reply":
            label = registry[fact.field].label if fact.field in registry else fact.field
            read_as.setdefault(fact.detail, []).append({"label": label, "value": p.fmt_value(fact.field, fact.value, registry)})
    reply_events = [event for event in view["events"] if event["type"] == "reply_received"]
    items: list[dict[str, Any]] = []
    for row in view["outbox"]:
        lines = (row["payload"].get("body") or "").splitlines()
        items.append({"type": "email", "at": row["created_at"], "when": p.fmt_when(row["created_at"]),
                      "kind": EMAIL_KINDS.get(row["kind"], row["kind"]), "round": row["round"],
                      "to": row["payload"].get("to", ""), "subject": row["payload"].get("subject", ""),
                      "preview": "\n".join(lines[:3]), "rest": "\n".join(lines[3:]),
                      "status": "Sent" if row["status"] == "sent" else "Retrying"})
    for index, message in enumerate(view["messages"]):
        flags = reply_events[index]["payload"].get("flags", []) if index < len(reply_events) else []
        items.append({"type": "reply", "at": message["created_at"], "when": p.fmt_when(message["created_at"]),
                      "body": message["body"], "read_as": read_as.get(f"reply r{message['round']}", []), "flags": flags})
    for event in view["events"]:
        if event["type"] == "uw_decision":
            items.append({"type": "decision", "at": event["created_at"], "when": p.fmt_when(event["created_at"]),
                          "text": DECISION_TEXT.get(event["payload"].get("choice"), "You decided"),
                          "note": event["payload"].get("note", "")})
    order = {"decision": 0, "email": 1, "reply": 2}
    items.sort(key=lambda item: (item["at"], order[item["type"]]))
    return items


def case_page(service: Service, lead_id: str, params: Mapping[str, str]) -> dict[str, Any] | None:
    view = service.case_view(lead_id)
    if view is None:
        return None
    registry = service.registry
    morning = morning_of(service)
    lead, case, assessment = view["lead"], view["case"], view["assessment"]
    values = _values(service, lead_id)
    state = case["state"]
    recipient = assessment.get("recipient") or "the broker"
    effective, overdue = p.days_label(values.get("effective_date"), morning) if morning else ("Not provided", False)
    checks = []
    for tree in assessment.get("trees", []):
        badge, tone = p.tree_badge(tree)
        checks.append({"name": p.page_name(tree["tree"]), "badge": badge, "tone": tone, "reason": p.tree_reason(tree, registry)})
    facts = assessment.get("facts", {})
    card = view["card"]
    return {
        "chrome": chrome(service), "banner": banner(service, params), "lead_id": lead_id,
        "name": p.insured_name(values), "property": p.property_line(values),
        "status": p.status_label(state), "tone": p.status_tone(state),
        "tier": p.tier_label(assessment.get("tier", 9)), "effective": effective, "overdue": overdue,
        "channel": p.CHANNELS.get(lead.source, lead.source),
        "card": decision_card(service, card, morning=morning, back=f"/cases/{lead_id}", in_case=True) if card else None,
        "stands": _stands(state, view, assessment, recipient),
        "flagged": [check for check in checks if check["badge"] != "Pass"],
        "passed": [check for check in checks if check["badge"] == "Pass"],
        "conversation": _conversation(service, lead_id, view),
        "key_facts": p.key_facts(facts, registry),
        "still_needed": [ask["label"] for ask in assessment.get("required_asks", [])],
        "details": {
            "facts": [{"label": registry[name].label if name in registry else name, "key": name,
                       "value": p.fmt_value(name, entry["value"], registry), "source": p.source_label(entry, registry)}
                      for name, entry in sorted(facts.items())],
            "tool_calls": [{"run": call["run_id"], "tool": p.tool_label(call["tool"]), "ok": call["ok"],
                            "result": "Done" if call["ok"] else
                            "Blocked: " + "; ".join(reason.removeprefix("Rejected: ") for reason in call["reasons"])}
                           for call in view["tool_calls"]],
            "events": [{"when": p.fmt_when(event["created_at"]), "what": p.event_label(event["type"])}
                       for event in view["events"]],
        },
    }
