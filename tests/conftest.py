import pytest

from uwagent.config import ROOT
from uwagent.registry import Registry


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load(ROOT / "sim-harness" / "shared" / "field_registry.json")
