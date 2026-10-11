from uwagent.facts import Fact
from uwagent.replies import parse_reply, validate_extraction

ASKED = ["roof_material", "square_feet", "water_heater_age_years"]


def test_numbered_reply_becomes_facts(registry):
    extraction = parse_reply(None, registry, ASKED, "Hi,\n1. clay tile\n2. 2,400\n3. N/A\nThanks")
    facts, flags = validate_extraction(extraction, registry, ASKED, round_=1)
    assert facts == [Fact("roof_material", "Clay Tile", "reply", "reply r1"), Fact("square_feet", 2400, "reply", "reply r1")]
    assert flags == []
