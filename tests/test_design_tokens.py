"""Guard the spec's accessibility requirement: every text colour pairing in the stylesheet meets WCAG AA (4.5:1)."""

import re

from uwagent.config import ROOT

PAIRS = [
    ("ink", "bg"), ("ink-2", "bg"), ("ink-3", "bg"), ("ink-3", "surface"), ("ink-3", "surface-2"), ("ink-2", "grey-bg"),
    ("accent", "surface"), ("amber", "amber-bg"), ("red", "red-bg"), ("green", "green-bg"), ("blue", "blue-bg"),
    ("slate", "slate-bg"), ("grey", "grey-bg"), ("navy", "navy-bg"), ("amber", "surface"), ("red", "surface"), ("green", "surface"),
]


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_colours_meet_wcag_aa():
    css = (ROOT / "src" / "uwagent" / "static" / "app.css").read_text()
    tokens = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css))
    too_low = {f"{fg} on {bg}": round(_contrast(tokens[fg], tokens[bg]), 2) for fg, bg in PAIRS if _contrast(tokens[fg], tokens[bg]) < 4.5}
    assert too_low == {}
