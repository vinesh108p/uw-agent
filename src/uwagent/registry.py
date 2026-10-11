"""Field registry: the contract every lead is triaged against."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class FieldDef:
    name: str
    label: str
    section: str
    kind: str
    options: tuple[str, ...] | None
    required: str
    producer_editable: bool
    consumers: tuple[str, ...]
    required_when: str | None = None
    missing_default: str | None = None
    derived_from: str | None = None


_PREDICATE = re.compile(r"^\s*(\w+)\s*(!=|=|in)\s*(.+?)\s*$")


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def eval_predicate(expr: str, values: Mapping[str, Any]) -> bool | None:
    """Evaluate a registry `requiredWhen` expression; None when the parent value is unknown."""
    match = _PREDICATE.match(expr)
    if match is None:
        raise ValueError(f"unsupported requiredWhen: {expr!r}")
    field, op, rhs = match.groups()
    value = values.get(field)
    if value is None:
        return None
    if op == "in":
        return _norm(value) in {_norm(part) for part in rhs.strip("()").split(",")}
    if op == "=":
        return _norm(value) == _norm(rhs)
    return _norm(value) != _norm(rhs)


class Registry:
    def __init__(self, fields: dict[str, FieldDef]):
        self._fields = fields

    @classmethod
    def load(cls, path: Path) -> "Registry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))["fields"]
        fields: dict[str, FieldDef] = {}
        for name, meta in raw.items():
            kind = meta["type"]["kind"]
            fields[name] = FieldDef(
                name=name,
                label=meta["label"],
                section=meta["section"],
                kind=kind,
                options=tuple(meta["type"]["options"]) if kind == "select" else None,
                required=meta["required"],
                producer_editable=bool(meta["editableByProducer"]),
                consumers=tuple(meta.get("consumers", [])),
                required_when=meta.get("requiredWhen"),
                missing_default=meta.get("missingDefault"),
                derived_from=meta.get("derivedFrom"),
            )
        return cls(fields)

    def __getitem__(self, name: str) -> FieldDef:
        return self._fields[name]

    def __contains__(self, name: object) -> bool:
        return name in self._fields

    def names(self) -> list[str]:
        return list(self._fields)

    def is_active(self, name: str, values: Mapping[str, Any]) -> bool | None:
        expr = self._fields[name].required_when
        return None if expr is None else eval_predicate(expr, values)

    def parent_of(self, name: str) -> str | None:
        expr = self._fields[name].required_when
        match = _PREDICATE.match(expr) if expr else None
        return match.group(1) if match else None

    def condition_text(self, name: str) -> str:
        """Plain-language form of a requiredWhen, used to ask follow-on questions in the same email."""
        field, op, rhs = _PREDICATE.match(self._fields[name].required_when).groups()
        parent = self._fields[field]
        if parent.kind == "toggle":
            return f'Only if the answer to "{parent.label}" is {"yes" if _norm(rhs) == "true" else "no"}'
        if op == "in":
            return f"Only if {parent.label} is one of {rhs.strip('()')}"
        return f"Only if {parent.label} is {'not ' if op == '!=' else ''}{rhs}"

    def coerce(self, name: str, value: Any) -> Any:
        """Coerce a raw value (often text from a reply) to the registry type, or raise ValueError."""
        field = self._fields[name]
        if value is None:
            raise ValueError("empty value")
        if field.kind == "select":
            text = str(value).strip()
            for option in field.options or ():
                if option.lower() == text.lower():
                    return option
            raise ValueError(f"{text!r} is not an allowed option for {field.label}")
        if field.kind == "toggle":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("yes", "y", "true"):
                return True
            if text in ("no", "n", "false"):
                return False
            raise ValueError(f"{value!r} is not yes/no")
        if field.kind == "integer":
            if isinstance(value, bool):
                raise ValueError("a yes/no value is not a number")
            if isinstance(value, float):
                if value.is_integer():
                    return int(value)
                raise ValueError(f"{value!r} is not a whole number")
            return int(str(value).replace(",", "").strip())
        if field.kind == "decimal":
            if isinstance(value, bool):
                raise ValueError("a yes/no value is not a number")
            return float(str(value).replace(",", "").strip())
        text = str(value).strip()
        if not text:
            raise ValueError("empty value")
        return text
