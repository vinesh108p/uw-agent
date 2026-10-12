from datetime import date

from uwagent import presenters as p


def test_underwriter_wording():
    assert p.fmt_money(1025000) == "$1,025,000"
    assert p.fmt_value("has_animals", False) == "No" and p.fmt_value("square_feet", 2400) == "2,400 sq ft"
    morning = date(2026, 6, 29)
    assert p.days_label("2026-07-08", morning) == ("Jul 8 · 9 days", False)
    assert p.days_label("2026-06-26", morning) == ("Jun 26 · 3 days ago", True)
    assert p.status_label("AWAITING_UW") == "Needs your decision"
    assert p.source_label({"source": "reply", "detail": "reply r1"}) == "Broker reply (round 1)"
    assert p.source_label({"source": "enrichment", "detail": "iso_ppc"}) == "Looked up: ISO protection class"
    tree = {"tree": "fire_simulation", "certain_decline": True, "possible_decline": False, "outcomes": [], "unknowns": [],
            "decline_reasons": ["Fire simulation fail (P(F) 0.79)"]}
    assert p.page_name("fire_simulation") == "Fire simulation" and p.tree_badge(tree) == ("Decline", "red")
    assert p.tree_reason(tree) == "Fire simulation fail (wildfire failure probability 0.79)"
