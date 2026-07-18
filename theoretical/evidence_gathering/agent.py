"""
Evidence Gathering agent (P1.0.9).

Delta-only by construction: input hypotheses always come from the
already-existing "claim"/"unknown" pool (P1.0.2's own selection --
CONFIRMED fields never become hypotheses in the first place, so this
agent structurally never re-searches an already-CONFIRMED field).

Propose, never write (P1.0.9 point 1): this module's only output is
EvidenceProposal objects. Nothing here ever writes a Dossier version
-- that happens through theoretical.dossier_versioning.version's
"evidence_update" trigger (Packet #11), only after founder approval
on a future Evidence Review screen. No upgrade authority lives here.

Three-state search_status contract (P1.0.9 point 2): "FOUND" and
"NO_EVIDENCE_FOUND" are the only two states the LLM itself may claim
-- both are trusted, completed outcomes. "NOT_SEARCHED" is reserved
for this module's own failure handling (call exception, malformed
output, an omitted hypothesis, or an ungrounded FOUND claim that
fails its own guard clause) -- retry-eligible, distinct from a
genuinely completed empty search. See this packet's §0(a).

Mandatory web search (Rule 5/6): call_anthropic_evidence_search()
invokes Anthropic's hosted web_search tool -- never a
same-knowledge-only completion. A proposal without a citable source
and excerpt is a declared failure, dropped (P1.0.9's own governance).

Stop-condition tracking (P1.0.9 point 3 -- "at most once per
dossier_version") is NOT this module's job -- storage-agnostic scope,
same precedent as Packet #11. The caller passes only hypotheses that
genuinely need (re-)searching for the given dossier_version.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from theoretical.hypothesis_extraction.scanner import Hypothesis
from theoretical.llm_utils import strip_json_markdown_fence

VALID_PROPOSED_LABELS = frozenset({"CONFIRMED", "ESTIMATE", "ASSUMPTION", "FOUNDER_OPINION"})

EVIDENCE_SEARCH_SYSTEM_PROMPT = """You research real-world evidence for a batch of business hypotheses, using web search. For each hypothesis, try to find real, current, citable evidence that confirms, contradicts, or refines the claim.

You will receive a JSON array of items: [{"hypothesis_id": str, "statement": str, "raw_text": str}, ...].

For each item, search the web as needed, then produce exactly one output object with these keys:
- "hypothesis_id": copied exactly from the input, unchanged.
- "search_status": "FOUND" if you found genuine, citable evidence; "NO_EVIDENCE_FOUND" if you searched but found nothing directly relevant or conclusive.
- "proposed_value": (only if FOUND) a concise, evidence-grounded finding.
- "proposed_evidence_label": (only if FOUND) one of "CONFIRMED", "ESTIMATE", "ASSUMPTION", "FOUNDER_OPINION" -- use CONFIRMED only if the evidence is strong, verifiable, and directly on-point; otherwise use a weaker label.
- "source": (only if FOUND) the URL or publication where you found this.
- "citation_excerpt": (only if FOUND) a short, direct quote or close paraphrase from the source that grounds proposed_value.

