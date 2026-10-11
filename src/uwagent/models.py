"""Wire models shared across modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel


class Lead(BaseModel):
    """Candidate-facing lead envelope from leadgen: `fields` maps registry names to values (None = missing)."""

    lead_id: str
    received_at: str
    source: str
    fields: dict[str, Any]

    @property
    def received_date(self) -> date:
        return date.fromisoformat(self.received_at[:10])


@dataclass(frozen=True)
class UWDecision:
    """An underwriter's resolution of a decision card: approve | ask_broker | decline.

    `scope` records what the UW reviewed (UW items, conditions, knockouts); an approval stays valid
    while the lead's current review items are a subset of it.
    """

    choice: str
    note: str = ""
    round: int = 0
    scope: tuple[str, ...] = ()
