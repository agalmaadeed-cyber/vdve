"""
Tests for cross-project evaluation item a.1 (2026-07-22): unify the
misleading pre-run status label across four VDVE pipeline steps
(Ranking's adjustment_status, Generated Stress Tests' status,
Parameter Extraction's extraction_status, Recommendation's status).

Before this fix, all four reused the same value for "never attempted
this session" as they did for "a real live call was genuinely
attempted and failed" -- both rendered identically (FAILED / MISSING /
FALLBACK_REJECT) before any button was ever clicked, which reads as a
real failure. The fix is display-only (_display_status() in app.py) --
it never touches the real status value used by compute_ceiling(),
Gate 4, or any other downstream consumer.

Uses AppTest for the same reason as tests/test_app_llm_dedup.py: this
class of bug (what's on screen vs. what's really been attempted this
session) is invisible to plain unit tests -- see
vdve_project_reference.md Section 6.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


def _fake_risk_adjustment(hypotheses):
    return "[]"


def _fake_probe(spec):
    return json.dumps({"hypothesis_id": spec["target_hypothesis_id"], "severity": "LOW", "rationale": "test"})


def _fake_param_extraction(extractable):
    return "[]"


def _fake_recommendation(payload):
    return json.dumps({"outcome": "Reject", "narrative": "test", "decisive_evidence": ["A1"]})


@pytest.fixture
def patched_llm_calls(monkeypatch):
    """Same monkeypatch.setenv discipline as test_app_llm_dedup.py's fixture --
    never a module-level os.environ.setdefault (would leak into the whole
    pytest session and un-skip the two dedicated live-API-cost tests)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    patches = [
        patch("theoretical.hypothesis_extraction.ranking.call_anthropic_risk_adjustment", _fake_risk_adjustment),
        patch("theoretical.stress_tests.engine.call_anthropic_probe", _fake_probe),
        patch("theoretical.simulation.parameter_extraction.call_anthropic_parameter_extraction", _fake_param_extraction),
        patch("theoretical.decision.outcome.call_anthropic_recommendation", _fake_recommendation),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _click(at, label: str) -> bool:
    matches = [b for b in at.button if b.label == label]
    if not matches:
        return False
    matches[0].click().run()
    return True


def _enable_all_flags_and_approve(at):
    at.run()
    for key in ["flag_phrasing", "flag_risk_adj", "flag_param_extraction", "flag_probes", "flag_evidence", "flag_recommendation"]:
        at.sidebar.checkbox(key=key).set_value(True)
    at.run()
    mock_cbs = [c for c in at.checkbox if c.label.startswith("Load mock evidence")]
    if mock_cbs:
        mock_cbs[0].set_value(False)
    at.run()
    _click(at, "Approve Parameters")


def _claims_and_unknowns_dataframes(at):
    """Claims and unknowns render as two separate st.dataframe calls, but
    an empty list renders as a columnless DataFrame (no adjustment_status
    column at all) -- filter to only the non-empty ones with real rows."""
    dfs = [d for d in at.dataframe if "adjustment_status" in d.value.columns and len(d.value) > 0]
    assert len(dfs) >= 1, f"expected at least 1 non-empty ranking dataframe, found {len(dfs)}"
    return dfs


def _generated_tests_dataframe(at):
    dfs = [d for d in at.dataframe if "target_hypothesis_id" in d.value.columns]
    assert len(dfs) == 1, f"expected exactly 1 generated-tests dataframe, found {len(dfs)}"
    return dfs[0]


def test_all_flags_off_shows_not_run_everywhere():
    """Deterministic-baseline mode (no LLM key, or all flags off): every
    one of the four sites must show NOT_RUN, never FAILED/MISSING/
    FALLBACK_REJECT."""
    at = AppTest.from_file("app.py")
    at.run()
    _click(at, "Approve Parameters")

    for df in _claims_and_unknowns_dataframes(at):
        assert set(df.value["adjustment_status"]) <= {"NOT_RUN"}, df.value["adjustment_status"].tolist()

    probes_df = _generated_tests_dataframe(at)
    assert set(probes_df.value["status"]) <= {"NOT_RUN"}, probes_df.value["status"].tolist()

    captions = [c.value for c in at.caption]
    assert any("NOT_RUN" in c and "parameter" in c.lower() for c in captions), captions
    assert not any("is MISSING until" in c for c in captions), "old misleading wording must be gone"

    write_texts = [w.value for w in at.markdown if "(" in w.value and ")" in w.value]
    assert any("(NOT_RUN)" in w for w in write_texts), "recommendation status must show (NOT_RUN)"
    assert not any("FALLBACK_REJECT" in w for w in write_texts)


def test_flags_on_but_not_yet_clicked_still_shows_not_run(patched_llm_calls):
    """The core bug this fixes: flag ON but no live click yet ('live-pending')
    previously showed the exact same FAILED/MISSING/FALLBACK_REJECT as a
    genuine attempted failure. Must now still show NOT_RUN."""
    at = AppTest.from_file("app.py")
    _enable_all_flags_and_approve(at)

    for df in _claims_and_unknowns_dataframes(at):
        assert set(df.value["adjustment_status"]) <= {"NOT_RUN"}, df.value["adjustment_status"].tolist()

    probes_df = _generated_tests_dataframe(at)
    assert set(probes_df.value["status"]) <= {"NOT_RUN"}, probes_df.value["status"].tolist()

    write_texts = [w.value for w in at.markdown if "(" in w.value and ")" in w.value]
    assert any("(NOT_RUN)" in w for w in write_texts)


def test_after_genuine_live_click_shows_real_status_not_not_run(patched_llm_calls):
    """Once a live call has genuinely been attempted this session (button
    clicked, result cached), the REAL status value must be shown again --
    the override must only apply pre-attempt, never mask a genuine result."""
    at = AppTest.from_file("app.py")
    _enable_all_flags_and_approve(at)

    for label in [
        "Run live risk adjustment", "Run live parameter extraction",
        "Run live qualitative probes", "Run live recommendation",
    ]:
        assert _click(at, label), f"button '{label}' not found"
        assert at.exception == [], f"exception after clicking '{label}': {at.exception}"

    # Fakes return "[]"/no valid adjustment -> the real per-item status is a
    # genuine (attempted) "FAILED", not "NOT_RUN" -- proving the override no
    # longer suppresses a real result once one genuinely exists.
    for df in _claims_and_unknowns_dataframes(at):
        assert "NOT_RUN" not in set(df.value["adjustment_status"]), df.value["adjustment_status"].tolist()

    probes_df = _generated_tests_dataframe(at)
    assert "NOT_RUN" not in set(probes_df.value["status"]), probes_df.value["status"].tolist()

    write_texts = [w.value for w in at.markdown if "(" in w.value and ")" in w.value]
    assert not any("(NOT_RUN)" in w for w in write_texts)
