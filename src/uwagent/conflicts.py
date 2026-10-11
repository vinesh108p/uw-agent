"""Present-but-inconsistent values. Anomalies are confirmed with the producer; eligibility conflicts go to the UW."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping


@dataclass(frozen=True)
class Conflict:
    key: str
    kind: Literal["anomaly", "eligibility"]
    field: str
    message: str


def detect_conflicts(values: Mapping[str, Any], today: date) -> list[Conflict]:
    out: list[Conflict] = []
    roof_year = values.get("roof_replacement_year")
    built = values.get("year_built")
    if roof_year is not None and roof_year > today.year:
        out.append(Conflict("roof_year_future", "anomaly", "roof_replacement_year",
                            f"The roof replacement year is listed as {roof_year}, which is in the future."))
    elif roof_year is not None and built is not None and roof_year < built:
        out.append(Conflict("roof_before_built", "anomaly", "roof_replacement_year",
                            f"The roof replacement year ({roof_year}) is earlier than the year built ({built})."))
    amps = values.get("electrical_panel_size_amps")
    if amps is not None and amps < 60:
        out.append(Conflict("amps_implausible", "anomaly", "electrical_panel_size_amps",
                            f"The electrical service is listed as {amps} amps, which is unusually low."))
    acreage = values.get("acreage")
    if acreage is not None and acreage <= 0:
        out.append(Conflict("acreage_zero", "anomaly", "acreage", "The lot size is listed as 0 acres."))
    dwelling = values.get("dwelling_type") or ""
    use = values.get("dwelling_use_type")
    months = values.get("months_unoccupied")
    if values.get("number_of_residents") == 0 and dwelling.startswith("Owner Occupied"):
        out.append(Conflict("zero_residents", "anomaly", "number_of_residents",
                            "The home is listed as owner-occupied with 0 residents."))
    if use == "Primary" and months is not None and months > 2:
        out.append(Conflict("primary_but_unoccupied", "eligibility", "months_unoccupied",
                            f"Listed as a primary residence but unoccupied for {months} consecutive months."))
    if use == "Primary" and values.get("is_rental") == "Short-Term Rentals":
        out.append(Conflict("primary_with_str", "eligibility", "is_rental",
                            "Listed as a primary residence but also used for short-term rentals."))
    if dwelling.startswith("Owner Occupied") and use in ("Secondary", "Seasonal", "Tenant"):
        out.append(Conflict("owner_occupied_vs_use", "eligibility", "dwelling_use_type",
                            f"Listed as owner-occupied but the occupancy type is {use}."))
    return out
