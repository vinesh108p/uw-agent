from uwagent import cli

from tests.fakes import make_service
from tests.support import load_queue


def test_run_prints_one_line_per_lead_in_tier_order(monkeypatch, tmp_path, capsys, registry):
    monkeypatch.setattr(cli, "build_service", lambda settings: make_service(tmp_path, registry, {42: load_queue(42)}))
    assert cli.main(["run", "--seed", "42", "--offline"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("LEAD-")]
    assert len(lines) == 10 and "Tier 1" in lines[0]
