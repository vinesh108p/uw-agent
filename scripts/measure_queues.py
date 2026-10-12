"""Measure what an incoming queue looks like to the engine (no LLM, no services needed).

Generates queues in-process with the harness generator, runs the engine on each lead before any reply,
and prints where the leads land and how many questions each one needs.

Usage: uv run python scripts/measure_queues.py [first_seed] [last_seed]     (defaults: 1 30)
"""

from __future__ import annotations

import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim-harness"))

from leadgen import generator  # noqa: E402

from uwagent.assessment import build_assessment  # noqa: E402
from uwagent.config import load_settings  # noqa: E402
from uwagent.models import Lead  # noqa: E402
from uwagent.registry import Registry  # noqa: E402


def path_of(a) -> str:
    if a.allowed_actions == ["mark_quote_ready"]:
        return "quote now"
    if a.allowed_actions == ["send_followup"]:
        return "follow-up only"
    if a.knockouts:
        return "UW: certain decline"
    if a.blocks_external:
        return "UW: may decline"
    return "UW: review or approve conditions"


def main(first: int, last: int) -> None:
    config = yaml.safe_load((ROOT / "sim-harness" / "leadgen" / "generator_config.yaml").read_text())
    registry = Registry.load(load_settings().registry_path)
    paths: Counter[str] = Counter()
    emailed_asks: list[int] = []  # leads that will get an email (everything except certain declines)
    raw_missing = filled = 0
    total = 0
    for seed in range(first, last + 1):
        for raw in generator.generate_queue(seed, 10, "mixed", config):
            lead = Lead(lead_id=raw["lead_id"], received_at=raw["received_at"], source=raw["source"], fields=raw["fields"])
            a = build_assessment(lead, registry)
            total += 1
            paths[path_of(a)] += 1
            n = sum(1 for item in a.released_asks if item.kind == "missing")
            if not a.knockouts:
                emailed_asks.append(n)
            missing = [name for name in registry.names() if lead.fields.get(name) is None and registry[name].required != "bind_only"]
            raw_missing += len(missing)
            filled += sum(1 for name in missing if a.values.get(name) is not None)
    print(f"seeds {first}-{last}: {total} leads")
    for name, count in paths.most_common():
        print(f"  {name:36s} {count:4d}  {count / total:6.1%}")
    print(f"questions per emailed lead (all leads except certain declines): mean {statistics.mean(emailed_asks):.1f}, "
          f"max {max(emailed_asks)}, {sum(1 for n in emailed_asks if n > 12) / len(emailed_asks):.0%} over 12")
    print(f"fields missing from the raw lead: {raw_missing}; filled by the system before asking: {filled} ({filled / raw_missing:.0%})")


if __name__ == "__main__":
    args = [int(x) for x in sys.argv[1:]]
    main(args[0] if args else 1, args[1] if len(args) > 1 else 30)
