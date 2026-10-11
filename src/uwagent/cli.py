"""Command line: `uwagent run` processes a morning queue."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import httpx

from .clients import LeadgenClient, MailboxClient
from .config import Settings, load_settings
from .llm import make_llm
from .policy import load_policy
from .registry import Registry
from .service import Service
from .store import Store


def build_service(settings: Settings) -> Service:
    return Service(settings=settings, store=Store(settings.db_path), registry=Registry.load(settings.registry_path),
                   policy=load_policy(settings.policy_path), leadgen=LeadgenClient(settings.leadgen_url),
                   mailbox=MailboxClient(settings.mailbox_url), llm=make_llm(settings))


def _settings(args: argparse.Namespace) -> Settings:
    settings = load_settings()
    if getattr(args, "offline", False):
        settings = replace(settings, live_llm=False)
    if getattr(args, "db", None):
        settings = replace(settings, db_path=Path(args.db))
    return settings


def _run(args: argparse.Namespace, settings: Settings) -> int:
    service = build_service(settings)
    print(f"mode: {'live (' + settings.model + ')' if settings.live_llm else 'offline (templates)'}")
    try:
        service.ingest_queue(seed=args.seed)
        results = {result.lead_id: result for result in service.advance_all()}
        for _ in range(args.reply_rounds):
            service.simulate_replies()
    except httpx.HTTPError as exc:
        print(f"error: leadgen is not reachable at {settings.leadgen_url} ({type(exc).__name__}). "
              "Start the harness with `make up`.", file=sys.stderr)
        return 2
    for lead_id in sorted(service.store.lead_ids(), key=service.priority):
        state = service.store.get_case(lead_id)["state"]
        result = results.get(lead_id)
        action = (result.action if result else None) or "-"
        note = (result.fallback or "") if result else ""
        print(f"{lead_id}  Tier {service.priority(lead_id)[0]}  {state:<15} {action:<20} {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uwagent")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="ingest a morning queue and drive every lead to its next action")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--offline", action="store_true", help="never call the model (deterministic templates)")
    run.add_argument("--db", help="SQLite path (default data/uwagent.db)")
    run.add_argument("--reply-rounds", type=int, default=0, help="simulate this many rounds of broker replies")
    args = parser.parse_args(argv)
    settings = _settings(args)
    if args.command == "run":
        return _run(args, settings)
    return 1


if __name__ == "__main__":
    sys.exit(main())
