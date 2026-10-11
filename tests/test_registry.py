from uwagent.registry import eval_predicate


def test_loads_metadata_and_conditions(registry):
    assert registry["roof_material"].kind == "select" and "Clay Tile" in registry["roof_material"].options
    assert registry["protection_class"].producer_editable is False and len(registry.names()) == 73
    assert eval_predicate("foundation_type in (Piers, Stilts, Pilings)", {"foundation_type": "Stilts"}) is True
    assert registry.is_active("trust_name", {"residence_held_in_trust": True}) is True
    assert registry.is_active("trust_name", {}) is None
    assert registry.parent_of("water_heater_age_years") == "water_heater_type"
    assert registry.condition_text("water_heater_age_years") == "Only if Water Heater Type is Tank"
    assert registry.condition_text("trust_name") == 'Only if the answer to "Is the property owned by a trust?" is yes'


def test_coerce(registry):
    assert registry.coerce("roof_material", "clay tile") == "Clay Tile"
    assert registry.coerce("has_animals", "No") is False
    assert registry.coerce("square_feet", "2,400") == 2400
    assert registry.coerce("acreage", "0.5") == 0.5
