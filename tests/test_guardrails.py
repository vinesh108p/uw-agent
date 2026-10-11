from uwagent.assessment import build_assessment
from uwagent.guardrails import check_content, check_followup
from uwagent.render import render_followup, template_followup_args

CASE = {"state": "NEW", "rounds_sent": 0}


def test_template_followups_pass_the_guardrails(seed42, registry, settings):
    for lead in seed42.values():
        assessment = build_assessment(lead, registry)
        if assessment.allowed_actions != ["send_followup"]:
            continue
        args = template_followup_args(assessment)
        assert check_followup(args, assessment, CASE, settings).ok
        items = {a.key: a for a in assessment.required_asks + assessment.optional_asks}
        subject, body = render_followup(assessment.lead_id, assessment.values, intro=args["intro"],
                                        questions=[(items[x["key"]], x["question"]) for x in args["items"]],
                                        closing=args["closing"], fmt=args["format"], terms=assessment.terms)
        result = check_content("followup", subject, body, lead_id=assessment.lead_id,
                               street=assessment.values.get("street_address"), registry=registry)
        assert result.ok, (lead.lead_id, result.reasons)
