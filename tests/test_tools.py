from uwagent.render import template_followup_args, template_uw_args
from uwagent.tools import handle_tool

from tests.fakes import make_context


def test_send_followup_sends_one_email_and_advances_state(seed42, registry, tmp_path):
    ctx, mailbox = make_context(seed42["LEAD-00000042-009"], registry, tmp_path)
    ctx.use_templates = True
    assert handle_tool("send_followup", template_followup_args(ctx.assessment), ctx).ok
    [email] = mailbox.sent
    assert email["to"] == "producer+lead-00000042-009@broker.example" and email["metadata"]["items"] == ["acreage"]
    assert ctx.store.get_case(ctx.lead.lead_id)["state"] == "FOLLOW_UP_SENT"


def test_request_uw_decision_creates_a_card_with_the_planned_email(seed42, registry, tmp_path):
    ctx, mailbox = make_context(seed42["LEAD-00000042-002"], registry, tmp_path)
    ctx.use_templates = True
    assert handle_tool("request_uw_decision", template_uw_args(ctx.assessment), ctx).ok
    payload = ctx.store.open_card_for(ctx.lead.lead_id)["payload"]
    assert payload["recommendation"] == "approve" and payload["scope"] == ["condition:exclude_liability"]
    assert len(payload["asks"]) == 6 and payload["terms"] == ["Personal liability coverage is excluded"]
    assert mailbox.sent == []


def test_a_revised_quote_is_delivered(seed42, registry, tmp_path):
    from uwagent.facts import Fact

    ctx, mailbox = make_context(seed42["LEAD-00000042-009"], registry, tmp_path, extra_facts=[Fact("acreage", 0.5, "reply", "reply r1")])
    ctx.use_templates = True
    note = {"cover_note": "Thank you for the complete information. We are ready to quote this property on the terms below."}
    assert handle_tool("mark_quote_ready", note, ctx).ok and handle_tool("mark_quote_ready", note, ctx).ok
    assert len(mailbox.sent) == 2
