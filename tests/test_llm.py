from types import SimpleNamespace

from uwagent.llm import FALLBACK_BETA, AnthropicLLM


def test_agent_call_uses_caching_low_effort_and_server_side_fallback():
    calls = []
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: calls.append(kw) or "response")))
    llm = AnthropicLLM("claude-opus-5-5", client=client)
    assert llm.create(system="S", messages=[{"role": "user", "content": "hi"}], tools=[{"name": "t"}]) == "response"
    kwargs = calls[0]
    assert kwargs["model"] == "claude-opus-5-5" and kwargs["betas"] == [FALLBACK_BETA] and kwargs["fallbacks"] == "default"
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"} and kwargs["output_config"] == {"effort": "low"}
    assert "tool_choice" not in kwargs
