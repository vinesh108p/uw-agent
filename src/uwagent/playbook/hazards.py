"""Property hazard pages of the FigJam playbook (F03–F08). CONDITION details are customer-facing."""

from __future__ import annotations

from .base import Outcome, View, condition, decline, judgment, passed

INELIGIBLE_PANELS = frozenset({"Federal Pacific", "Stab-Lok", "Zinsco", "Challenger", "Sylvania"})
NEIGHBOR_TOO_CLOSE_FT = 15
STEEP_SLOPE_DEG = 20
PIER_FOUNDATIONS = frozenset({"Piers", "Stilts", "Pilings"})
COMBUSTIBLE_ROOFS = frozenset({"Wood Shake", "Wood Shingle", "Other"})
COMPOSITION_ROOFS = frozenset({"Architecture Shingles", "Asphalt Fiberglass Composite"})


def tier1_or_rounded(v: View) -> bool:
    """FigJam 'Tier one broker or rounded account?': Tier 1 broker, or the insured already has a Stand primary policy."""
    return v["broker_tier"] == "Tier 1" or v["has_primary_policy_with_stand"] is True


def post_pier(v: View) -> list[Outcome]:
    tree = "post_pier"
    if v["foundation_type"] not in PIER_FOUNDATIONS:
        return [passed(tree, "Not a post & pier foundation")]
    if v["post_pier_supports_living_area"]:
        return [decline(tree, "Post & pier foundation under living area")]
    if v["year_built"] < 2000:
        return [decline(tree, "Post & pier decking on a home built before 2000")]
    height = v["deck_height_ft"]
    if height <= 8:
        return [condition(tree, "surcharge_15_deck", "15% surcharge for post & pier decking up to 8 ft above grade")]
    if height <= 12:
        return [condition(tree, "surcharge_25_deck", "25% surcharge for post & pier decking 8 to 12 ft above grade")]
    return [decline(tree, "Deck more than 12 ft above grade")]


def fire_simulation(v: View) -> list[Outcome]:
    tree = "fire_simulation"
    pf = v["p_f"]
    if pf <= 0.50:
        return [passed(tree, f"Fire simulation pass (P(F) {pf:.2f})")]
    failures = []
    if v["road_access"] == "Limited / Dead-end / No Turnaround":
        failures.append("limited road access")
    neighbor = v["min_distance_to_neighbor_ft"]
    if neighbor < NEIGHBOR_TOO_CLOSE_FT:
        failures.append(f"neighboring home {neighbor} ft away")
    if failures:
        return [decline(tree, f"Fire simulation fail (P(F) {pf:.2f}); legacy review fails: {', '.join(failures)}")]
    mitigation = []
    if v["vegetation_clearance"] == "Too Close":
        mitigation.append("heavy vegetation / inadequate defensible space")
    elif v["slope_angle_deg"] > STEEP_SLOPE_DEG:
        mitigation.append("steep slope increases clearance needs")
    if v["is_7a_compliant"] is False:
        mitigation.append("not Chapter 7A compliant")
    if mitigation:
        return [judgment(tree, "fire_mitigation",
                         f"Fire simulation fail (P(F) {pf:.2f}); legacy review: {', '.join(mitigation)}. Determine client "
                         "willingness to mitigate (yes: quote with a mitigation plan; no: decline).", may_decline=True)]
    return [judgment(tree, "fire_legacy",
                     f"Fire simulation fail (P(F) {pf:.2f}); legacy checks pass. Consider legacy underwriting with a "
                     "preliminary mitigation plan to discuss with the broker.", may_decline=True)]


