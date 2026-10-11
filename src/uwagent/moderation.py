"""LLM professionalism/policy check on every agent-written outbound message. Fails closed."""

from __future__ import annotations

from pydantic import BaseModel

from .llm import LLM
from .policy import Policy


class ModerationResult(BaseModel):
    passed: bool
    reasons: list[str]


MODERATOR_PROMPT = """You review outbound emails from an insurance underwriting team to brokers and homeowners before they are sent.
Fail the email (passed=false) if it breaks the communication policy below, for example: unprofessional, pressuring or
blaming tone; speculation; promises about coverage, price, approval or timing; legal, tax or financial advice; any mention
of internal scoring or screening (fraud, KYC, fire-simulation scores, broker tiers); references to protected
characteristics; or questions that are vague or cannot be answered in one reply. Give short reasons when failing.
Otherwise return passed=true with an empty reasons list.

COMMUNICATION POLICY:
"""


def moderate(llm: LLM | None, policy: Policy, subject: str, body: str) -> ModerationResult:
    if llm is None:
        return ModerationResult(passed=True, reasons=[])
    try:
        result = llm.parse(system=MODERATOR_PROMPT + policy.text, user=f"Subject: {subject}\n\n{body}", output_format=ModerationResult)
    except Exception as exc:  # any API failure: fail closed so nothing unreviewed goes out
        return ModerationResult(passed=False, reasons=[f"moderation unavailable ({type(exc).__name__})"])
    if result is None:
        return ModerationResult(passed=False, reasons=["moderation declined to review"])
    return result
