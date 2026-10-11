"""Outbound communication policy (versioned text) and the banned-term lists enforced by code."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

BANNED_TERMS: tuple[str, ...] = (
    "kyc", "know your customer", "fraud", "fraudulent", "p(f)", "probability of failure", "fire simulation",
    "broker tier", "tier 1", "tier 2", "tier 3", "reputational", "spotlight", "deal killer", "rounded account",
)
FOLLOWUP_BANNED: tuple[str, ...] = ("decline", "declined", "denied", "reject", "rejected")


@dataclass(frozen=True)
class Policy:
    text: str
    version: str


def load_policy(path: Path) -> Policy:
    text = Path(path).read_text(encoding="utf-8")
    return Policy(text=text, version=hashlib.sha256(text.encode()).hexdigest()[:8])