def roof(v: View) -> list[Outcome]:
    tree = "roof"
    pf = v["p_f"]
    roof_class = v.get("roof_classification")
    if roof_class is None:
        if pf <= 0.15:
            return [passed(tree, "Unknown roof class; low wildfire exposure")]
        material = v["roof_material"]
        if material in COMPOSITION_ROOFS:
            roof_class = "Class A" if v.today.year - v["roof_replacement_year"] <= 20 else "Class B"
        else:
            roof_class = "Class B" if material in COMBUSTIBLE_ROOFS else "Class A"
    if roof_class == "Class A":
        return [passed(tree, "Class A roof")]
    if pf <= 0.15:
        return [passed(tree, "Non-Class A roof; low wildfire exposure")]
    if pf <= 0.50:
        return [condition(tree, "roof_class_a_first_term",
                          "Confirm a Class A roof (roofing permit, contractor invoice, manufacturer documentation, or "
                          "inspection) or replace the roof within the first policy term")]
    return [condition(tree, "roof_class_a_60_days",
                      "Confirm a Class A roof (roofing permit, contractor invoice, manufacturer documentation, or "
                      "inspection) or replace the roof within 60 days of binding")]


def siding(v: View) -> list[Outcome]:
    tree = "siding"
    if v["siding_material"] != "Wood Shake / Shingle":
        return [passed(tree, "Siding is not wood shake or shingle")]
    pf = v["p_f"]
    if pf <= 0.15:
        return [passed(tree, "Wood shake siding; low wildfire exposure")]
    if pf <= 0.50:
        return [condition(tree, "siding_class_a_first_term", "Confirm Class A siding or replace the siding within the first policy term")]
    return [condition(tree, "siding_class_a_uw_period", "Confirm Class A siding or replace the siding within the underwriting period")]


def electrical(v: View) -> list[Outcome]:
    tree = "electrical"
    out: list[Outcome] = []
    if v["has_knob_and_tube_wiring"]:
        if tier1_or_rounded(v):
            out.append(judgment(tree, "knob_tube_replace",
                                "Knob & tube wiring (Tier 1 broker or rounded account): replace within the first term if "
                                "isolated to low-draw areas, otherwise within the underwriting period."))
        else:
            out.append(judgment(tree, "knob_tube_review",
                                "Knob & tube wiring without a Tier 1 broker or rounded account: isolated low-draw areas, "
                                "replace within the first term; high-draw areas or whole house, decline.", may_decline=True))
    brand = v["electrical_panel_brand"]
    amps = v["electrical_panel_size_amps"]
    problems = []
    if brand in INELIGIBLE_PANELS:
        problems.append(f"{brand} panel")
    if amps < 120:
        problems.append(f"{amps} amp service")
    if problems:
        if tier1_or_rounded(v):
            out.append(condition(tree, "panel_replace_uw_period",
                                 f"Replace the electrical panel within the underwriting period ({', '.join(problems)})"))
        else:
            out.append(decline(tree, f"Electrical: {', '.join(problems)} without a Tier 1 broker or rounded account"))
    return out or [passed(tree, "No electrical hazards")]


def plumbing(v: View) -> list[Outcome]:
    tree = "plumbing"
    out: list[Outcome] = []
    if v["plumbing_age_years"] > 30:
        if tier1_or_rounded(v):
            out.append(condition(tree, "plumbing_inspection_first_term", "Plumbing inspection within the first policy term (plumbing over 30 years old)"))
        else:
            out.append(decline(tree, "Plumbing older than 30 years without a Tier 1 broker or rounded account"))
    if v["water_heater_type"] == "Tank" and v["water_heater_age_years"] > 10:
        if v["water_heater_location"] == "In or Above Finished Space":
            if tier1_or_rounded(v):
                out.append(condition(tree, "water_heater_inspection_first_term",
                                     "Water heater inspection within the first policy term (tank over 10 years old in finished space)"))
            else:
                out.append(decline(tree, "Tank water heater over 10 years old in finished space without a Tier 1 broker or rounded account"))
        else:
            out.append(condition(tree, "water_heater_inspection_first_term", "Water heater inspection within the first policy term (tank over 10 years old)"))
    return out or [passed(tree, "Plumbing within guidelines")]
