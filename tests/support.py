"""Shared test helpers."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load_queue(seed: int) -> list[dict]:
    return json.loads((FIXTURES / f"queue_seed{seed}.json").read_text())
