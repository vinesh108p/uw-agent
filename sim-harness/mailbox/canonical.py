"""Narrow receiver wire hashing; independent of candidate dependencies."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any


def _validate(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("JSON nesting exceeds limit")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate(item, depth + 1)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate(item, depth + 1)
        return
    raise ValueError("unsupported JSON value")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def validate_document(raw: bytes) -> None:
    if len(raw) > 1_000_000:
        raise ValueError("JSON document exceeds byte limit")
    value = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    if set(value) - {"lead_id", "to", "from", "from_", "subject", "body", "metadata"}:
        raise ValueError("unsupported wire property")
    if "from" in value and "from_" in value:
        raise ValueError("ambiguous sender aliases")
    _validate(value)


def payload_digest(payload: dict[str, Any]) -> str:
    _validate(payload)
    canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
