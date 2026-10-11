"""Turn a lead (+ replies + UW decisions) into the assessment the agent acts on and the guardrails enforce."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence

from .conflicts import Conflict, detect_conflicts
from .enrichment import resolve
from .facts import Fact, FactSet
from .models import Lead, UWDecision
from .playbook import Kind, Outcome, TreeResult, evaluate_playbook
from .playbook.account import OCCUPANCY_FIELDS
from .registry import FieldDef, Registry

UW_CHOICES = ("approve", "ask_broker", "decline")


@dataclass(frozen=True)
class AskItem:
    key: str
    label: str
    kind: Literal["missing", "confirm", "conditional"]
    section: str
    options: tuple[str, ...] | None = None
    current_value: Any = None
    note: str = ""


@dataclass(frozen=True)
class UWItem:
    key: str
    title: str
    detail: str
    may_decline: bool = False


@dataclass
class Assessment:
    lead_id: str
    round: int
    tier: int
    effective_date: str
    facts: dict[str, dict[str, Any]]
    results: list[TreeResult]
    knockouts: list[Outcome]
    required_asks: list[AskItem]
    optional_asks: list[AskItem]
    deferred: list[str]
    conditions: list[Outcome]
    advisories: list[Outcome]
    uw_items: list[UWItem]
    conflicts: list[Conflict]
    system_gaps: list[str]
    subjectivities: list[str]
    scope: list[str]
    blocks_external: bool
    allowed_actions: list[str]
    recommendation: str | None
    allowed_recommendations: list[str]
    followup_format: Literal["itemized", "incomplete_submission"]
    recipient: str
    decision: UWDecision | None

    @property
    def values(self) -> dict[str, Any]:
        return {name: entry["value"] for name, entry in self.facts.items()}

    @property
    def required_ask_keys(self) -> set[str]:
        return {a.key for a in self.required_asks}

    @property
    def allowed_ask_keys(self) -> set[str]:
        return self.required_ask_keys | {a.key for a in self.optional_asks}

    @property
    def terms(self) -> list[str]:
        """Quote terms the broker sees in the same email: playbook conditions plus advisories."""
        return [o.detail for o in self.conditions + self.advisories]

    @property
    def priority(self) -> tuple[int, str, str]:
        """Tier 1 brokers first (lower number = higher priority), then the nearest effective date."""
        return (self.tier, self.effective_date or "9999-12-31", self.lead_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_id": self.lead_id,
            "round": self.round,
            "tier": self.tier,
            "effective_date": self.effective_date,
            "facts": self.facts,
            "trees": [
                {
                    "tree": r.tree,
                    "certain_decline": r.certain_decline,
                    "possible_decline": r.possible_decline,
                    "outcomes": [_outcome(o) for o in r.common_outcomes],
                    "unknowns": sorted(r.relevant_unknowns),
                    "decline_reasons": [o.detail for o in r.decline_reasons],
                }
                for r in self.results
            ],
            "knockouts": [_outcome(o) for o in self.knockouts],
            "required_asks": [asdict(a) for a in self.required_asks],
            "optional_asks": [asdict(a) for a in self.optional_asks],
            "deferred": self.deferred,
            "conditions": [_outcome(o) for o in self.conditions],
            "advisories": [_outcome(o) for o in self.advisories],
            "terms": self.terms,
            "uw_items": [asdict(u) for u in self.uw_items],
            "conflicts": [asdict(c) for c in self.conflicts],
            "system_gaps": self.system_gaps,
            "subjectivities": self.subjectivities,
            "scope": self.scope,
            "blocks_external": self.blocks_external,
            "allowed_actions": self.allowed_actions,
            "recommendation": self.recommendation,
            "allowed_recommendations": self.allowed_recommendations,
            "followup_format": self.followup_format,
            "recipient": self.recipient,
            "decision": asdict(self.decision) if self.decision else None,
        }


def _outcome(o: Outcome) -> dict[str, Any]:
    return {"kind": o.kind.value, "tree": o.tree, "detail": o.detail, "code": o.code, "may_decline": o.may_decline}


def _ask(meta: FieldDef) -> AskItem:
    return AskItem(meta.name, meta.label, "missing", meta.section, meta.options)


def _confirm(meta: FieldDef, values: dict[str, Any], note: str) -> AskItem:
    return AskItem(meta.name, meta.label, "confirm", meta.section, meta.options, values.get(meta.name), note)


def _recipient(lead: Lead, values: dict[str, Any]) -> str:
    if lead.source == "direct_web":
        return values.get("owner_email") or f"applicant+{lead.lead_id.lower()}@portal.stand.example"
    return f"producer+{lead.lead_id.lower()}@broker.example"


def _tier(values: dict[str, Any]) -> int:
    match = re.search(r"\d+", str(values.get("broker_tier") or ""))
    return int(match.group()) if match else 9


def _recommend(allowed: list[str], knockouts: list[Outcome], conflicts: list[Conflict],
               blocks_external: bool, needs_review: bool) -> tuple[str | None, list[str]]:
    if allowed != ["request_uw_decision"]:
        return None, []
    eligibility = any(c.kind == "eligibility" for c in conflicts)
    if knockouts:
        if eligibility and all(o.tree == "occupancy" for o in knockouts):
            return "ask_broker", ["ask_broker", "decline"]
        return "decline", ["decline"]
    if blocks_external:
        return "ask_broker", ["approve", "ask_broker", "decline"]
    if needs_review:
        return "approve", ["approve", "ask_broker"]
    return "ask_broker", ["ask_broker"]  # kill switch: the UW releases the email


def build_assessment(lead: Lead, registry: Registry, *, extra_facts: Sequence[Fact] = (), decision: UWDecision | None = None,
                     flags: Sequence[str] = (), round_: int = 0, ask_threshold: int = 12,
                     autosend_enabled: bool = True) -> Assessment:
    today = lead.received_date
    facts = FactSet.from_submission(lead.fields)
    for fact in extra_facts:
        facts.add(fact)
    resolve(lead.lead_id, facts, today)
    values = facts.values()
    # An anomaly is settled once the producer (or the UW) has confirmed the value.
    conflicts = [c for c in detect_conflicts(values, today)
                 if not (c.kind == "anomaly" and facts.fact(c.field).source in ("reply", "uw"))]
    # Quarantine anomalous values: a likely typo (e.g. a 30 A service) must not drive a decision until confirmed.
    quarantined = {c.field for c in conflicts if c.kind == "anomaly"}
    results = evaluate_playbook({k: v for k, v in values.items() if k not in quarantined}, registry, today)

    knockouts = [o for r in results if r.certain_decline for o in r.decline_reasons]
    demanded: set[str] = set().union(*(r.relevant_unknowns for r in results))

    def askable(name: str) -> bool:
        meta = registry[name]
        return (values.get(name) is None and meta.producer_editable and meta.required != "bind_only"
                and name not in OCCUPANCY_FIELDS)

    required: dict[str, AskItem] = {}
    optional: list[AskItem] = []
    deferred: list[str] = []
    gaps: list[str] = []
    for name in registry.names():
        if values.get(name) is not None:
            continue
        meta = registry[name]
        if not meta.producer_editable:
            if meta.required == "always" or name in demanded:
                gaps.append(name)
        elif meta.required == "bind_only":
            deferred.append(name)
        elif name in OCCUPANCY_FIELDS:
            optional.append(_ask(meta))
        elif meta.required == "always":
            required[name] = _ask(meta)
        elif meta.required == "conditional":
            active = registry.is_active(name, values)
            parent = registry.parent_of(name)
            if active is True or (meta.required_when is None and name in demanded):
                required[name] = _ask(meta)
            elif active is None and parent is not None and askable(parent):
                # Follow-on question in the same email, so the broker never gets a second round for it.
                required[name] = AskItem(name, meta.label, "conditional", meta.section, meta.options,
                                         note=registry.condition_text(name))
    for conflict in conflicts:
        if conflict.kind == "anomaly":
            required[conflict.field] = _confirm(registry[conflict.field], values, conflict.message)

    uw_items = [UWItem(c.key, "Occupancy conflict", c.message, may_decline=True) for c in conflicts if c.kind == "eligibility"]
    conditions: list[Outcome] = []
    advisories: list[Outcome] = []
    for result in results:
        if result.certain_decline:
            continue
        for outcome in result.common_outcomes:
            if outcome.kind is Kind.JUDGMENT:
                uw_items.append(UWItem(outcome.code, result.tree.replace("_", " ").title(), outcome.detail, outcome.may_decline))
            elif outcome.kind is Kind.CONDITION:
                conditions.append(outcome)
            elif outcome.kind is Kind.ADVISORY:
                advisories.append(outcome)
    uw_items += [UWItem(f"reply_flag_{i}", "Reply needs review", text) for i, text in enumerate(flags, start=1)]
    if gaps and not required:
        uw_items.append(UWItem("system_gaps", "System data unavailable", ", ".join(registry[g].label for g in gaps)))

    scope = sorted({f"uw:{u.key}" for u in uw_items} | {f"condition:{o.code}" for o in conditions}
                   | {f"knockout:{o.tree}" for o in knockouts})
    choice = decision.choice if decision else None
    approved = choice == "approve" and set(scope) <= set(decision.scope)
    asked_by_uw = choice == "ask_broker" and decision.round == round_
    if asked_by_uw:
        for conflict in conflicts:
            if conflict.kind == "eligibility":
                required[conflict.field] = _confirm(registry[conflict.field], values, conflict.message)
        if decision.note.strip():
            required["uw_question"] = AskItem("uw_question", "Underwriter question", "confirm", "Underwriting", note=decision.note.strip())

    if approved:
        uw_items = []
    active_knockouts = [] if approved else knockouts
    if active_knockouts and not asked_by_uw:
        required, optional = {}, []
    blocks_external = bool(active_knockouts or any(u.may_decline for u in uw_items)) and not asked_by_uw
    needs_review = bool(uw_items or (conditions and not approved)) and not asked_by_uw

    if choice == "decline":
        allowed = ["send_decline_notice"]
    elif blocks_external or needs_review:
        allowed = ["request_uw_decision"]  # the UW weighs in before the one email goes out
    elif required:
        allowed = ["send_followup"] if (autosend_enabled or asked_by_uw or approved) else ["request_uw_decision"]
    else:
        allowed = ["mark_quote_ready"]

    recommendation, allowed_recommendations = _recommend(allowed, active_knockouts, conflicts, blocks_external, needs_review)
    missing_count = sum(1 for a in required.values() if a.kind == "missing")
    followup_format = "incomplete_submission" if missing_count > ask_threshold or "street_address" in required else "itemized"
    subjectivities = [f"Collect at binding: {registry[name].label}" for name in deferred]
    if optional and allowed != ["send_followup"]:
        subjectivities.append("Confirm occupancy details after quoting: " + ", ".join(a.label for a in optional))
    subjectivities += [o.detail for o in advisories]

    return Assessment(
        lead_id=lead.lead_id, round=round_, tier=_tier(values), effective_date=str(values.get("effective_date") or ""),
        facts=facts.provenance(), results=results, knockouts=knockouts, required_asks=list(required.values()),
        optional_asks=optional, deferred=deferred, conditions=conditions, advisories=advisories, uw_items=uw_items,
        conflicts=conflicts, system_gaps=gaps, subjectivities=subjectivities, scope=scope, blocks_external=blocks_external,
        allowed_actions=allowed, recommendation=recommendation, allowed_recommendations=allowed_recommendations,
        followup_format=followup_format, recipient=_recipient(lead, values), decision=decision,
    )
