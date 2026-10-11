import json

import pytest

from evals import run as eval_run
from evals.contract import expect
from evals.scoring import aggregate, render_scorecard
from uwagent.config import ROOT

from tests.fakes import make_service
from tests.support import load_queue

GOLD = json.loads((ROOT / "evals" / "gold" / "seed42.json").read_text())


@pytest.mark.parametrize("item", load_queue(42), ids=lambda item: item["lead"]["lead_id"])
def test_contract_agrees_with_blind_gold(item, registry):
    expectation = expect(item["lead"], item["debug"], registry)
    gold = GOLD[item["lead"]["lead_id"]]
    assert (expectation.action, expectation.no_email, expectation.must_ask) == (gold["action"], gold["no_email"], set(gold["must_ask"]))


def test_offline_baseline_passes_every_gate_on_seed42(tmp_path, registry):
    run = eval_run.run_seed(42, lambda db: make_service(tmp_path, registry, {42: load_queue(42)}), registry, reply_rounds=2)
    metrics = aggregate([run], mode="offline")
    assert metrics["action_accuracy"] == 1.0 and metrics["gates_passed"]
    assert "Overall: PASS" in render_scorecard(metrics)
