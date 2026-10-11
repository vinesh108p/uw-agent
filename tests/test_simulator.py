from uwagent.simulator import simulate_reply


def test_complete_persona_answers_with_valid_values(registry):
    keys = ["roof_material", "square_feet", "water_heater_type", "water_heater_age_years", "uw_question"]
    body, expected = simulate_reply("complete", keys, registry, "LEAD-1", known={"year_built": 1990})
    assert expected == {"roof_material": "Architecture Shingles", "square_feet": 2400, "water_heater_type": "Tankless"}
    assert "1. Architecture Shingles" in body and "4. N/A" in body and "5. Yes" in body
