"""Guardrail recall on labeled good/bad outbound emails: deterministic checks alone, and with live moderation."""

from __future__ import annotations

import json
from typing import Any

from uwagent.config import ROOT
from uwagent.guardrails import check_content
from uwagent.llm import LLM
from uwagent.moderation import moderate
from uwagent.policy import Policy
from uwagent.registry import Registry

CASES_PATH = ROOT / "evals" / "redteam" / "emails.jsonl"


def run_redteam(llm: LLM | None, policy: Policy, registry: Registry) -> dict[str, Any]:
    rows = []
    for line in CASES_PATH.read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        deterministic = check_content(case["kind"], case["subject"], case["body"], lead_id=case["lead_id"], street=None, registry=registry)
        moderation = moderate(llm, policy, case["subject"], case["body"]) if llm is not None else None
        rows.append({"id": case["id"], "label": case["label"], "violation": case.get("violation", ""),
                     "deterministic_block": not deterministic.ok,
                     "moderation_block": None if moderation is None else not moderation.passed,
                     "reasons": deterministic.reasons + ([] if moderation is None else moderation.reasons)})
    bad = [r for r in rows if r["label"] == "bad"]
    good = [r for r in rows if r["label"] == "good"]

    def blocked(row: dict[str, Any]) -> bool:
        return row["deterministic_block"] or bool(row["moderation_block"])

    return {
        "moderation": "live" if llm is not None else "offline",
        "cases": len(rows),
        "deterministic_recall": round(sum(r["deterministic_block"] for r in bad) / len(bad), 3),
        "combined_recall": round(sum(blocked(r) for r in bad) / len(bad), 3),
        "false_positive_rate": round(sum(blocked(r) for r in good) / len(good), 3),
        "rows": rows,
    }
