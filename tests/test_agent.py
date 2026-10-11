from uwagent.agent import run_agent
from uwagent.moderation import ModerationResult
from uwagent.render import template_followup_args

from tests.fakes import ScriptedLLM, make_context, response, tool_use


def test_agent_writes_and_sends_the_followup(seed42, registry, tmp_path):
    ctx, mailbox = make_context(seed42["LEAD-00000042-009"], registry, tmp_path)
    ctx.llm = ScriptedLLM(responses=[response(tool_use("send_followup", template_followup_args(ctx.assessment)))],
                          parsed=[ModerationResult(passed=True, reasons=[])])
    result = run_agent(ctx)
    assert (result.action, result.ok, result.fallback) == ("send_followup", True, None) and len(mailbox.sent) == 1
    assert "acreage" in ctx.llm.create_calls[0]["messages"][0]["content"]


def test_offline_runs_on_templates(seed42, registry, tmp_path):
    ctx, mailbox = make_context(seed42["LEAD-00000042-000"], registry, tmp_path)
    result = run_agent(ctx)
    assert (result.action, result.fallback) == ("request_uw_decision", "offline") and mailbox.sent == []
