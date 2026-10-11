"""FigJam underwriting playbook encoded as small decision trees."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from ..registry import Registry
from . import account, hazards
from .base import Kind, Outcome, Tree, TreeResult, evaluate
from .domains import make_domain

PLAYBOOK: dict[str, Tree] = {
    "occupancy": account.occupancy,
    "profile": account.profile,
    "fire_simulation": hazards.fire_simulation,
    "protection_class": account.protection_class,
    "roof": hazards.roof,
    "siding": hazards.siding,
    "post_pier": hazards.post_pier,
    "plumbing": hazards.plumbing,
    "electrical": hazards.electrical,
    "pools": account.pools,
    "trusts": account.trusts,
    "replacement_cost": account.replacement_cost,
}


def evaluate_playbook(values: Mapping[str, Any], registry: Registry, today: date) -> list[TreeResult]:
    domain = make_domain(registry)
    return [evaluate(name, tree, values, today, domain) for name, tree in PLAYBOOK.items()]


__all__ = ["Kind", "Outcome", "PLAYBOOK", "TreeResult", "evaluate_playbook"]
