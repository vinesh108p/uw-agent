"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    leadgen_url: str = "http://localhost:8081"
    mailbox_url: str = "http://localhost:8025"
    db_path: Path = ROOT / "data" / "uwagent.db"
    registry_path: Path = ROOT / "sim-harness" / "shared" / "field_registry.json"
    policy_path: Path = ROOT / "policies" / "communication_policy.md"
    model: str = "claude-opus-5-5"
    live_llm: bool = False
    autosend_enabled: bool = True
    from_address: str = "underwriting@stand.example"
    max_rounds: int = 3
    ask_threshold: int = 12
    concurrency: int = 5


def load_settings() -> Settings:
    defaults = Settings()
    return Settings(
        leadgen_url=os.environ.get("LEADGEN_URL", defaults.leadgen_url),
        mailbox_url=os.environ.get("MAILBOX_URL", defaults.mailbox_url),
        db_path=Path(os.environ.get("UW_DB_PATH", defaults.db_path)),
        registry_path=Path(os.environ.get("UW_REGISTRY_PATH", defaults.registry_path)),
        policy_path=Path(os.environ.get("UW_POLICY_PATH", defaults.policy_path)),
        model=os.environ.get("UW_MODEL", defaults.model),
        live_llm=bool(os.environ.get("ANTHROPIC_API_KEY")) and not _flag("UW_OFFLINE"),
        autosend_enabled=not _flag("UW_AUTOSEND_DISABLED"),
    )
