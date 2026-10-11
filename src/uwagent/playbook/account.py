"""Account and protection pages of the FigJam playbook (F01, F02, F09–F12). CONDITION/ADVISORY details are customer-facing."""

from __future__ import annotations

from .base import Outcome, View, advisory, condition, decline, judgment, passed

OCCUPANCY_FIELDS = ("dwelling_type", "dwelling_use_type", "is_rental", "months_unoccupied", "listed_for_sale")
RENTAL_USES = ("Tenant", "Mixed (Secondary/Seasonal & Tenant)")
RCE_TOLERANCE = 0.05


def occupancy(v: View) -> list[Outcome]:
    tree = "occupancy"
    if v.get("listed_for_sale") is True:
        return [decline(tree, "Property is listed for sale")]
    rental = v.get("is_rental")
    use = v.get("dwelling_use_type")
    months = v.get("months_unoccupied")
    out: list[Outcome] = []
    if rental in ("Short-Term Rentals", "Long-Term Rentals") or use in RENTAL_USES:
        if v["has_primary_policy_with_stand"]:
            if rental == "Short-Term Rentals":
                out.append(condition(tree, "str_surcharge_endorsement", "15% surcharge and the short-term rental endorsement"))
            else:
                out.append(condition(tree, "rental_surcharge_15", "15% rental surcharge"))
        elif v["broker_tier"] == "Tier 1":
            out.append(condition(tree, "rental_surcharge_15", "15% rental surcharge"))
        else:
            out.append(judgment(tree, "rental_exception",
                                "Rental without a Stand primary policy: is there a justifiable exception (lead line for a "
                                "larger desirable account, or a well-managed property over $5M Coverage A)? Otherwise decline.",
                                may_decline=True))
    if months is not None and months > 0:
        if not v["has_primary_policy_with_stand"]:
            out.append(decline(tree, f"Unoccupied {months} month(s) without a Stand primary policy"))
        elif months > 2:
            out.append(decline(tree, f"Unoccupied more than 60 days ({months} months)"))
        else:
            out.append(condition(tree, "vacancy_modifications",
                                 "Vacancy terms: 25% surcharge, $100,000 AOP deductible, 3% water deductible, low-temperature "
                                 "alarm or winterization, and twice-weekly interior and exterior visits"))
    return out or [passed(tree, "Occupancy within guidelines")]


def profile(v: View) -> list[Outcome]:
    tree = "profile"
    kyc = v["kyc_score"]
    if kyc <= 5:
        return [passed(tree, f"KYC {kyc}")]
    if kyc <= 7:
        return [judgment(tree, "kyc_6_7",
                         f"KYC {kyc}: decide whether the insured is in the spotlight or private. Playbook: exclude liability; "
                         "if that is a deal killer, add social media and libel/slander exclusions with defense within limits "
                         "(spotlight) or offer premises liability only (private).")]
    return [condition(tree, "exclude_liability", "Personal liability coverage is excluded")]


def trusts(v: View) -> list[Outcome]:
    tree = "trusts"
    if not v["residence_held_in_trust"]:
        return [passed(tree, "Not held in a trust or LLC")]
    return [
        advisory(tree, "trust_questionnaire", "Trust & LLC questionnaire due within 30 days of binding"),
        advisory(tree, "trust_coverage", "Coverage applies only to trust-owned assets (Coverage A/B), Coverage C excluded, "
                                         "premises liability only; occupants should carry their own tenant policy"),
    ]


def pools(v: View) -> list[Outcome]:
    tree = "pools"
    pool = v["pool_type"]
    if pool == "None":
        return [passed(tree, "No pool")]
    out: list[Outcome] = []
    if pool == "Inground" and v["pool_security"] != "Fenced":
        if (v.get("acreage") or 0) >= 2 or v["is_gated_community"]:
            out.append(advisory(tree, "pool_cover_recommended", "We recommend a secure pool cover"))
        else:
            out.append(condition(tree, "pool_secured_cover", "Secured pool cover, or fence with a self-locking gate, within the underwriting period"))
    if pool == "Above Ground" and not v["above_ground_pool_ladder"]:
        out.append(condition(tree, "pool_locking_ladder", "Pull-up or locking pool ladder within the underwriting period"))
    if v["pool_has_diving_board_or_slide"]:
        out.append(condition(tree, "pool_limitation_of_liability", "Limitation of liability endorsement for the pool slide or diving board"))
    return out or [passed(tree, "Pool secured")]


def replacement_cost(v: View) -> list[Outcome]:
    tree = "replacement_cost"
    coverage = v["coverage_a"]
    rce = v["replacement_cost"]
    ratio = coverage / rce
    if ratio < 1 - RCE_TOLERANCE:
        return [advisory(tree, "rc_below_rce",
                         f"Coverage A is below our replacement cost estimate (${rce:,}); we will inspect after binding and "
                         "may adjust coverage to the determined replacement cost")]
    if ratio <= 1.5:
        return [passed(tree, "Coverage A within 150% of the replacement cost estimate")]
    return [condition(tree, "rc_quote_at_rce",
                      f"Coverage A quoted at our replacement cost estimate (${rce:,}) unless documentation supporting the "
                      "requested amount is provided (for example, the current declarations page); we will inspect after binding")]


def protection_class(v: View) -> list[Outcome]:
    tree = "protection_class"
    pc = v["protection_class"]
    if pc not in ("9", "10"):
        return [passed(tree, f"Protection class {pc}")]
    if v["dist_to_nearest_fire_hydrant"] <= 1000:
        response = v["fire_dept_response_time"]
        if response == "Greater than 30 Minutes":
            return [decline(tree, "Protection class 9/10 with fire department response over 30 minutes")]
        if response == "Within 15 Minutes":
            return [passed(tree, "Protection class 9/10 with a hydrant within 1,000 ft and response within 15 minutes")]
        if response == "Unknown":
            return [judgment(tree, "pc_response_unknown", "Protection class 9/10: fire department response time is unknown")]
        out: list[Outcome] = []
        if v["square_feet"] >= 7500 and v["interior_sprinklers"] != "Centrally Monitored Interior Sprinklers":
            out.append(condition(tree, "pc_central_sprinklers", "Centrally monitored interior sprinklers"))
        if v["physical_barriers"]:
            out.append(condition(tree, "pc_knox_box", "Knox box for fire department access within the underwriting period"))
        elif v["fire_alarm"] != "Central Alarm":
            out.append(condition(tree, "pc_central_alarm", "Central station fire alarm within the underwriting period"))
        return out or [passed(tree, "Protection class 9/10 requirements met")]
    if v["road_access"] == "Limited / Dead-end / No Turnaround":
        return [decline(tree, "Protection class 9/10 with no hydrant within 1,000 ft and limited road access")]
    if v["fire_dept_response_time"] == "Greater than 30 Minutes":
        return [decline(tree, "Protection class 9/10 with no hydrant within 1,000 ft and response over 30 minutes")]
    water = "an alternative water source is available" if v["alternative_water_source"] else "no alternative water source"
    return [judgment(tree, "pc_water_supply",
                     f"Protection class 9/10 with no hydrant within 1,000 ft ({water}): tanker service, dry hydrant, "
                     "fittings, year-round access and stored water per square foot are outside the registry; UW review.",
                     may_decline=True)]
