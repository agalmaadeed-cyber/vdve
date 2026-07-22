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

import hashlib
import json
import re

_FENCE_PATTERN = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def strip_json_markdown_fence(text: str) -> str:
    if not isinstance(text, str):
        return text
    matches = _FENCE_PATTERN.findall(text)
    return matches[-1].strip() if matches else text.strip()


def escape_markdown_dollar(text: str) -> str:
    """
    Streamlit's st.markdown/st.write render "$...$" as inline LaTeX
    (KaTeX) with no per-call opt-out. Free LLM text containing two or
    more literal "$" figures (e.g. cited prices) gets the text between
    them silently swallowed into a garbled math-mode render -- found
    live during the P1.3 full-cycle walkthrough (D5 evidence proposal,
    2026-07-18). Escaping to "\\$" is the standard workaround. Display
    -only: never apply this before storing or exporting the underlying
    text -- only immediately before a markdown-rendering call.
    """
    if not isinstance(text, str):
        return text
    return text.replace("$", "\\$")


def compute_payload_hash(payload) -> str:
    """
    Deterministic hash of a JSON-serializable payload -- the cache key
    app.py's live-LLM-step cache (cost-redundancy fix, P1.4 Packet #2)
    uses to detect whether a pipeline step's ACTUAL inputs changed
    since its last successful live call, never just whether a sidebar
    flag is on. sort_keys=True makes the hash stable regardless of
    dict key ordering; default=str handles any value json.dumps can't
    natively serialize defensively rather than crashing the page over
    a hashing edge case. Never used for anything security-sensitive --
    purely a change-detection key for an in-session cache.
    """
    serialized = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
