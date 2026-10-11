import pytest

from uwagent.config import ROOT
from uwagent.registry import Registry


@pytest.fixture(scope="session")
def registry() -> Registry:
    return Registry.load(ROOT / "sim-harness" / "shared" / "field_registry.json")

from uwagent.models import Lead

from tests.support import load_queue


@pytest.fixture(scope="session")
def seed42() -> dict[str, Lead]:
    return {item["lead"]["lead_id"]: Lead.model_validate(item["lead"]) for item in load_queue(42)}

from uwagent.config import Settings
from uwagent.policy import load_policy


@pytest.fixture(scope="session")
def policy():
    return load_policy(ROOT / "policies" / "communication_policy.md")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=tmp_path / "test.db")
