"""Field values with provenance. Higher-ranked sources win; within a rank the latest fact wins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SOURCE_RANK = {"uw": 6, "reply": 5, "submission": 4, "enrichment": 3, "derived": 2, "default": 1}


@dataclass(frozen=True)
class Fact:
    field: str
    value: Any
    source: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.source not in SOURCE_RANK:
            raise ValueError(f"unknown fact source {self.source!r}")


class FactSet:
    def __init__(self, facts: Iterable[Fact] = ()):
        self._facts: list[Fact] = []
        for fact in facts:
            self.add(fact)

    @classmethod
    def from_submission(cls, fields: Mapping[str, Any]) -> "FactSet":
        return cls(Fact(name, value, "submission") for name, value in fields.items() if value is not None)

    def add(self, fact: Fact) -> None:
        if fact.value is not None:
            self._facts.append(fact)

    def fact(self, field: str) -> Fact | None:
        best: Fact | None = None
        for candidate in self._facts:
            if candidate.field == field and (best is None or SOURCE_RANK[candidate.source] >= SOURCE_RANK[best.source]):
                best = candidate
        return best

    def get(self, field: str) -> Any:
        found = self.fact(field)
        return None if found is None else found.value

    def values(self) -> dict[str, Any]:
        return {name: self.get(name) for name in {f.field for f in self._facts}}

    def provenance(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name in sorted({f.field for f in self._facts}):
            best = self.fact(name)
            out[name] = {"value": best.value, "source": best.source, "detail": best.detail}
        return out
