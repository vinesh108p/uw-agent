"""Capture deterministic leadgen queues (leads + answer keys) as test fixtures.

Runs the harness generator in-process (read-only import), so no Docker is needed.
Usage: uv run python scripts/capture_fixtures.py 42 7 2024
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim-harness"))

from leadgen import generator  # noqa: E402


def capture(seed: int, out_dir: Path) -> Path:
    config = yaml.safe_load((ROOT / "sim-harness" / "leadgen" / "generator_config.yaml").read_text())
    leads = generator.generate_queue(seed, 10, "mixed", config)
    payload = [
        {"lead": {key: lead[key] for key in ("lead_id", "received_at", "source", "fields")}, "debug": lead["debug"]}
        for lead in leads
    ]
    path = out_dir / f"queue_seed{seed}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


if __name__ == "__main__":
    out = ROOT / "tests" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    for raw in sys.argv[1:] or ["42", "7", "2024"]:
        print(capture(int(raw), out))
