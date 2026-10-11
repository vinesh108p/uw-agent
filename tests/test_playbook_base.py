from datetime import date

from uwagent.playbook.base import decline, evaluate, passed

TODAY = date(2026, 6, 29)
DOMAINS = {"flag": (True, False), "level": ("low", "high")}


def test_certain_decline_needs_no_answers():
    tree = lambda v: [decline("toy", "flag set")] if v["flag"] else [decline("toy", "flag clear")]
    result = evaluate("toy", tree, {}, TODAY, DOMAINS.get)
    assert result.certain_decline and result.relevant_unknowns == set()


def test_only_decision_relevant_unknowns_are_asked():
    tree = lambda v: [decline("toy", "low")] if v["level"] == "low" else [passed("toy", "ok")]
    result = evaluate("toy", tree, {}, TODAY, DOMAINS.get)
    assert result.possible_decline and result.relevant_unknowns == {"level"}
    same = evaluate("toy", lambda v: [passed("toy", "same")], {"flag": None}, TODAY, DOMAINS.get)
    assert same.resolved and [o.detail for o in same.common_outcomes] == ["same"]
