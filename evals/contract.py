"""Answer-key behavior contract.

Expectations come ONLY from the lead, the leadgen answer key, the registry and the simulated world (uwagent.world).
It is a second, independent reading of the FigJam: it must never import the engine (playbook, assessment,
enrichment, agent, tools), otherwise the eval would only prove the engine agrees with itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from uwagent import world
from uwagent.registry import Registry

OCCUPANCY = frozenset({"dwelling_type", "dwelling_use_type", "is_rental", "months_unoccupied", "listed_for_sale"})
ANOMALY_FIELDS = frozenset({"roof_replacement_year", "electrical_panel_size_amps", "acreage", "number_of_residents"})
_PARENT = re.compile(r"^\s*(\w+)")


@dataclass
class Expectation:
    lead_id: str
    action: str | None
    no_email: bool
    must_ask: set[str]
    must_not_ask: set[str]
    conflict_fields: set[str]
    reasons: list[str] = field(default_factory=list)


def _askable(name: str, values: dict[str, Any], registry: Registry) -> bool:
    meta = registry[name]
    return values.get(name) is None and meta.producer_editable and meta.required != "bind_only" and name not in OCCUPANCY


def _parent(registry: Registry, name: str) -> str:
    return _PARENT.match(registry[name].required_when).group(1)


def _review_reasons(f: dict[str, Any], archetypes: set[str], effective: dict[str, Any], tier1_or_rounded: bool) -> list[str]:
    """Playbook conditions or judgment calls the UW must weigh in on before the single email goes out."""
    reasons = []
    kyc = f.get("kyc_score")
    if kyc is not None and kyc > 5:
        reasons.append("KYC above 5")
    if tier1_or_rounded and {"electrical_hazard", "plumbing_water_heater"} & archetypes:
        reasons.append("Tier 1 hazard conditions")
    if "pool_hazard" in archetypes:
        reasons.append("pool conditions")
    rce = f.get("replacement_cost") or world.replacement_cost(effective)
    if f.get("coverage_a") and rce and f["coverage_a"] / rce > 1.5:
        reasons.append("Coverage A above 150% of RCE")
    return reasons


def expect(lead: dict[str, Any], debug: dict[str, Any], registry: Registry) -> Expectation:
    f = lead["fields"]
    lead_id = lead["lead_id"]
    archetypes = set(debug["injected_archetypes"])
    primary = f.get("has_primary_policy_with_stand")
    primary = world.crm_has_primary_policy(lead_id) if primary is None else primary
    tier = f.get("broker_tier") or world.crm_broker_tier(lead_id)
    tier1_or_rounded = tier == "Tier 1" or primary is True
    effective = dict(f)
    effective["protection_class"] = f.get("protection_class") or world.ppc(f) or "9"
    effective["pool_type"] = f.get("pool_type") or "None"

    reasons: list[str] = []
    if "post_and_pier" in archetypes:
        reasons.append("post & pier: every branch declines")
    if "pc_9_10_rural" in archetypes:
        reasons.append("PC 9/10 without a hydrant and with limited road access")
    if "wildfire_severe" in archetypes:
        reasons.append("fire simulation fail with a neighbor under 15 ft")
    months = f.get("months_unoccupied")
    if months is not None and months > 0 and (not primary or months > 2):
        reasons.append("unoccupied")
    if f.get("listed_for_sale") is True:
        reasons.append("listed for sale")
    if "electrical_hazard" in archetypes and not tier1_or_rounded:
        reasons.append("ineligible electrical without Tier 1 or rounded account")
    if "plumbing_water_heater" in archetypes and not tier1_or_rounded:
        reasons.append("old plumbing without Tier 1 or rounded account")
    declines = bool(reasons)
    eligibility_conflict = "occupancy_conflict" in archetypes and not declines

    conflict_fields: set[str] = set()
    for perturbation in debug["perturbations"]:
        if perturbation["kind"] == "conflict" and perturbation["field"] in ANOMALY_FIELDS:
            if perturbation["field"] != "number_of_residents" or str(f.get("dwelling_type") or "").startswith("Owner Occupied"):
                conflict_fields.add(perturbation["field"])
    # The generator's clean data can itself be impossible (a roof replaced before the home was built): confirm it too.
    if f.get("roof_replacement_year") is not None and f.get("year_built") is not None and f["roof_replacement_year"] < f["year_built"]:
        conflict_fields.add("roof_replacement_year")

    conditional = {k for k in registry.names() if registry[k].required == "conditional" and registry[k].required_when}
    present = {k for k, v in f.items() if v is not None}
    system = {k for k in registry.names() if not registry[k].producer_editable}
    bind_only = {k for k in registry.names() if registry[k].required == "bind_only"}
    inactive = {k for k in conditional
                if registry.is_active(k, effective) is False
                or (registry.is_active(k, effective) is None and not _askable(_parent(registry, k), effective, registry))}
    demand_only = {"opening_protection"}
    if not (effective["pool_type"] == "Inground" and f.get("pool_security") != "Fenced" and (f.get("acreage") or 0) < 2):
        demand_only.add("is_gated_community")
    optional = {k for k in OCCUPANCY if f.get(k) is None}
    must_not_ask = (system | bind_only | inactive | demand_only | present) - conflict_fields - optional

    must_ask: set[str] = set()
    if not declines and not eligibility_conflict:
        for k in registry.names():
            meta = registry[k]
            if f.get(k) is not None or not meta.producer_editable or k in OCCUPANCY or k == "pool_type":
                continue
            if meta.required == "always":
                if not (k == "has_knob_and_tube_wiring" and f.get("year_built") is not None):  # FigJam default from year built
                    must_ask.add(k)
            elif k in conditional:
                active = registry.is_active(k, effective)
                if active is True or (active is None and _askable(_parent(registry, k), effective, registry)):
                    must_ask.add(k)  # follow-on questions ride in the same email
        must_ask |= conflict_fields

    review = [] if declines or eligibility_conflict else _review_reasons(f, archetypes, effective, tier1_or_rounded)
    if declines or eligibility_conflict or review:
        if eligibility_conflict:
            reasons.append("occupancy eligibility conflict")
        reasons += review
        action = "request_uw_decision"
    elif must_ask:
        action = "send_followup"
    else:
        kyc = f.get("kyc_score") if f.get("kyc_score") is not None else world.kyc_score(lead_id)
        if kyc is None:
            reasons.append("KYC unavailable")
        action = "request_uw_decision" if kyc is None else "mark_quote_ready"
    return Expectation(lead_id, action, action == "request_uw_decision", must_ask, must_not_ask, conflict_fields, reasons)
