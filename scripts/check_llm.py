"""One tiny live call per request shape we use, to confirm the SDK accepts them (costs well under a cent)."""

from __future__ import annotations

import sys

from uwagent.config import load_settings
from uwagent.llm import AnthropicLLM
from uwagent.moderation import ModerationResult


def main() -> int:
    settings = load_settings()
    if not settings.live_llm:
        print("Set ANTHROPIC_API_KEY in .env (and leave UW_OFFLINE unset) first.", file=sys.stderr)
        return 2
    llm = AnthropicLLM(settings.model)
    ping = {"name": "ping", "description": "Call this tool.", "strict": True,
            "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}}
    response = llm.create(system="Call the ping tool with ok=true.", messages=[{"role": "user", "content": "ping"}], tools=[ping])
    print("agent call:", response.stop_reason, [block.type for block in response.content])
    print("parse call:", llm.parse(system="Return passed=true and an empty reasons list.", user="Subject: hi\n\nHello.",
                                   output_format=ModerationResult))
    return 0


if __name__ == "__main__":
    sys.exit(main())
