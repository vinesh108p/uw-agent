from uwagent.config import ROOT, load_settings


def test_settings_from_environment(monkeypatch):
    monkeypatch.delenv("UW_OFFLINE", raising=False)  # a developer's shell may force offline mode
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert load_settings().live_llm is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    settings = load_settings()
    assert settings.live_llm is True and settings.model == "claude-opus-5-5"
    assert settings.registry_path == ROOT / "sim-harness" / "shared" / "field_registry.json"


def test_board_is_published_on_loopback_only():
    assert '"127.0.0.1:8090:8090"' in (ROOT / "compose.yaml").read_text()