After any web searches you perform, your LAST output must be ONLY a JSON array, one object per input item, in the same order as the input. No prose, no markdown fencing, no explanation outside that JSON array."""


@dataclass
class EvidenceProposal:
    hypothesis_id: str
    dossier_version: int
    search_status: str  # "FOUND" | "NO_EVIDENCE_FOUND" | "NOT_SEARCHED"
    searched_at: str
    proposed_value: str | None = None
    proposed_evidence_label: str | None = None
    source: str | None = None
    citation_excerpt: str | None = None


def _build_payload(hypotheses: list[Hypothesis]) -> list[dict]:
    return [
        {"hypothesis_id": h.source_field, "statement": h.statement or h.raw_dossier_text, "raw_text": h.raw_dossier_text}
        for h in hypotheses
    ]


def call_anthropic_evidence_search(hypotheses: list[Hypothesis]) -> str:
    """
    Real LLM call, web search mandatory (Rule 5/6). Uses Anthropic's
    hosted web_search tool -- executed server-side within this single
    call. Reads ANTHROPIC_API_KEY from the environment via the SDK's
    default client behavior, same as every prior packet.

    Tool type pinned to "web_search_20250305" at time of writing --
    revisit if Anthropic's tool API surface changes. See this
    packet's §0(b) for the block-ordering assumption this function
    makes, flagged as unverified against a live call.
    """
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set in environment. This must be set "
            "locally by the founder -- never hardcoded, never committed."
        )

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        thinking={"type": "disabled"},
        system=EVIDENCE_SEARCH_SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": json.dumps(_build_payload(hypotheses), ensure_ascii=False)}],
    )
    text_blocks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return text_blocks[-1] if text_blocks else ""


def apply_evidence_search_guards(
    hypotheses: list[Hypothesis],
    raw_llm_response: str,
    dossier_version: int,
    now: str | None = None,
) -> list[EvidenceProposal]:
    """
    Deterministic governance layer (P1.0.9). Never mutates the input
    list. Every input hypothesis appears exactly once in the output,
    always -- FOUND, NO_EVIDENCE_FOUND, or NOT_SEARCHED, never absent.
    """
    timestamp = now or datetime.now(timezone.utc).isoformat()
    input_ids = {h.source_field for h in hypotheses}

    try:
        raw_llm_response = strip_json_markdown_fence(raw_llm_response)
        parsed = json.loads(raw_llm_response)
        if not isinstance(parsed, list):
            raise ValueError("not an array")
    except (json.JSONDecodeError, ValueError):
        parsed = []

    by_id: dict[str, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        hid = item.get("hypothesis_id")
        if isinstance(hid, str) and hid in input_ids and hid not in by_id:  # first match wins
            by_id[hid] = item

    results: list[EvidenceProposal] = []
    for h in hypotheses:
        item = by_id.get(h.source_field)

        if item is None:
            results.append(EvidenceProposal(
                hypothesis_id=h.source_field, dossier_version=dossier_version,
                search_status="NOT_SEARCHED", searched_at=timestamp,
            ))
            continue

        status = item.get("search_status")

        if status == "NO_EVIDENCE_FOUND":
            results.append(EvidenceProposal(
                hypothesis_id=h.source_field, dossier_version=dossier_version,
                search_status="NO_EVIDENCE_FOUND", searched_at=timestamp,
            ))
        elif status == "FOUND":
            value = item.get("proposed_value")
            label = item.get("proposed_evidence_label")
            source = item.get("source")
            excerpt = item.get("citation_excerpt")
            grounded = (
                isinstance(value, str) and value.strip()
                and label in VALID_PROPOSED_LABELS
                and isinstance(source, str) and source.strip()
                and isinstance(excerpt, str) and excerpt.strip()
            )
            if grounded:
                results.append(EvidenceProposal(
                    hypothesis_id=h.source_field, dossier_version=dossier_version,
                    search_status="FOUND", searched_at=timestamp,
                    proposed_value=value.strip(), proposed_evidence_label=label,
                    source=source.strip(), citation_excerpt=excerpt.strip(),
                ))
            else:
                # Ungrounded FOUND claim -- declared failure, dropped,
                # falls back to NOT_SEARCHED (retry-eligible). See §0(a).
                results.append(EvidenceProposal(
                    hypothesis_id=h.source_field, dossier_version=dossier_version,
                    search_status="NOT_SEARCHED", searched_at=timestamp,
                ))
        else:
            results.append(EvidenceProposal(
                hypothesis_id=h.source_field, dossier_version=dossier_version,
                search_status="NOT_SEARCHED", searched_at=timestamp,
            ))

    return results


def gather_evidence(
    hypotheses: list[Hypothesis],
    dossier_version: int,
    llm_call: Callable[[list[Hypothesis]], str] = call_anthropic_evidence_search,
    now: str | None = None,
) -> list[EvidenceProposal]:
    """
    Public entry point. A total call failure (network error, auth
    error, malformed tool response, etc.) is treated identically to a
    malformed response -- everything falls back to
    search_status="NOT_SEARCHED", nothing crashes the pipeline. Same
    doctrine as Packet #2's phrase_hypotheses().
    """
    try:
        raw_response = llm_call(hypotheses)
    except Exception:
        raw_response = ""
    return apply_evidence_search_guards(hypotheses, raw_response, dossier_version, now=now)
