"""Run the eval suites against the harness.

    uv run python -m evals.run --seeds 42 7 --reply-rounds 2 --redteam            # offline baseline (free)
    uv run --env-file .env python -m evals.run --seeds 42 --live --redteam        # live agent (spends tokens)

Requires leadgen started with DEBUG=true (`make up` does this) for the answer key.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import httpx

from uwagent.cli import build_service
from uwagent.config import ROOT, load_settings
from uwagent.llm import make_llm
from uwagent.policy import load_policy
from uwagent.registry import Registry
from uwagent.service import Service
from uwagent.tools import TERMINAL_TOOLS

from .contract import expect
from .redteam import run_redteam
from .scoring import aggregate, audit_mail, render_failures, render_scorecard, reply_extraction, score_lead

GOLD_DIR = ROOT / "evals" / "gold"
BASELINE = ROOT / "evals" / "baseline.json"


def gold_check(seed: int, store: Any, lead_ids: list[str]) -> dict[str, Any] | None:
    path = GOLD_DIR / f"seed{seed}.json"
    if not path.exists():
        return None
    gold = json.loads(path.read_text())
    mismatches: list[str] = []
    for lead_id, expected in gold.items():
        if lead_id not in lead_ids:
            mismatches.append(f"{lead_id}: not in queue")
            continue
        calls = [c for c in store.tool_calls_for(lead_id) if c["ok"] and c["tool"] in TERMINAL_TOOLS]
        if not calls:
            mismatches.append(f"{lead_id}: no action taken")
            continue
        first = calls[0]
        if first["tool"] != expected["action"]:
            mismatches.append(f"{lead_id}: action {first['tool']} != {expected['action']}")
        elif expected["action"] == "send_followup":
            keys = {item["key"] for item in first["args"]["items"]}
            missing = set(expected["must_ask"]) - keys
            if missing:
                mismatches.append(f"{lead_id}: missing asks {sorted(missing)}")
            if first["args"].get("format") != expected["format"]:
                mismatches.append(f"{lead_id}: format {first['args'].get('format')} != {expected['format']}")
        elif first["args"].get("recommendation") != expected["recommendation"]:
            mismatches.append(f"{lead_id}: recommendation {first['args'].get('recommendation')} != {expected['recommendation']}")
    return {"leads": len(gold), "mismatches": mismatches}


def run_closed_loop(service: Service, rounds: int) -> dict[str, Any]:
    """Simulated underwriter (accepts each recommendation) + producer personas, `rounds` times."""
    cards = 0
    minutes = 0.0
    carded: set[str] = set()
    for _ in range(rounds):
        for card in service.store.list_open_cards():
            payload = card["payload"]
            cards += 1
            carded.add(card["lead_id"])
            minutes += 0.5 + sum(1.0 for item in payload.get("uw_items", []) if item.get("may_decline"))
            service.resolve_card(card["id"], payload.get("recommendation") or "approve")
        service.simulate_replies()
    lead_ids = service.store.lead_ids()
    states = {lead_id: service.store.get_case(lead_id)["state"] for lead_id in lead_ids}
    return {"uw_cards": cards, "uw_minutes": minutes, "final_states": states,
            "touchless_quotes": sum(1 for lead_id, state in states.items() if state == "QUOTED" and lead_id not in carded),
            **reply_extraction(service.store, lead_ids)}


def run_seed(seed: int, make_service: Callable[[Path], Service], registry: Registry, reply_rounds: int) -> dict[str, Any]:
    service = make_service(Path(tempfile.mkdtemp(prefix=f"uweval-{seed}-")) / "eval.db")
    lead_ids = service.ingest_queue(seed=seed)
    service.advance_all()
    debugs = {lead_id: service.leadgen.get_debug(lead_id) for lead_id in lead_ids}
    scores = [score_lead(expect(service.store.get_lead(lead_id).model_dump(), debugs[lead_id], registry), service.store,
                         service.mailbox.emails_for_lead(lead_id), service.store.instance_id, registry, debugs[lead_id])
              for lead_id in lead_ids]
    gold = gold_check(seed, service.store, lead_ids)
    loop = run_closed_loop(service, reply_rounds)
    audit = audit_mail(lead_ids, service.mailbox, service.store.instance_id, registry)
    return {"seed": seed, "scores": scores, "gold": gold, "loop": loop, "audit": audit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--live", action="store_true", help="use the live agent (requires ANTHROPIC_API_KEY; spends tokens)")
    parser.add_argument("--reply-rounds", type=int, default=2)
    parser.add_argument("--redteam", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "evals" / "out"))
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)

    base = load_settings()
    if args.live and not base.live_llm:
        print("--live needs ANTHROPIC_API_KEY (and UW_OFFLINE unset)", file=sys.stderr)
        return 2
    settings = replace(base, live_llm=args.live)
    registry = Registry.load(settings.registry_path)
    try:
        runs = [run_seed(seed, lambda db: build_service(replace(settings, db_path=db)), registry, args.reply_rounds)
                for seed in args.seeds]
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            print("leadgen answer key is disabled: restart the harness with DEBUG=true (make up)", file=sys.stderr)
            return 2
        raise
    except httpx.HTTPError as exc:
        print(f"harness not reachable ({type(exc).__name__}): start it with `make up`", file=sys.stderr)
        return 2

    redteam = run_redteam(make_llm(settings), load_policy(settings.policy_path), registry) if args.redteam else None
    metrics = aggregate(runs, redteam=redteam, mode="live" if args.live else "offline")
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
    out = Path(args.out) / metrics["run_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    (out / "scorecard.md").write_text(render_scorecard(metrics, baseline))
    (out / "failures.md").write_text(render_failures(runs))
    if args.write_baseline:
        BASELINE.write_text(json.dumps(metrics, indent=2, default=str))
    print((out / "scorecard.md").read_text())
    print(f"artifacts: {out}")
    return 0 if metrics["gates_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
