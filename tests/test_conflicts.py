from datetime import date

from uwagent.conflicts import detect_conflicts


def test_detects_anomalies_and_eligibility_conflicts():
    values = {"roof_replacement_year": 2031, "dwelling_use_type": "Primary", "months_unoccupied": 8}
    found = {c.key: c.kind for c in detect_conflicts(values, date(2026, 6, 29))}
    assert found == {"roof_year_future": "anomaly", "primary_but_unoccupied": "eligibility"}
