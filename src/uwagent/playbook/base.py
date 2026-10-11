"""Typed outcomes and evaluation of a decision tree over the possible values of missing inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence


class Kind(StrEnum):
    PASS = "pass"
    CONDITION = "condition"
    ADVISORY = "advisory"
    JUDGMENT = "judgment"
    DECLINE = "decline"
    NEED = "need"


@dataclass(frozen=True)
class Outcome:
    kind: Kind
    tree: str
    detail: str
    code: str = ""
    may_decline: bool = False
    field: str = ""

    def signature(self) -> tuple[str, str]:
        return (self.kind.value, self.code or self.detail)


def passed(tree: str, detail: str) -> Outcome:
    return Outcome(Kind.PASS, tree, detail)


def condition(tree: str, code: str, detail: str) -> Outcome:
    """A quote condition. `detail` is customer-facing: it is printed in the quote."""
    return Outcome(Kind.CONDITION, tree, detail, code)


def advisory(tree: str, code: str, detail: str) -> Outcome:
    """Informational term (subjectivity/recommendation); customer-facing; no UW approval needed."""
    return Outcome(Kind.ADVISORY, tree, detail, code)


def judgment(tree: str, code: str, detail: str, may_decline: bool = False) -> Outcome:
    """A question only an underwriter can answer. `detail` is UW-facing."""
    return Outcome(Kind.JUDGMENT, tree, detail, code, may_decline)


def decline(tree: str, detail: str) -> Outcome:
    return Outcome(Kind.DECLINE, tree, detail)


class Unknown(Exception):
    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


class View:
    """Read-only values for a tree; `v[name]` raises Unknown for a missing field so evaluate() can branch."""

    def __init__(self, values: Mapping[str, Any], today: date):
        self._values = values
        self.today = today

    def __getitem__(self, name: str) -> Any:
        value = self._values.get(name)
        if value is None:
            raise Unknown(name)
        return value

    def get(self, name: str) -> Any:
        return self._values.get(name)


@dataclass(frozen=True)
class Branch:
    assignment: dict[str, Any]
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True)
class TreeResult:
    tree: str
    branches: tuple[Branch, ...]

    @property
    def resolved(self) -> bool:
        only = self.branches[0]
        return len(self.branches) == 1 and not only.assignment and all(o.kind is not Kind.NEED for o in only.outcomes)

    @property
    def certain_decline(self) -> bool:
        return all(any(o.kind is Kind.DECLINE for o in b.outcomes) for b in self.branches)

    @property
    def possible_decline(self) -> bool:
        return not self.certain_decline and any(o.kind is Kind.DECLINE for b in self.branches for o in b.outcomes)

    @property
    def common_outcomes(self) -> list[Outcome]:
        """Outcomes that hold however the unknown inputs resolve."""
        first, *rest = self.branches
        common = [o for o in first.outcomes if all(o.signature() in {x.signature() for x in b.outcomes} for b in rest)]
        return [o for o in common if o.kind is not Kind.NEED]

    @property
    def relevant_unknowns(self) -> set[str]:
        """Missing inputs whose answer can change this tree's outcome (empty on a certain decline)."""
        if self.certain_decline:
            return set()
        needs = {o.field for b in self.branches for o in b.outcomes if o.kind is Kind.NEED}
        signatures = {frozenset(o.signature() for o in b.outcomes) for b in self.branches}
        branched: set[str] = set().union(*(b.assignment.keys() for b in self.branches)) if len(signatures) > 1 else set()
        return needs | branched

    @property
    def decline_reasons(self) -> list[Outcome]:
        seen: set[str] = set()
        out: list[Outcome] = []
        for branch in self.branches:
            for outcome in branch.outcomes:
                if outcome.kind is Kind.DECLINE and outcome.detail not in seen:
                    seen.add(outcome.detail)
                    out.append(outcome)
        return out


Tree = Callable[[View], Sequence[Outcome]]
Domain = Callable[[str], Sequence[Any] | None]
MAX_UNKNOWNS = 3


def evaluate(name: str, tree: Tree, values: Mapping[str, Any], today: date, domain: Domain) -> TreeResult:
    """Run `tree`; when it reads a missing input, re-run it once per possible value (up to MAX_UNKNOWNS deep)."""
    branches: list[Branch] = []

    def run(current: dict[str, Any], assignment: dict[str, Any]) -> None:
        try:
            outcomes = tuple(tree(View(current, today)))
        except Unknown as unknown:
            candidates = domain(unknown.field)
            if not candidates or len(assignment) >= MAX_UNKNOWNS:
                need = Outcome(Kind.NEED, name, f"Needs {unknown.field}", field=unknown.field)
                branches.append(Branch(assignment, (need,)))
                return
            for candidate in candidates:
                run({**current, unknown.field: candidate}, {**assignment, unknown.field: candidate})
            return
        branches.append(Branch(assignment, outcomes))

    run(dict(values), {})
    return TreeResult(name, tuple(branches))
