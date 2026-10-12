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


def test_unparseable_dates_never_break_a_page():
    assert p.days_label("7/15/2026", date(2026, 6, 29)) == ("7/15/2026", False)


def test_times_are_labelled_utc_when_the_server_runs_in_utc(monkeypatch):
    import time
    from datetime import datetime, timezone

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        now = datetime(2026, 6, 29, 15, 0, tzinfo=timezone.utc)
        assert p.fmt_when("2026-06-29T14:30:00.000000Z", now) == "today at 14:30 UTC"
        assert p.iso_ms("2026-06-29T14:30:00.123456Z") == "2026-06-29T14:30:00.123Z"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_asked_phrase_names_items_and_the_underwriters_question():
    assert p.asked_phrase(["roof_material", "uw_question", "acreage"]) == "2 items and your question"
    assert p.asked_phrase(["acreage"]) == "1 item" and p.asked_phrase(["uw_question"]) == "your question"


def test_underwriter_item_tags_use_playbook_page_names():
    assert p.tag_for_title("Post Pier") == "Post & pier" and p.tag_for_title("Profile") == "Profile (KYC)"
    assert p.tag_for_title("Occupancy conflict") == "Occupancy conflict"
