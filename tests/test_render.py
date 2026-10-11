from uwagent.assessment import build_assessment
from uwagent.models import UWDecision
from uwagent.render import render_followup, template_question


def test_one_email_carries_follow_on_questions_and_terms(seed42, registry):
    lead = seed42["LEAD-00000042-002"]
    review = build_assessment(lead, registry)
    assessment = build_assessment(lead, registry, decision=UWDecision("approve", scope=tuple(review.scope)))
    questions = [(item, template_question(item)) for item in assessment.required_asks]
    subject, body = render_followup(assessment.lead_id, assessment.values, intro="Hi.", questions=questions,
                                    closing="Thanks.", fmt=assessment.followup_format, terms=assessment.terms)
    assert "6 items needed to finalize your quote" in subject
    assert 'Only if the answer to "Is the property owned by a trust?" is yes: Name of trust?' in body
    assert "Terms to expect on the quote:\n- Personal liability coverage is excluded" in body
