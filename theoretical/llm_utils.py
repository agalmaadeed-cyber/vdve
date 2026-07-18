"""
Shared defensive parsing helper (found during Packet #14's
live-fire verification, 2026-07-17): despite every system prompt
in this codebase explicitly forbidding markdown fencing, the
model sometimes wraps JSON output in ```json ... ``` once
extended thinking is disabled -- and, when a tool (e.g. web_search)
is also in play, sometimes prepends narrative prose before the
fenced block too. This searches for a fence anywhere in the text
(not anchored to the whole string) and takes the LAST match if
multiple exist, never alters genuinely-unfenced content, and is
applied before every json.loads() call on raw LLM output across
this codebase.
"""

from __future__ import annotations

import re

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def strip_json_markdown_fence(text: str) -> str:
    if not isinstance(text, str):
        return text
    matches = _FENCE_PATTERN.findall(text)
    return matches[-1].strip() if matches else text.strip()
